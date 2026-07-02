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

### Local build + push (current path)

While the CodingWorkspace source repo is private and no CI credential is
configured, build and push manually with `build-and-push.sh`:

```bash
# 1. Push the branch/tag the Dockerfile references, so pip-from-git can fetch it.
git -C /path/to/CodingWorkspace push origin jupyterhub-port

# 2. Build for the cluster's arch and push to ECR (run from anywhere).
ECR_ACCOUNT=123456789012 AWS_REGION=ca-central-1 \
  jupyter-images/codingworkspace-notebook/build-and-push.sh
```

The script logs into ECR, creates the repo if needed, and runs a
`docker buildx` build that injects the private-repo read token via a BuildKit
secret (default token: `gh auth token`). It prints the `singleuser.image`
values to set in the z2jh `values.yaml`. Override `IMAGE_TAG`, `CW_TOKEN`, or
`PLATFORM` as needed — `PLATFORM` **must** match your EKS nodes (`linux/amd64`
unless Graviton/arm64).

### CI build (later)

The repo's `build.yml` Action can build and push this image automatically when
files here change, but it needs a Git credential for the private source repo
(the default `GITHUB_TOKEN` can't read another repo). To enable it: add a
read-only deploy key or fine-grained PAT as the `CODINGWORKSPACE_READ_TOKEN`
secret in `ubc/jupyter-images`, then pass
`--secret id=cw_token,env=CODINGWORKSPACE_READ_TOKEN` (with `DOCKER_BUILDKIT=1`)
in the build step.

## Before it builds cleanly

- **Pin the CodingWorkspace ref.** The `pip install ... @git+...@jupyterhub-port`
  line in the `Dockerfile` tracks the port branch; change it to a tag/SHA once
  merged.

See `JUPYTERHUB_PORT_DESIGN.md` in the CodingWorkspace repo for the full design,
the `values.yaml`, and the trial/acceptance plan.
