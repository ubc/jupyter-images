# codingworkspace-notebook CI/CD pipeline (ops)

Audience: LT Hub / AppCloud operators. The developer-facing "how do I
release" guide is `RELEASING.md` in the CodingWorkspace repo; this document
explains how the machinery works, its credentials, and the runbook.

## Flow

```text
kevinlb1/CodingWorkspace                ubc/jupyter-images                          ECR / EKS
------------------------                ------------------                          ---------
push/merge to `release`  ──(≤15 min)──▶ track-cw.yml (cron, on main)
                                          │ ls-remote release via CW_DEPLOY_KEY
                                          │ bump codingworkspace-notebook/CW_REF
                                          │   (bot commit on main)
                                          └─▶ dispatch build.yml ────────────────▶ push <ji7>-cw<cw7>
                                                │ clone CW at CW_REF (deploy key)          + :latest
                                                │ build with cwsrc context                 + :preview
                                                                                             │
preview hub profile: image :preview, image_pull_policy Always ◀──────────────── new spawns pull it
prod hub profile:    immutable <ji7>-cw<cw7> pin, changed via jhub-config PR + helm (the gate)
```

## Components

| Piece | Where | Notes |
|-------|-------|-------|
| `track-cw.yml` | `.github/workflows/`, on `main` | Cron `7,22,37,52 * * * *` + `workflow_dispatch`. Must live on the default branch: GitHub only runs scheduled workflows from there. Checks out and commits to `main` (`JI_BRANCH` env) |
| `build.yml` | `.github/workflows/`, on `main` | Unchanged multi-image build, plus: clones the private CW repo at `CW_REF` into `$RUNNER_TEMP/cw-src` (kept out of the other images' build contexts) and passes it as the `cwsrc` named context; pushes the moving `:preview` tag for this image, `main` only; **skips (not fails)** this image when the secret is unavailable (fork PRs) |
| `CW_REF` | `codingworkspace-notebook/`, on `main` | Pin file, full CW commit SHA. Owned by the tracker; manual edits get overwritten within 15 min unless the tracker is paused |
| Preview hub values | `jhub-config/config-preview-keycloak.yaml` | `ai100-codingworkspace` profile: `image: …:preview`, `image_pull_policy: Always` |
| Prod hub values | `jhub-config/config-prd-keycloak.yaml` | Must pin an immutable `<ji7>-cw<cw7>` tag. Never point prod at `:preview` or `:latest` |

Two GitHub quirks explain the workflow shape:

1. **Scheduled workflows run only from the default branch** — so `track-cw.yml`
   runs from `main`, which is also where the image sources live.
2. **Pushes made with `GITHUB_TOKEN` never trigger `push` workflows**
   (recursion guard). The tracker's bump commit alone would build nothing, so
   it explicitly dispatches `build.yml` (`workflow_dispatch` is exempt from
   the guard).

## Tags

| Tag | Meaning |
|-----|---------|
| `<ji7>-cw<cw7>` | Immutable: jupyter-images commit + CodingWorkspace commit that produced it. The only thing prod may pin |
| `preview` | Moving; always equals the newest immutable tag built from the canonical branch. The preview hub follows it |
| `latest` | Pushed by the generic build loop for every image; informational only |
| `*.dirty` | From the local fallback script with uncommitted changes; never deploy |

`docker buildx imagetools inspect <repo>:preview` shows the digest — match it
against the immutable tags to answer "what is preview running right now?"
(that's also how you pick the tag to promote to prod).

## Credentials

| Credential | Scope | Notes |
|------------|-------|-------|
| `CW_DEPLOY_KEY` (Actions secret) | Read-only deploy key on `kevinlb1/CodingWorkspace` | Used by both workflows to ls-remote/clone the private repo. ed25519, fingerprint `SHA256:rS/MKFM52MbgrnLQDX3juJvh4hfSIqlnUXOdK/xXMDc`. Exposure risk: anyone with write access to this repo can exfiltrate via a workflow edit; it grants read-only CW source access (same trust circle that ships code into student pods) |
| `GITHUB_TOKEN` | Per-run | `track-cw.yml` requests `contents: write` (bump push) + `actions: write` (dispatch) |
| AWS OIDC role `github` | ECR push | Pre-existing, unchanged |

**Rotating the deploy key:** generate a new pair
(`ssh-keygen -t ed25519 -N ''`); add the public key as a second read-only
deploy key on the CW repo; replace the `CW_DEPLOY_KEY` secret with the new
private key; run `track-cw.yml` manually to confirm; delete the old deploy
key.

## Runbook

**Verify a release went through**

```bash
gh run list --repo ubc/jupyter-images --workflow track-cw.yml --limit 3
gh run list --repo ubc/jupyter-images --workflow build.yml --branch codingworkspace-notebook --limit 3
aws ecr describe-images --repository-name codingworkspace-notebook \
  --region ca-central-1 \
  --query 'sort_by(imageDetails,&imagePushedAt)[-3:].{tags:imageTags,pushed:imagePushedAt}'
```

Expect the newest image to carry `preview` + the new immutable tag together.

**Trigger the tracker immediately** (instead of waiting ≤15 min)

```bash
gh workflow run track-cw.yml --repo ubc/jupyter-images --ref main
```

**Pause / resume the pipeline** (e.g. to hold a manual `CW_REF` pin)

```bash
gh workflow disable track-cw.yml --repo ubc/jupyter-images
gh workflow enable  track-cw.yml --repo ubc/jupyter-images
```

**Emergency rollback of preview** (skips the pipeline; server-side retag, no
pull needed)

```bash
aws ecr get-login-password --region ca-central-1 \
  | docker login --username AWS --password-stdin 032401129069.dkr.ecr.ca-central-1.amazonaws.com
docker buildx imagetools create \
  -t 032401129069.dkr.ecr.ca-central-1.amazonaws.com/codingworkspace-notebook:preview \
  032401129069.dkr.ecr.ca-central-1.amazonaws.com/codingworkspace-notebook:<last-good-immutable-tag>
```

Then pause the tracker (above) or revert the CW `release` branch, or the next
cycle re-tags `:preview` forward again. The clean rollback is a revert on
`release` — prefer it when the ~15 min cycle is acceptable.

**Promote to prod**

1. `docker buildx imagetools inspect …:preview` → find the immutable tag with
   the same digest (i.e. what preview has been running).
2. PR to `jhub-config` setting that tag in `config-prd-keycloak.yaml`.
3. Review + `helm upgrade` against the prod cluster. Diff repo vs live first
   (`helm get values`) — drift has bitten twice.

## Failure modes

| Symptom | Cause / action |
|---------|----------------|
| Tracker run green but says "No release branch" | `release` deleted/renamed in the CW repo — recreate or update `CW_BRANCH` |
| Tracker push step fails | Race with a human push to `main`; by design it does not rebase/force — the next cron run retries cleanly |
| Build red at the clone step | Deploy key removed/rotated on the CW repo, or secret missing — re-add key / secret |
| Build red at `pip install` | The CW commit broke packaging; fix forward or revert on `release` |
| Build green but `:preview` not updated | Build ran from a non-`main` branch (the retag is gated to `main`) or for another image only — check the run's "Detected changes" lines |
| Students report old behavior | Their pod predates the release — server stop/start required; pods are never hot-swapped |
| Fork PR shows the image skipped | Expected: secrets aren't available to fork PRs; the image is skipped so the PR stays green |

## Maintenance notes

- The pipeline operates entirely on `main` (the `codingworkspace-notebook`
  feature branch was merged and retired). `JI_BRANCH`, the `track-cw.yml`
  checkout, and the `build.yml` `:preview` retag gate are all `main`.
- Optional upgrades, deliberately not built yet: `repository_dispatch` from
  CW pushes for instant tracking (needs a dispatch credential in the CW
  repo; cron remains the fallback), and a re-pull DaemonSet if the
  once-per-node ~2.8 GB pull after each release becomes annoying.
- Local fallback build: `build-and-push.sh` (see `README.md`) — for testing
  uncommitted CW source; never deploy its `.dirty` tags.
