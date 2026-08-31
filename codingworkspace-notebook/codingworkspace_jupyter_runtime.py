"""Narrow Jupyter authorization and named-proxy extension for CodingWorkspace."""

from __future__ import annotations

import os
import re
import secrets
import time
from typing import Any

from jupyter_server.auth import Authorizer
from jupyter_server_proxy.config import ServerProxy as ServerProxyConfig
from jupyter_server_proxy.config import make_handlers


TERMINATION_GRACE_ENV = "CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS"
# The kubelet starts the termination grace-period clock before it invokes an
# exec preStop hook. Keep these budgets in one trusted runtime module so the
# Jupyter child timeout is derived from, rather than independent of, the Hub
# profile's asserted grace period.
KUBELET_POST_HOOK_RESERVE_SECONDS = 6
PRESTOP_DISCOVERY_RESERVE_SECONDS = 2
PRESTOP_PROCESS_EXIT_RESERVE_SECONDS = 2
PRESTOP_REPLACEMENT_QUIET_SECONDS = 2
PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS = 15
MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS = 30
MAX_CODINGWORKSPACE_SHUTDOWN_SECONDS = 90


def parse_termination_grace_seconds(raw_value: object) -> int:
    """Validate the Hub-provided copy of terminationGracePeriodSeconds."""

    value = str(raw_value if raw_value is not None else "")
    if (
        value != value.strip()
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 4
    ):
        raise ValueError(f"{TERMINATION_GRACE_ENV} must be a positive integer")
    seconds = int(value)
    if value != str(seconds):
        raise ValueError(f"{TERMINATION_GRACE_ENV} must use canonical decimal form")
    minimum = (
        KUBELET_POST_HOOK_RESERVE_SECONDS
        + PRESTOP_DISCOVERY_RESERVE_SECONDS
        + PRESTOP_PROCESS_EXIT_RESERVE_SECONDS
        + PRESTOP_REPLACEMENT_QUIET_SECONDS
        + PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS
        + MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS
    )
    if seconds < minimum:
        raise ValueError(
            f"{TERMINATION_GRACE_ENV} must be at least {minimum} seconds "
            "for bounded shutdown and checkpoint verification"
        )
    if seconds > 3600:
        raise ValueError(f"{TERMINATION_GRACE_ENV} must not exceed 3600 seconds")
    return seconds


def derive_codingworkspace_shutdown_seconds(termination_grace_seconds: int) -> int:
    """Reserve hook/checkpoint time and return the child shutdown deadline."""

    available = termination_grace_seconds - (
        KUBELET_POST_HOOK_RESERVE_SECONDS
        + PRESTOP_DISCOVERY_RESERVE_SECONDS
        + PRESTOP_PROCESS_EXIT_RESERVE_SECONDS
        + PRESTOP_REPLACEMENT_QUIET_SECONDS
        + PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS
    )
    shutdown_seconds = min(MAX_CODINGWORKSPACE_SHUTDOWN_SECONDS, available)
    if shutdown_seconds < MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS:
        raise ValueError("termination grace leaves no safe CodingWorkspace shutdown budget")
    return shutdown_seconds


class CodingWorkspaceOnlyAuthorizer(Authorizer):
    """Deny every Jupyter resource except read-only server health metadata.

    This blocks ``contents``/``files``, ``kernels``, ``sessions``, and
    ``terminals`` resources. The Notebook and Lab extensions are separately
    disabled, so their ``/tree`` and ``/lab`` frontends are not registered.
    Unknown extension resources are denied by the same default.
    """

    _allowed = frozenset({("read", "api")})
    explicitly_denied_resources = frozenset(
        {
            "config",
            "contents",
            "files",
            "kernels",
            "kernelspecs",
            "nbconvert",
            "server",
            "sessions",
            "terminals",
        }
    )

    def is_authorized(
        self, handler: Any, user: Any, action: str, resource: str
    ) -> bool:
        del handler, user
        return (str(action), str(resource)) in self._allowed


def _load_jupyter_server_extension(server_app: Any) -> None:
    """Register only CodingWorkspace; never register /proxy/<host>:<port>."""

    class_modules = {cls.__module__.partition(".")[0] for cls in type(server_app).mro()}
    if class_modules.intersection({"jupyterlab", "notebook"}):
        raise RuntimeError(
            "CodingWorkspace requires plain Jupyter Server; Lab/Notebook apps are forbidden"
        )

    extension_states = dict(getattr(server_app, "jpserver_extensions", {}) or {})
    forbidden_enabled = sorted(
        name
        for name in ("jupyter_server_proxy", "jupyterlab", "notebook", "notebook_shim")
        if extension_states.get(name)
    )
    if forbidden_enabled:
        raise RuntimeError(
            "Forbidden Jupyter extensions are enabled: " + ", ".join(forbidden_enabled)
        )

    serverproxy_config = ServerProxyConfig(parent=server_app)
    if set(serverproxy_config.servers) != {"codingworkspace"}:
        raise RuntimeError("Exactly one named CodingWorkspace proxy must be configured")
    process = serverproxy_config.servers["codingworkspace"]
    if (
        list(process.command)
        != [
            "/opt/conda/bin/python",
            "-I",
            "-P",
            "-m",
            "codingworkspace.server",
            "serve",
        ]
        or process.port != 8768
        or not process.absolute_url
    ):
        raise RuntimeError("The CodingWorkspace named proxy contract was overridden")

    environment = dict(process.environment) if isinstance(process.environment, dict) else {}
    header_overrides = (
        dict(process.request_headers_override)
        if isinstance(process.request_headers_override, dict)
        else {}
    )
    environment_token = environment.get("CODINGWORKSPACE_PROXY_AUTH_TOKEN", "")
    header_token = header_overrides.get("X-CodingWorkspace-Proxy-Token", "")
    if (
        len(environment_token) < 32
        or len(header_token) < 32
        or not secrets.compare_digest(environment_token, header_token)
    ):
        raise RuntimeError(
            "The named proxy must overwrite the CodingWorkspace capability header "
            "with the per-server backend token"
        )
    try:
        termination_grace_seconds = parse_termination_grace_seconds(
            os.environ.get(TERMINATION_GRACE_ENV)
        )
        expected_shutdown_seconds = derive_codingworkspace_shutdown_seconds(
            termination_grace_seconds
        )
    except ValueError as exc:
        raise RuntimeError(
            "The Hub termination grace assertion is missing or unsafe"
        ) from exc
    required_environment = {
        "CODINGWORKSPACE_AUTH_MODE": "jupyterhub",
        "CODINGWORKSPACE_ISOLATION_MODE": "bubblewrap",
        "CODINGWORKSPACE_ISOLATION_OPENCODE_COMMAND": "/usr/local/bin/opencode",
        "CODINGWORKSPACE_REMOTE_WORKERS_ENABLED": "0",
        "CODINGWORKSPACE_PERSONAL_MODEL_AUTH_ENABLED": "0",
        "CODINGWORKSPACE_GITHUB_BACKUP_ENABLED": "0",
        "CODINGWORKSPACE_REPOSITORY_IMPORT_HOST": "github.students.cs.ubc.ca",
        "CODINGWORKSPACE_SQLITE_JOURNAL_MODE": "DELETE",
        "CODINGWORKSPACE_SQLITE_SYNCHRONOUS": "FULL",
        TERMINATION_GRACE_ENV: str(termination_grace_seconds),
        "CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS": str(
            expected_shutdown_seconds
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONSAFEPATH": "1",
    }
    overridden = sorted(
        name for name, value in required_environment.items() if environment.get(name) != value
    )
    if overridden:
        raise RuntimeError(
            "The CodingWorkspace Hub safety environment was overridden: "
            + ", ".join(overridden)
        )
    if not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+",
        str(environment.get("CODINGWORKSPACE_OPENCODE_RUNTIME_VERSION") or ""),
    ):
        raise RuntimeError("The baked OpenCode runtime version is missing")
    try:
        credential_issued_at_epoch = int(
            environment["CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH"]
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "The model credential issue time must be captured when Jupyter starts"
        ) from exc
    current_epoch = int(time.time())
    if credential_issued_at_epoch != 0 and not (
        1_700_000_000 <= credential_issued_at_epoch <= current_epoch + 300
    ):
        raise RuntimeError(
            "The model credential issue time must be 0 or a plausible operator-supplied epoch"
        )

    handlers = make_handlers(server_app.web_app.settings["base_url"], [process])
    server_app.web_app.add_handlers(".*", handlers)
    server_app.log.info(
        "[codingworkspace] Named proxy enabled; arbitrary port proxying disabled"
    )


def _jupyter_server_extension_points() -> list[dict[str, str]]:
    return [{"module": "codingworkspace_jupyter_runtime"}]


load_jupyter_server_extension = _load_jupyter_server_extension
_jupyter_server_extension_paths = _jupyter_server_extension_points
