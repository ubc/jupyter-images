
# --- AI100: GizmoApp via jupyter-server-proxy -------------------------------
# Appended to /etc/jupyter/jupyter_server_config.py at image build time.
# `c` is already defined by the base config file above.
#
# GizmoApp is path-prefix aware (GIZMOAPP_URL_PREFIX). We run it with
# absolute_url=True and hand it the full proxied prefix ({base_url}gizmoapp)
# so its generated static/API links resolve correctly behind the proxy.
c.ServerProxy.servers = {
    "gizmoapp": {
        "command": ["/usr/local/bin/start-gizmoapp.sh", "{port}"],
        "environment": {
            "GIZMOAPP_URL_PREFIX": "{base_url}gizmoapp",
            "GIZMOAPP_SHELL": "auto",
        },
        "absolute_url": True,
        "timeout": 60,
        "launcher_entry": {
            "title": "GizmoApp",
            "enabled": True,
        },
        "new_browser_tab": False,
    }
}
