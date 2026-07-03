
# --- CodingWorkspace via jupyter-server-proxy --------------------------------
# Appended to /etc/jupyter/jupyter_server_config.py at image build time.
# `c` is already defined by the base config file above.
#
# CodingWorkspace runs as a normal subprocess on 127.0.0.1:8768 and is served
# under the Jupyter base at /user/<name>/codingworkspace/. It reads its identity
# from JUPYTERHUB_USER (auth_mode=jupyterhub) and proxies each student's preview
# app via the sibling /user/<name>/proxy/<port>/ endpoint (websocket-capable).
#
# {base_url} is substituted by jupyter-server-proxy to the Jupyter base, e.g.
# /user/alice/.
import os

cw_env = {
    "CODINGWORKSPACE_AUTH_MODE": "jupyterhub",
    "CODINGWORKSPACE_ISOLATION_MODE": "logical",       # the pod is the sandbox
    "CODINGWORKSPACE_REMOTE_WORKERS_ENABLED": "0",     # turns run locally, in this pod
    "CODINGWORKSPACE_AGENT_BACKEND": "opencode",
    # Clone the (public) starter over HTTPS: the pod has no SSH key/known_hosts,
    # so the default git@github.com: SSH URL fails host-key verification (exit 128).
    "CODINGWORKSPACE_STARTER_REPO_URL": "https://github.com/kevinlb1/GizmoApp.git",
    "CODINGWORKSPACE_BIND_HOST": "127.0.0.1",          # only server-proxy (same pod) reaches it
    "CODINGWORKSPACE_PLATFORM_PORT": "8768",
    "CODINGWORKSPACE_URL_PREFIX": "{base_url}codingworkspace",
    "CODINGWORKSPACE_WORKSPACE_ROOT": "/home/jovyan/cw/workspaces",
    "CODINGWORKSPACE_RUN_DIR": "/home/jovyan/cw/run",
    "CODINGWORKSPACE_REPO_ROOT": "/home/jovyan/cw/repos",
    "CODINGWORKSPACE_LOG_DIR": "/home/jovyan/cw/logs",
    "CODINGWORKSPACE_STATE_DB": "/home/jovyan/cw/run/CodingWorkspace.sqlite3",
    # _preview_url() builds the sibling /proxy/<port>/ path from this at request time.
    "JUPYTERHUB_SERVICE_PREFIX": os.environ.get("JUPYTERHUB_SERVICE_PREFIX", "/"),
}

c.ServerProxy.servers = {
    "codingworkspace": {
        "command": ["python", "-m", "codingworkspace.server", "serve"],
        "port": 8768,
        # absolute_url=True: forward the full /user/<name>/codingworkspace/ path to
        # the backend (do NOT strip the prefix), matching CODINGWORKSPACE_URL_PREFIX
        # above. Same pattern as GizmoApp. With False, CW would receive "/" and 404.
        "absolute_url": True,
        "timeout": 120,
        "environment": cw_env,
        "launcher_entry": {"enabled": False},   # no notebook launcher tile
    }
}

# Land students directly in CodingWorkspace, not the Jupyter file browser.
c.ServerApp.default_url = "/codingworkspace/"
