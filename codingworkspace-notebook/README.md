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

CodingWorkspace is installed from a **local checkout** — no GitHub credential is
needed, and you build exactly what is on disk (no branch push required):

```bash
# CW_SRC defaults to ../CodingWorkspace next to this repo; override if elsewhere.
ECR_ACCOUNT=123456789012 AWS_REGION=ca-central-1 \
  jupyter-images/codingworkspace-notebook/build-and-push.sh
```

The script logs into ECR, creates the repo if needed, and runs a `docker buildx`
build that installs CodingWorkspace from `CW_SRC` (passed as the `cwsrc` build
context). It prints the `singleuser.image` values to set in the z2jh
`values.yaml`. Override `IMAGE_TAG`, `CW_SRC`, `PLATFORM`, or `AWS_PROFILE` as
needed — `PLATFORM` **must** match your EKS nodes (`linux/amd64` unless
Graviton/arm64).

### CI build (later)

The repo's `build.yml` Action builds on the runner, which has no local checkout
of the source, so CI must install CodingWorkspace **from git** — and that needs a
read credential for the private repo (the default `GITHUB_TOKEN` can't read
another repo). Options: a read-only **deploy key** on kevinlb1/CodingWorkspace,
or a **collaborator token** (a classic PAT or `gh` token from an account kevinlb
has granted read access — fine-grained PATs can't cross personal accounts). Then
switch the Dockerfile's install line to the commented `git+https://...` form,
add the token as the `CODINGWORKSPACE_READ_TOKEN` secret in `ubc/jupyter-images`,
and pass `--secret id=cw_token,env=CODINGWORKSPACE_READ_TOKEN` (with
`DOCKER_BUILDKIT=1`) in the build step.

See `JUPYTERHUB_PORT_DESIGN.md` in the CodingWorkspace repo for the full design,
the `values.yaml`, and the trial/acceptance plan.
