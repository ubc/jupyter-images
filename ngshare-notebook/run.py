"""
Hardening launcher for the vendored ngshare package - wraps it without
patching its source, so it fails loudly (AttributeError) rather than
silently no-op'ing if upstream ever renames/removes what this patches.

What this adds, and why:
  - Request logging: ngshare's own startup code calls
    logging.config.fileConfig(disable_existing_loggers=True), which
    silently disables Tornado's access logger. Without this, the service
    produces no record at all of who requested what - re-enabled here,
    after that call runs, so requests actually show up in the logs.
  - XSRF cookie protection + SameSite=Lax: neither of which ngshare turns
    on itself, leaving it without standard protection against
    cross-site request forgery.
  - Request body-size cap (default 25MiB, override via
    NGSHARE_MAX_BODY_BYTES): ngshare accepts requests of unlimited size by
    default, so a single very large upload can exhaust memory/disk.
"""

import logging
import os
import sys

import ngshare.ngshare as ngs
from tornado.httpserver import HTTPServer as _RealHTTPServer

MAX_BODY_BYTES = int(os.environ.get('NGSHARE_MAX_BODY_BYTES', 25 * 1024 * 1024))

_access_log = logging.getLogger('ngshare.access')


def _log_function(handler):
    try:
        user = handler.get_current_user()
        username = user['name'] if user else '-'
    except Exception:
        username = '-'
    _access_log.info(
        '%s %s %s %d %.2fms',
        username,
        handler.request.method,
        handler.request.uri,
        handler.get_status(),
        handler.request.request_time() * 1000,
    )


_orig_app_init = ngs.MyApplication.__init__


def _patched_app_init(self, prefix, db_url, storage_path, debug=False, admin=(), autoreload=True):
    _orig_app_init(self, prefix, db_url, storage_path, debug=debug, admin=admin, autoreload=autoreload)

    # Re-enable the logger AFTER dbutil.upgrade()'s fileConfig call (inside
    # _orig_app_init) disabled it.
    _access_log.disabled = False
    if not _access_log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _access_log.addHandler(handler)
        _access_log.setLevel(logging.INFO)
        _access_log.propagate = False

    self.settings['log_function'] = _log_function
    self.settings['xsrf_cookies'] = True
    self.settings['cookie_options'] = {'samesite': 'Lax'}


def _hardened_http_server(app, *args, **kwargs):
    kwargs.setdefault('max_body_size', MAX_BODY_BYTES)
    kwargs.setdefault('max_buffer_size', MAX_BODY_BYTES)
    return _RealHTTPServer(app, *args, **kwargs)


ngs.MyApplication.__init__ = _patched_app_init
ngs.HTTPServer = _hardened_http_server


if __name__ == '__main__':
    ngs.main(sys.argv[1:])
