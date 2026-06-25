# ai100-notebook

JupyterHub single-user image for **AI100**.

Built on `quay.io/jupyter/scipy-notebook:hub-5.5.0` and adds:

- **AI coding agents** (installed globally via Node 22), each as both a
  terminal CLI and an ACP adapter for jupyter-ai:
  - Claude Code — `@anthropic-ai/claude-code` (CLI) + `@zed-industries/claude-agent-acp` (ACP)
  - Codex — `@openai/codex` (CLI) + `@zed-industries/codex-acp` (ACP)
- **jupyter-ai 3.x** (`>=3.0,<4.0`), plus `jupyter-ai-jupyternaut` and the
  `openai`/`anthropic` Python SDKs. jupyter-ai v3 connects to coding agents over
  the Agent Client Protocol (ACP); it pulls in `jupyter-ai-acp-client`
  automatically, so the two ACP adapters above show up as chat personas.
- **jupyter-server-proxy** wired to launch **GizmoApp** on demand.
- Common JupyterLab tooling from `install-common.sh` (includes `nbgitpuller`).

## How students get GizmoApp

The [GizmoApp repo](https://github.com/kevinlb1/GizmoApp) is **not baked into
the image**. Students pull it into their home directory with an nbgitpuller
link, which lands it at `~/GizmoApp`:

```
https://<HUB_HOST>/hub/user-redirect/git-pull?repo=https://github.com/kevinlb1/GizmoApp&branch=main&urlpath=lab
```

Replace `<HUB_HOST>` with the AI100 hub hostname. This URL-encoded form is
ready to paste into a Canvas/LMS link or the course site. nbgitpuller is
merge-friendly, so re-clicking the link pulls instructor updates without
clobbering student work.

## Running GizmoApp

Once `~/GizmoApp` exists, GizmoApp appears as a **GizmoApp** tile in the
JupyterLab launcher (provided by jupyter-server-proxy). Clicking it:

1. runs `/usr/local/bin/start-gizmoapp.sh <port>`,
2. which starts `gunicorn server.wsgi:app` from `~/GizmoApp`, and
3. serves it under `<base_url>/gizmoapp/` inside the JupyterLab tab.

GizmoApp's `create_app()` runs its idempotent SQLite migrations on startup, so
no separate database init step is required. The database is written to
`~/GizmoApp/var/data/` (git-ignored in the repo).

It can also be reached directly at `…/user/<name>/gizmoapp/`.

## Build / deploy

CI (`.github/workflows/build.yml`) builds from the **repo root** as the Docker
context and pushes to ECR as `ai100-notebook` (`:latest` and the commit SHA)
whenever files under `ai100-notebook/` change. The Dockerfile therefore
references `install-common.sh` and `ai100-notebook/…` relative to the repo
root.

### Local build

```bash
# from the jupyter-images repo root
docker build -f ai100-notebook/Dockerfile -t ai100-notebook:dev .
```
