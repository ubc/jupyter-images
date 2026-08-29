"""Fail-closed Jupyter Server configuration for CodingWorkspace pods."""

from __future__ import annotations

import os
import secrets
import sys
import time


RUNTIME_ROOT = "/opt/codingworkspace-jupyter/runtime"
if RUNTIME_ROOT not in sys.path:
    sys.path.insert(0, RUNTIME_ROOT)

from codingworkspace_jupyter_runtime import (  # noqa: E402
    TERMINATION_GRACE_ENV,
    CodingWorkspaceOnlyAuthorizer,
    derive_codingworkspace_shutdown_seconds,
    parse_termination_grace_seconds,
)


proxy_token = secrets.token_urlsafe(48)
try:
    termination_grace_seconds = parse_termination_grace_seconds(
        os.environ.get(TERMINATION_GRACE_ENV)
    )
    codingworkspace_shutdown_seconds = derive_codingworkspace_shutdown_seconds(
        termination_grace_seconds
    )
except ValueError as exc:
    raise RuntimeError(
        f"The Hub profile must inject {TERMINATION_GRACE_ENV} from the same "
        "configuration value used for the pod termination grace period"
    ) from exc
raw_credential_issued_at_epoch = os.environ.get(
    "CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH", "0"
).strip()
try:
    parsed_credential_issued_at_epoch = int(raw_credential_issued_at_epoch)
except ValueError as exc:
    raise RuntimeError(
        "CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH must be a non-negative Unix epoch"
    ) from exc
if (
    parsed_credential_issued_at_epoch < 0
    or parsed_credential_issued_at_epoch > int(time.time()) + 300
):
    raise RuntimeError(
        "CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH must be 0 or a plausible past Unix epoch"
    )
credential_issued_at_epoch = str(parsed_credential_issued_at_epoch)
allowed_models = os.environ.get(
    "CODINGWORKSPACE_ALLOWED_MODELS", "openai/gpt-5.4-mini"
).strip()
default_model = os.environ.get(
    "CODINGWORKSPACE_DEFAULT_MODEL", "openai/gpt-5.4-mini"
).strip()
allowed_model_set = {item.strip() for item in allowed_models.split(",") if item.strip()}
if not allowed_model_set or default_model not in allowed_model_set:
    raise RuntimeError(
        "CODINGWORKSPACE_DEFAULT_MODEL must be present in the non-empty "
        "CODINGWORKSPACE_ALLOWED_MODELS allowlist"
    )

cw_root = "/home/jovyan/cw"
cw_run = f"{cw_root}/run"
cw_env = {
    "CODINGWORKSPACE_CONFIG_FILE": "/opt/codingworkspace-jupyter/runtime/CodingWorkspace.env",
    "CODINGWORKSPACE_AUTH_MODE": "jupyterhub",
    "CODINGWORKSPACE_PROXY_AUTH_TOKEN": proxy_token,
    "CODINGWORKSPACE_BIND_HOST": "127.0.0.1",
    "CODINGWORKSPACE_PLATFORM_PORT": "8768",
    "CODINGWORKSPACE_URL_PREFIX": "{base_url}codingworkspace",
    "JUPYTERHUB_SERVICE_PREFIX": os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/"),
    # Retained ~/.local packages and the working directory cannot shadow the
    # trusted installed package. The absolute child command also uses -I/-P.
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
    "CODINGWORKSPACE_ADMIN_USERS": os.environ.get("CODINGWORKSPACE_ADMIN_USERS", ""),
    # Mandatory child-process boundary for untrusted repositories.
    "CODINGWORKSPACE_ISOLATION_MODE": "bubblewrap",
    "CODINGWORKSPACE_BUBBLEWRAP_COMMAND": "/usr/bin/bwrap",
    "CODINGWORKSPACE_BUBBLEWRAP_RUNTIME_ROOTS": "/usr:/opt",
    "CODINGWORKSPACE_AGENT_BACKEND": "opencode",
    "CODINGWORKSPACE_OPENCODE_COMMAND": "/usr/local/bin/opencode",
    "CODINGWORKSPACE_ISOLATION_OPENCODE_COMMAND": "/usr/local/bin/opencode",
    "CODINGWORKSPACE_LOCAL_AGENT_MODEL_PROXY_ENABLED": "1",
    # Remote code execution and unfinished multi-pod features are forbidden.
    "CODINGWORKSPACE_REMOTE_WORKERS_ENABLED": "0",
    "CODINGWORKSPACE_APP_MEDIA_PROXY_ENABLED": "0",
    "CODINGWORKSPACE_MEDIA_WORKERS_ENABLED": "0",
    "CODINGWORKSPACE_MEDIA_VOICE_CLONE_ENABLED": "0",
    "CODINGWORKSPACE_PROJECT_SELECTION_ENABLED": "0",
    "CODINGWORKSPACE_INSTITUTIONAL_GIT_ENABLED": "0",
    # Centrally injected, student-scoped LiteLLM only.
    "CODINGWORKSPACE_PERSONAL_MODEL_AUTH_ENABLED": "0",
    "CODINGWORKSPACE_MODEL_DISCOVERY_ENABLED": "1",
    "CODINGWORKSPACE_MODEL_DISCOVERY_CACHE_SECONDS": "300",
    "CODINGWORKSPACE_AI_BUDGET_LOOKUP_ENABLED": "0",
    "CODINGWORKSPACE_MODEL_CREDENTIAL_LIFETIME_SECONDS": "172800",
    "CODINGWORKSPACE_MODEL_CREDENTIAL_WARNING_SECONDS": "21600",
    "CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH": credential_issued_at_epoch,
    "CODINGWORKSPACE_ALLOWED_MODELS": allowed_models,
    "CODINGWORKSPACE_DEFAULT_MODEL": default_model,
    # No personal Git credential. Imports are credential-free UBC CS HTTPS only.
    "CODINGWORKSPACE_GITHUB_BACKUP_ENABLED": "0",
    "CODINGWORKSPACE_REPOSITORY_IMPORT_ENABLED": "1",
    "CODINGWORKSPACE_REPOSITORY_IMPORT_HOST": "github.students.cs.ubc.ca",
    "CODINGWORKSPACE_STARTER_REPO_URL": "/opt/codingworkspace-starters/GizmoApp",
    # Explicit retained-home paths.
    "CODINGWORKSPACE_WORKSPACE_ROOT": f"{cw_root}/workspaces",
    "CODINGWORKSPACE_ISOLATED_WORKSPACE_ROOT": f"{cw_root}/isolated-workspaces",
    "CODINGWORKSPACE_REPO_ROOT": f"{cw_root}/repos",
    "CODINGWORKSPACE_LOG_DIR": f"{cw_root}/logs",
    "CODINGWORKSPACE_RUN_DIR": cw_run,
    "CODINGWORKSPACE_STATE_DB": f"{cw_run}/CodingWorkspace.sqlite3",
    "CODINGWORKSPACE_RESTART_DRAIN_FILE": f"{cw_run}/restart-drain",
    "CODINGWORKSPACE_GITHUB_CREDENTIALS_DIR": f"{cw_run}/github-credentials",
    "CODINGWORKSPACE_OPENCODE_AUTH_ROOT": f"{cw_run}/opencode-auth",
    "CODINGWORKSPACE_OPENCODE_UPDATE_DIR": f"{cw_run}/opencode-updates",
    "CODINGWORKSPACE_WORKER_SCRATCH_ROOT": f"{cw_run}/worker-scratch",
    "CODINGWORKSPACE_WORKER_TOKEN_FILE": f"{cw_run}/worker-token",
    "CODINGWORKSPACE_MEDIA_WORKER_TOKEN_FILE": f"{cw_run}/media-worker-token",
    # EFS-safe SQLite and bounded same-PVC checkpoints.
    "CODINGWORKSPACE_SQLITE_JOURNAL_MODE": "DELETE",
    "CODINGWORKSPACE_SQLITE_SYNCHRONOUS": "FULL",
    "CODINGWORKSPACE_SQLITE_BACKUP_INTERVAL_SECONDS": "900",
    "CODINGWORKSPACE_SQLITE_BACKUP_MAX_MB": "512",
    # App admission/readiness limits; hard EFS limits remain a Hub concern.
    "CODINGWORKSPACE_WORKSPACE_DISK_QUOTA_MB": "2048",
    "CODINGWORKSPACE_WORKSPACE_FILE_QUOTA": "100000",
    "CODINGWORKSPACE_TOTAL_STORAGE_QUOTA_MB": "5120",
    "CODINGWORKSPACE_MIN_FREE_DISK_MB": "512",
    "CODINGWORKSPACE_MAX_WORKSPACES_PER_USER": "20",
    "CODINGWORKSPACE_MAX_USER_RUNNING_TURNS": "1",
    "CODINGWORKSPACE_MAX_USER_QUEUED_TURNS": "2",
    # Derive the child deadline from the Hub's asserted pod grace period. The
    # preStop helper independently repeats this calculation and refuses a
    # mismatched child or parent process.
    TERMINATION_GRACE_ENV: str(termination_grace_seconds),
    "CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS": str(
        codingworkspace_shutdown_seconds
    ),
}

# Preserve unrelated system entries, but explicitly defeat auto-discovery of
# every user-facing Jupyter surface and the stock arbitrary-port proxy.
c.ServerApp.jpserver_extensions.update(
    {
        "jupyter_server_proxy": False,
        "jupyterlab": False,
        "notebook": False,
        "notebook_shim": False,
        "codingworkspace_jupyter_runtime": True,
    }
)
c.ServerApp.authorizer_class = CodingWorkspaceOnlyAuthorizer
c.ServerApp.terminals_enabled = False
c.ServerApp.root_dir = "/opt/codingworkspace-jupyter/empty-root"
c.ServerApp.default_url = "/codingworkspace/"
c.ServerApp.open_browser = False
c.ServerApp.quit_button = False

c.ServerProxy.servers = {
    "codingworkspace": {
        "command": [
            "/opt/conda/bin/python",
            "-I",
            "-P",
            "-m",
            "codingworkspace.server",
            "serve",
        ],
        "port": 8768,
        # Preserve /user/<name>/codingworkspace/... for the prefix-aware app.
        "absolute_url": True,
        "timeout": 120,
        "environment": cw_env,
        "request_headers_override": {
            # Tornado HTTPHeaders.update replaces any client-supplied value.
            "X-CodingWorkspace-Proxy-Token": proxy_token,
        },
        "launcher_entry": {"enabled": False},
    }
}
