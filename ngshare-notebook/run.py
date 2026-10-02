"""
Hardening launcher for the vendored ngshare package - wraps it without
patching its source, so it fails loudly (AttributeError) rather than
silently no-op'ing if upstream ever renames/removes what this patches.

What this adds, and why:
  - Request logging: ngshare's own startup code calls
    logging.config.fileConfig (from dbutil.upgrade(), inside main(), before
    MyApplication is ever constructed), which defaults to
    disable_existing_loggers=True and silently disables every logger that
    already existed - Tornado's access/application/general loggers
    included. Patched here, before any ngshare code runs, so none of them
    get disabled in the first place.
  - XSRF cookie protection + SameSite/HttpOnly/Secure on the auth cookie:
    none of which ngshare turns on itself, leaving it without standard
    protection against cross-site request forgery. Header-token requests
    (the only kind nbgrader/the hub ever send) are exempted the same way
    JupyterHub's own HubAuth does: a browser never attaches an
    Authorization header to a cross-site form POST, so CSRF only applies
    to the cookie session.
  - Request body-size cap (default 25MiB, override via
    NGSHARE_MAX_BODY_BYTES): ngshare accepts requests of unlimited size by
    default, so a single very large upload can exhaust memory/disk. Must
    stay below the pod's memory limit (see README) - a request under this
    cap can still hold several decoded copies of its payload in memory.
"""

import logging
import logging.config
import os
import sys

import ngshare.ngshare as ngs
from tornado.httpserver import HTTPServer as _RealHTTPServer

MAX_BODY_BYTES = int(os.environ.get('NGSHARE_MAX_BODY_BYTES', 25 * 1024 * 1024))

_access_log = logging.getLogger('ngshare.access')

# dbutil.upgrade() -> alembic -> alembic/env.py calls
# logging.config.fileConfig(config.config_file_name) with no explicit
# disable_existing_loggers argument, so it defaults to True and disables
# every logger that already existed, not just the ones alembic.ini
# configures. Patched here, before main() ever calls dbutil.upgrade(), so
# nothing gets disabled in the first place - fixing the cause instead of
# re-enabling one logger after the fact.
_orig_file_config = logging.config.fileConfig


def _file_config(*args, **kwargs):
    kwargs['disable_existing_loggers'] = False
    return _orig_file_config(*args, **kwargs)


logging.config.fileConfig = _file_config


def _log_function(handler):
    # handler.user was already resolved in MyRequestHandler.prepare(); a
    # second handler.get_current_user() here would be an uncached
    # requests.get to the hub on every single request.
    user = getattr(handler, 'user', None)
    username = user.id if user else '-'
    _access_log.info(
        '%s %s %s %s %d %.2fms',
        handler.request.remote_ip,
        username,
        handler.request.method,
        # request.path, not request.uri: the latter includes the query
        # string, which for the OAuth callback carries the auth `code`.
        handler.request.path,
        handler.get_status(),
        handler.request.request_time() * 1000,
    )


_orig_app_init = ngs.MyApplication.__init__


def _patched_app_init(self, prefix, db_url, storage_path, debug=False, admin=(), autoreload=False):
    _orig_app_init(self, prefix, db_url, storage_path, debug=debug, admin=admin, autoreload=autoreload)

    if not _access_log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
        _access_log.addHandler(handler)
        _access_log.setLevel(logging.INFO)
        _access_log.propagate = False

    self.settings['log_function'] = _log_function
    self.settings['xsrf_cookies'] = True


# Tornado runs check_xsrf_cookie() before prepare() for any non-GET
# request when xsrf_cookies is on. MyRequestHandler never calls
# HubAuth._get_user (it overrides get_current_user with its own
# requests.get), so _token_authenticated never gets set and every
# token-authenticated write (nbgrader submit/release, roster sync, ...)
# gets a 403 before any ngshare code runs. Mirror HubAuth's own exemption:
# a browser can't attach Authorization to a cross-site form POST, so CSRF
# only applies to the cookie-authenticated path.
_orig_check_xsrf_cookie = ngs.MyRequestHandler.check_xsrf_cookie


def _check_xsrf_cookie(self):
    if 'Authorization' in self.request.headers:
        self._token_authenticated = True
        return
    return _orig_check_xsrf_cookie(self)


ngs.MyRequestHandler.check_xsrf_cookie = _check_xsrf_cookie


# When check_xsrf_cookie rejects a request, prepare() never ran, so
# self.db was never set - on_finish() still runs and the original
# `self.db.close()` raises AttributeError.
def _on_finish(self):
    db = getattr(self, 'db', None)
    if db is not None:
        db.close()


ngs.MyRequestHandler.on_finish = _on_finish


# ngshare's own set_secure_cookie('ngshare-oauth-token', token) call sets
# no cookie attributes at all - settings['cookie_options'] (the previous
# approach here) is read by neither Tornado nor ngshare, so it was a
# no-op. Wrap the one call site that actually sets this cookie instead.
#
# Once XSRF applies to the cookie-authenticated path, home.html's forms
# will 403 (they don't embed xsrf_form_html()) - the web page becomes
# read-only, which is the intended effect; see README.
_orig_set_secure_cookie = ngs.JupyterHubLoginHandler.set_secure_cookie


def _set_secure_cookie(self, name, value, *args, **kwargs):
    if name == 'ngshare-oauth-token':
        kwargs.setdefault('httponly', True)
        kwargs.setdefault('secure', True)
        kwargs.setdefault('samesite', 'Lax')
    return _orig_set_secure_cookie(self, name, value, *args, **kwargs)


ngs.JupyterHubLoginHandler.set_secure_cookie = _set_secure_cookie


def _hardened_http_server(app, *args, **kwargs):
    kwargs.setdefault('max_body_size', MAX_BODY_BYTES)
    kwargs.setdefault('max_buffer_size', MAX_BODY_BYTES)
    # Behind the hub's proxy (see ngshare.py's "Must listen on all
    # interfaces for proxy"), so trust its X-Forwarded-For/X-Real-IP for
    # request.remote_ip instead of logging the proxy's own address.
    kwargs.setdefault('xheaders', True)
    return _RealHTTPServer(app, *args, **kwargs)


ngs.MyApplication.__init__ = _patched_app_init
ngs.HTTPServer = _hardened_http_server


if __name__ == '__main__':
    ngs.main(sys.argv[1:])
