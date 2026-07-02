# codingworkspace-notebook

A JupyterHub single-user image that runs **CodingWorkspace** — an
instructor-controlled agentic-coding UI (a frontend for [opencode.ai](https://opencode.ai))
— instead of the standard notebook interface.

## How it works

The image bases on `quay.io/jupyter/base-notebook` (pinned `hub-` tag), so it
speaks the JupyterHub single-user contract (OAuth handshake, port binding,
activity/culling) out of the box. On top of that:

- **CodingWorkspace** is installed from its Git repo and runs as a subprocess on
  `127.0.0.1:8768`, exposed by **jupyter-server-proxy** at
  `/user/<name>/codingworkspace/`. `default_url` sends students straight there —
  they never see JupyterLab.
- **OpenCode** is installed as the coding agent CodingWorkspace drives. This
  image deliberately does **not** install `jupyter-ai` or the ACP adapters used
  by `ai100-notebook`; the whole point is the controlled CodingWorkspace UI.
- Each student's **preview app** is proxied by server-proxy at
  `/user/<name>/proxy/<port>/`, which carries websockets and streaming.
- Per-student state (workspaces, repos, SQLite metadata, logs) lives under
  `/home/jovyan/cw`, on the per-user persistent volume.

Identity comes from `JUPYTERHUB_USER` (CodingWorkspace runs with
`CODINGWORKSPACE_AUTH_MODE=jupyterhub`); the pod is one student, so it is also
the isolation boundary (`CODINGWORKSPACE_ISOLATION_MODE=logical`, remote workers
disabled).

## Building

Built and pushed to ECR by the repo's `build.yml` Action when files under this
directory change. The ECR repo is named `codingworkspace-notebook`; that name +
the 7-char commit SHA tag is what `singleuser.image` points at in the z2jh
`values.yaml`.

## Before it builds cleanly

- **Pin the CodingWorkspace ref.** The `pip install ... @git+...@jupyterhub-port`
  line in the `Dockerfile` tracks the port branch; change it to a tag/SHA once
  merged.
- **Repo access.** If `kevinlb1/CodingWorkspace` is private, add a Git credential
  to the build Action (it currently has only AWS OIDC + ECR permissions).

See `JUPYTERHUB_PORT_DESIGN.md` in the CodingWorkspace repo for the full design,
the `values.yaml`, and the trial/acceptance plan.
