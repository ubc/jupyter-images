#!/usr/bin/env bash
# Post-build smoke test for ngshare-notebook. Run as:
#   ngshare-notebook/ci/smoke.sh IMAGE_REF
set -euo pipefail

IMAGE="${1:?usage: smoke.sh IMAGE_REF}"

# No curl in the python:3.12-slim-bookworm base - everything here uses the
# stdlib instead. Script piped to `python3 -` via stdin rather than -c, to
# stay out of nested-quoting hell.
docker run --rm -i --entrypoint python3 "$IMAGE" - <<'PYEOF'
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread


def fail(msg):
    print('FAIL: ' + msg, file=sys.stderr)
    sys.exit(1)


# Stand in for the hub: ngshare's user_for_token() does a GET to
# $JUPYTERHUB_API_URL/user with the caller's token and trusts whatever 200
# JSON comes back - good enough to exercise real auth without a real hub.
class FakeHubHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'name': 'smoketest', 'admin': False}).encode())

    def log_message(self, *args):
        pass


fake_hub = HTTPServer(('127.0.0.1', 8000), FakeHubHandler)
Thread(target=fake_hub.serve_forever, daemon=True).start()

env = dict(os.environ)
env.update(
    JUPYTERHUB_API_URL='http://127.0.0.1:8000/hub/api',
    JUPYTERHUB_API_TOKEN='smoke-test-api-token',
    JUPYTERHUB_CLIENT_ID='smoke-test-client',
    JUPYTERHUB_SERVICE_PREFIX='/services/ngshare/',
    JUPYTERHUB_SERVICE_URL='http://0.0.0.0:12121/services/ngshare/',
)

# --admins smoketest: matches the fake hub's returned username, so the
# POST below exercises a full admin-gated handler end to end, not just
# the auth layer.
proc = subprocess.Popen(
    [
        'python3', '/ngshare/run.py',
        '--database', 'sqlite:////tmp/ngshare-smoke.db',
        '--storage', '/tmp/ngshare-smoke-storage/',
        '--admins', 'smoketest',
    ],
    env=env,
)

try:
    healthz_url = 'http://127.0.0.1:12121/services/ngshare/healthz'
    for _ in range(60):
        try:
            with urllib.request.urlopen(healthz_url, timeout=1) as r:
                if r.status == 200:
                    break
        except (urllib.error.URLError, ConnectionError):
            pass
        if proc.poll() is not None:
            fail('ngshare exited early with code %r' % proc.returncode)
        time.sleep(0.5)
    else:
        fail('ngshare never became healthy')

    # The regression this guards: xsrf_cookies=True with no token
    # exemption meant check_xsrf_cookie() rejected every non-GET request
    # authenticated only by an Authorization header - Tornado's generic
    # 403 HTML page, before any ngshare code ran. A real ngshare JSON
    # response (success or error) proves the request reached ngshare's
    # own routing instead.
    req = urllib.request.Request(
        'http://127.0.0.1:12121/services/ngshare/course/smoke-test-course',
        method='POST',
        headers={'Authorization': 'token smoke-test-user-token'},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            body = r.read()
    except urllib.error.HTTPError as e:
        status = e.code
        body = e.read()

    print('POST status: %d' % status)
    print(body.decode(errors='replace'))

    if status == 403 and b'<html' in body.lower():
        fail(
            "got Tornado's generic XSRF 403 HTML page - the "
            'Authorization-header exemption is broken'
        )

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        fail("response body is not valid JSON - request never reached ngshare's own handler")

    if 'success' not in parsed:
        fail('response JSON has no "success" key: %r' % (parsed,))

    print('OK')
    time.sleep(0.3)  # let any pending access-log write flush before we kill it
finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    fake_hub.shutdown()
PYEOF
