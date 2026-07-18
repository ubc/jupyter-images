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
- **LiteLLM wiring**: `/etc/opencode/opencode.json` (`OPENCODE_CONFIG`) defines
  a `litellm` provider that resolves `OPENAI_BASE_URL` / `OPENAI_API_KEY` from
  the pod env — the hub's AI100 `pre_spawn_hook` injects both (per-student
  virtual key). The model list and default (`litellm/gpt-5.4-mini`) must be
  kept in sync with the models the AI100 LiteLLM team actually serves, or
  direct `opencode` use 403s. This covers direct `opencode` invocations;
  CodingWorkspace-driven turns construct their own OpenCode env and
  per-workspace config, so pointing the CodingWorkspace UI at LiteLLM is
  configured in CodingWorkspace itself, not here.
- Each student's **preview app** is proxied by server-proxy at
  `/user/<name>/proxy/<port>/`, which carries websockets and streaming.
- Per-student state (workspaces, repos, SQLite metadata, logs) lives under
  `/home/jovyan/cw`, on the per-user persistent volume.

Identity comes from `JUPYTERHUB_USER` (CodingWorkspace runs with
`CODINGWORKSPACE_AUTH_MODE=jupyterhub`); the pod is one student, so it is also
the isolation boundary (`CODINGWORKSPACE_ISOLATION_MODE=logical`, remote workers
disabled).

## Building

### CI build (the normal path)

The repo's `build.yml` Action builds and pushes this image even though the
CodingWorkspace source repo (kevinlb1/CodingWorkspace) is private:

- **`CW_REF`** (in this directory) pins the CodingWorkspace ref to build —
  prefer a full commit SHA so builds are reproducible. **Bumping it is the
  release action**: the change triggers the Action, which rebuilds this image
  with the new source.
- The workflow clones the private repo at that ref using the read-only
  **`CW_DEPLOY_KEY`** Actions secret (a deploy key on the CodingWorkspace
  repo), into `RUNNER_TEMP` so it stays out of the other images' build
  contexts, and passes it to the build as the `cwsrc` named context the
  Dockerfile expects.
- The pushed tag is `<jupyter-images sha>-cw<codingworkspace sha>` — set that
  as `singleuser.image.tag` in the z2jh values. (`latest` is also pushed, but
  pin the full tag.)
- When the secret is unavailable (e.g. pull requests from forks) the image is
  skipped, not failed, so unrelated PRs stay green.

So a release is: edit `CW_REF` (and/or files here), commit, push, wait for the
Action, then point the hub values at the printed tag.

### Local build + push (fallback)

`build-and-push.sh` builds from a **local checkout** — useful for testing
uncommitted CodingWorkspace changes, since no GitHub credential is needed and
you build exactly what is on disk:

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
Graviton/arm64). Local builds tag `<sha>-cw<sha>.dirty` when either tree has
uncommitted changes — don't deploy `.dirty` tags.

See `JUPYTERHUB_PORT_DESIGN.md` in the CodingWorkspace repo for the full design,
the `values.yaml`, and the trial/acceptance plan.
