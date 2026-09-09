"""Frontend guard regressions; real Jupyter HTTP tests run when installed.

The dependency-free cases run in static CI. The runtime cases also run in the
image-contract smoke using the installed Jupyter stack, before lifecycle tests.
"""
from __future__ import annotations

import ast
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.environ.get("CW_JUPYTER_RUNTIME_TEST_ROOT", ROOT))
RUNTIME = RUNTIME_ROOT / "codingworkspace_jupyter_runtime.py"


def load_guard():
    tree = ast.parse(RUNTIME.read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "validate_jupyter_frontends")
    namespace = {"Any": object}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(RUNTIME), "exec"), namespace)
    return namespace[function.name]


class FrontendGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = load_guard()
        self.app = SimpleNamespace(jpserver_extensions={},
                                   extension_manager=SimpleNamespace(extensions={}))

    def test_plain_server_with_disabled_frontends_passes(self):
        self.app.jpserver_extensions = {"jupyterlab": False, "notebook": False}
        self.app.extension_manager.extensions["jupyterlab"] = SimpleNamespace(enabled=False)
        self.guard(self.app)

    def test_explicit_lab_and_notebook_launcher_on_plain_server_rejected(self):
        for module in ("jupyterlab.labapp", "notebook.app"):
            self.app._starter_app = type("FrontendApp", (), {"__module__": module})()
            with self.subTest(module=module), self.assertRaisesRegex(RuntimeError, "apps are forbidden"):
                self.guard(self.app)

    def test_frontend_server_subclass_rejected(self):
        app = type("LabServer", (), {"__module__": "jupyterlab.labapp"})()
        with self.assertRaisesRegex(RuntimeError, "apps are forbidden"):
            self.guard(app)

    def test_manager_enabled_frontend_rejected_despite_false_config(self):
        for name in ("jupyterlab", "notebook", "notebook_shim", "jupyter_server_proxy"):
            self.app.jpserver_extensions = {name: False}
            self.app.extension_manager.extensions = {name: SimpleNamespace(enabled=True)}
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, "Forbidden Jupyter extensions"):
                self.guard(self.app)

    def test_config_enabled_frontend_rejected_before_manager_load(self):
        self.app.jpserver_extensions = {"jupyterlab": True}
        with self.assertRaisesRegex(RuntimeError, "Forbidden Jupyter extensions"):
            self.guard(self.app)


HAS_JUPYTER = all(importlib.util.find_spec(name) is not None
                  for name in ("jupyter_server", "jupyterlab", "jupyter_server_proxy"))


@unittest.skipUnless(HAS_JUPYTER, "requires the Jupyter image runtime")
class JupyterRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cw-jupyter-frontends-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.log = self.root / "server.log"
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            self.port = listener.getsockname()[1]
        # This extension exercises the real guard at Jupyter's normal load
        # stage without starting a CW backend or accessing student state.
        (self.root / "cw_frontend_test_extension.py").write_text(
            "from codingworkspace_jupyter_runtime import validate_jupyter_frontends\n"
            "def _load_jupyter_server_extension(app):\n"
            "    validate_jupyter_frontends(app)\n"
            "    app.log.info('CW_JUPYTER_FRONTEND_GUARD_PASS')\n"
            "def _jupyter_server_extension_points():\n"
            "    return [{'module': 'cw_frontend_test_extension'}]\n"
        )
        # Extract only the actual image's frontend policy assignments. The
        # image smoke provides that config beside this test; local tests use
        # the checkout. No copied fallback policy can silently pass a regression.
        policy_path = Path(os.environ.get("CW_JUPYTER_CONFIG_TEST_PATH", ROOT / "codingworkspace_server_proxy_config.py"))
        policy_tree = ast.parse(policy_path.read_text())
        wanted = {"authorizer_class", "reraise_server_extension_failures", "terminals_enabled"}
        statements = [node for node in policy_tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Attribute) and target.attr in wanted
                              for target in node.targets)]
        self.assertEqual(len(statements), len(wanted))
        self.policy = ast.unparse(ast.Module(body=statements, type_ignores=[]))

    def start(self, command, base_url="/user/test-student/", extra_env=None):
        config = self.root / "jupyter_server_config.py"
        config.write_text(
            "from codingworkspace_jupyter_runtime import CodingWorkspaceOnlyAuthorizer\n"
            + self.policy + "\n"
            + "c.ServerApp.jpserver_extensions = " + repr({
                "cw_frontend_test_extension": True, "jupyterlab": False,
                "notebook": False, "notebook_shim": False,
                "jupyter_server_proxy": False, "jupyter_lsp": False,
            }) + "\n"
            + f"c.ServerApp.root_dir = {str(self.root)!r}\n"
        )
        env = dict(os.environ,
                   JUPYTER_CONFIG_DIR=str(self.root), JUPYTER_RUNTIME_DIR=str(self.root),
                   PYTHONPATH=os.pathsep.join((str(self.root), str(RUNTIME_ROOT))),
                   JUPYTERHUB_SINGLEUSER_APP="jupyter_server.serverapp.ServerApp")
        # Standalone smoke has no Hub service token; never inherit one from
        # an operator's environment into this self-contained local test.
        env.pop("JUPYTERHUB_API_TOKEN", None)
        env.update(extra_env or {})
        output = self.log.open("wb")
        self.addCleanup(output.close)
        process = subprocess.Popen([
            sys.executable, "-m", command,
            f"--ServerApp.config_file={config}", "--ServerApp.ip=127.0.0.1",
            f"--ServerApp.port={self.port}", "--ServerApp.port_retries=0",
            f"--ServerApp.base_url={base_url}", "--ServerApp.open_browser=False",
            "--IdentityProvider.token=cw-local-frontend-test-token",
        ], env=env, stdout=output, stderr=subprocess.STDOUT)
        def stop():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
        self.addCleanup(stop)
        return process

    def status(self, path):
        request = Request(f"http://127.0.0.1:{self.port}{path}",
                          headers={"Authorization": "token cw-local-frontend-test-token"})
        try:
            with urlopen(request, timeout=1) as response:
                return response.status
        except HTTPError as exc:
            return exc.code

    def assert_routes(self, process, base_url):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self.fail(self.log.read_text())
            try:
                if self.status(base_url + "api") == 200:
                    break
            except (URLError, TimeoutError):
                pass
            time.sleep(0.1)
        else:
            self.fail("Jupyter failed to become ready: " + self.log.read_text())
        self.assertIn("CW_JUPYTER_FRONTEND_GUARD_PASS", self.log.read_text())
        for route in ("lab", "lab/", "lab/tree/test.ipynb", "tree",
                      "api/contents", "api/kernels", "api/sessions", "api/terminals"):
            with self.subTest(route=route):
                self.assertIn(self.status(base_url + route), (403, 404))

    def test_plain_server_health_works_frontends_and_resource_apis_denied(self):
        base_url = "/user/test-student/named-server/"
        self.assert_routes(self.start("jupyter_server", base_url), base_url)

    def test_hub_singleuser_entrypoint_preserves_guard_and_route_denials(self):
        if importlib.util.find_spec("jupyterhub") is None:
            self.skipTest("requires the image JupyterHub runtime")

        class FakeHub(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/hub/api":
                    body = {"version": "5.5.0"}
                elif self.path.startswith("/hub/api/user"):
                    body = {"kind": "user", "name": "test-student", "admin": False,
                            "groups": [], "scopes": ["access:servers!server=test-student/named-server"]}
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("X-JupyterHub-Version", "5.5.0")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def log_message(self, *_args):
                pass

        hub = ThreadingHTTPServer(("127.0.0.1", 0), FakeHub)
        thread = threading.Thread(target=hub.serve_forever, daemon=True)
        thread.start()
        def stop_hub():
            hub.shutdown()
            hub.server_close()
            thread.join(timeout=5)
        self.addCleanup(stop_hub)
        base_url = "/user/test-student/named-server/"
        process = self.start("jupyterhub.singleuser", base_url, {
            "JUPYTERHUB_API_TOKEN": "cw-local-hub-service-test-token",
            "JUPYTERHUB_API_URL": f"http://127.0.0.1:{hub.server_port}/hub/api",
            "JUPYTERHUB_SERVICE_URL": f"http://127.0.0.1:{self.port}{base_url}",
            "JUPYTERHUB_SERVICE_PREFIX": base_url,
            "JUPYTERHUB_CLIENT_ID": "jupyterhub-user-test-student-named-server",
            "JUPYTERHUB_USER": "test-student",
            "JUPYTERHUB_SERVER_NAME": "named-server",
        })
        self.assert_routes(process, base_url)

    def test_explicit_lab_launcher_is_fatal_despite_disabled_config(self):
        process = self.start("jupyterlab")
        try:
            returncode = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.fail("Lab launcher continued running despite the frontend guard")
        self.assertNotEqual(returncode, 0, self.log.read_text())
        self.assertIn("Lab/Notebook apps are forbidden", self.log.read_text())
        self.assertNotIn("CW_JUPYTER_FRONTEND_GUARD_PASS", self.log.read_text())


if __name__ == "__main__":
    unittest.main()
