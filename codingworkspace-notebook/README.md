# codingworkspace-notebook

A JupyterHub single-user image for **CodingWorkspace**, the course-controlled
agentic coding UI. Students land in CodingWorkspace at
`/user/<name>/codingworkspace/`; its application preview remains in the same
authenticated Hub origin.

## Production boundary

The pod belongs to one authenticated student and one retained home. Repository
code is still untrusted. CodingWorkspace-launched applications, installers,
validation commands, and coding agents therefore run through the fail-closed
Bubblewrap profile. The image also removes Jupyter's unused terminal, kernel,
contents, Notebook, and JupyterLab surfaces so an authenticated student cannot
use Jupyter itself to start an unsandboxed same-UID process or read private
control-plane files.

The managed CodingWorkspace process listens only on `127.0.0.1:8768`.
`jupyter-server-proxy` generates one random capability per Jupyter Server
process, supplies it to CodingWorkspace, and overwrites the corresponding
request header on proxied requests. A direct loopback request without that
capability is rejected. The header protects the control API; it does not claim
network isolation. Cluster egress and production user-namespace behavior remain
deployment acceptance gates.

Personal GitHub backup, personal model login, repository-executing remote
workers, the local media pilot, and browser project selection are disabled in
JupyterHub. Student coding models use only the centrally injected, student-
scoped LiteLLM credential. The image deliberately has no global OpenCode config
that would let direct CLI use consume that pod credential.

The model-key mint hook should also inject
`CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH` with the key's actual Unix
issuance time. The image preserves and validates that value. When it is absent,
CodingWorkspace receives `0` and labels process-observed age as only a lower
bound; a Jupyter restart must never pretend that an older key was newly minted.
Gateway `401`/`403` responses remain authoritative.

Jupyter configuration and its runtime files do not come from the retained home.
The root-selected config is beneath `/opt`; cookies/server records use the
per-container, mode-0700 `/tmp/codingworkspace-jupyter-runtime`. This prevents a
retained `~/.jupyter` or prior runtime file from controlling the next server.
`PYTHONNOUSERSITE=1`, `PYTHONSAFEPATH=1`, and the proxy's absolute isolated
Python command (`-I -P`) also prevent retained `~/.local` packages or the
working directory from shadowing the trusted CodingWorkspace installation.

## Pod shutdown hook

The image installs `/usr/local/sbin/codingworkspace-prestop`. The Hub profile
must run that exact command as the non-root notebook user in the pod's
Kubernetes `preStop` hook and retain `terminationGracePeriodSeconds: 120`.
Add the hook and paired grace-period values to the existing CodingWorkspace
profile's `kubespawner_override` (the comments mark existing entries that must
remain):

```yaml
singleuser:
  profileList:
    - slug: ai100-codingworkspace
      kubespawner_override:
        # Preserve every other existing extra_pod_config value.
        extra_pod_config:
          terminationGracePeriodSeconds: 120
        # Preserve every other existing environment value.
        environment:
          CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS: "120"
        # Add preStop alongside the profile's existing postStart entry.
        lifecycle_hooks:
          preStop:
            exec:
              command:
                - /usr/local/sbin/codingworkspace-prestop
```

This is a fragment to merge into that existing profile, not a complete profile
definition. KubeSpawner does not merge a profile's `lifecycle_hooks` with
top-level `singleuser.lifecycleHooks`: the profile value replaces the top-level
map. Therefore keep the profile's existing `postStart` entry as a sibling of
`preStop`; configuring only `singleuser.lifecycleHooks` will not install this
hook for the CodingWorkspace profile.

The pod field and
`CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS` are one deployment
contract and must always change together. Kubernetes does not expose the pod's
actual termination-grace field to the child process, so the environment value
is the runtime's trusted mirror for deriving a bounded hook budget. Hub-config
CI must compare the two configured values, and preview-Hub acceptance must
confirm that the resulting pod spec and container environment still agree.

The helper:

- accepts exactly one same-UID child with the immutable Python command, cwd,
  parent, and fail-closed Hub environment expected by this image;
- opens a Linux pidfd, revalidates the child, sends that exact process SIGTERM,
  and derives its child timeout and whole-hook deadline from the required
  `CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS` value;
- treats zero same-UID exact-command processes as an idempotent `not-running`
  success, but rejects any matching process whose full identity is ambiguous,
  changed, or invalid without falling back to a PID-reuse-prone signal;
- requires one newly published `shutdown` SQLite checkpoint and a complete
  `PRAGMA quick_check` of that checkpoint within the mandatory integrity
  reserve; then, if the remaining budget permits, performs a separately bounded
  best-effort check of the closed primary database for telemetry only; and
- emits a credential-free `CW_ALERT` and exits nonzero on every unsafe outcome.

With the required 120-second deployment contract, the derived budgets preserve
CodingWorkspace's 90-second child timeout, the supervisor-replacement quiet
interval, at least 15 seconds for the mandatory complete checkpoint check, and
six seconds after the hook for kubelet termination. The redundant primary check
uses at most five seconds; a warning or budget-based skip does not invalidate a
verified shutdown checkpoint or make the hook fail.

`jupyter-server-proxy` 4.5.0 uses simpervisor 1.0.0. A clean CodingWorkspace
SIGTERM returns zero and is not restarted; a nonzero exit would be restarted,
which the helper detects. Simpervisor's own Jupyter SIGTERM handler forwards the
signal but exits the parent immediately without awaiting the child, so it is
not a substitute for this blocking preStop hook. The actual cluster must prove
pidfd/proc access, hook execution, checkpoint publication, and the 120-second
grace against the accepted image digest.

## Immutable inputs

The trusted build resolves three reviewed inputs:

| Input | Pin / source |
| --- | --- |
| Notebook base | Digest-pinned `quay.io/jupyter/base-notebook:hub-5.5.0` in `Dockerfile` |
| CodingWorkspace | Normally the tracker-owned full SHA in `CW_REF`, equal to the CodingWorkspace `release` head on `jupyter-images` main. A reviewed-main manual dispatch may provide a separate exact full-SHA candidate without editing `CW_REF`, but that override can never promote. Private source is cloned with the read-only deploy key and converted to a bundle-only `cwsrc` build context. |
| GizmoApp starter | Full SHA in `GIZMOAPP_REF`; public source is cloned and converted to a bundle-only `gizmosrc` build context |

The GizmoApp checkout is baked at
`/opt/codingworkspace-starters/GizmoApp`, remains a SHA-1 Git repository, and is
root-owned and non-writable. New projects clone from that local source without
requiring a network or student Git credential. Network imports are limited to
credential-free HTTPS repositories on `github.students.cs.ubc.ca`.

The build verifies the exact source SHAs after checkout, creates self-contained
Git bundles that advertise only those detached commits, and re-verifies the
bundle commits inside the image build. This works across Buildx drivers without
transferring checkout credentials or Git configuration. Image labels and the
workflow's release-evidence artifact record the full CodingWorkspace and
GizmoApp commits. Dependency versions and checksums are fixed in the Dockerfile
and its pin files. The complete Python 3.13 proxy runtime is installed only from
hash-locked binary wheels reviewed for both Linux amd64 and arm64; update the
requirements and both architecture checks together.

## Validation and publication

`build.yml` separates untrusted validation from trusted publication:

- Every pull request, including a fork PR, runs non-secret image selection with
  `contents: read` and no AWS or source-repository secret. CodingWorkspace or
  workflow changes additionally run its static/configuration suite; an
  unrelated image change does not inherit or depend on CodingWorkspace lint.
- A reviewed image-source push to `main` builds CodingWorkspace with the
  currently released source pin and may publish an immutable candidate. It
  **does not** move `preview` or `latest`.
- A trusted manual dispatch of reviewed `main` may supply an exact lowercase
  40-character `codingworkspace_candidate_sha`. The workflow verifies that the
  private clone contains that exact commit, records it in the immutable tag and
  evidence, leaves tracker-owned `CW_REF` unchanged, and rejects any request
  that also enables promotion.
- `track-cw.yml` follows CodingWorkspace's `release` branch. When that branch
  moves, the tracker updates `CW_REF` and explicitly dispatches a trusted build
  with promotion enabled. That dispatch is the normal and only automatic path
  that moves CodingWorkspace's `preview` and `latest` tags.
- An image-source PR must not update `CW_REF` to an unreleased commit. Such a
  pin has not passed the release gate and the tracker would replace it with the
  actual `release` head on its next run.
- Production must pin the accepted immutable image digest in the Hub profile;
  it must never follow `preview` or `latest`.

The two CodingWorkspace credential-bearing jobs—the hardened build and release
tracker—use the `codingworkspace-publication` environment. Repository
administrators must restrict that environment to deployments from `main`, store
`CW_DEPLOY_KEY` only there (removing any repository-level copy), and configure
the AWS role to trust only the exact GitHub OIDC subject
`repo:ubc/jupyter-images:environment:codingworkspace-publication` (plus the
intended audience). GitHub uses the environment—not the ref—in `sub` for jobs
that name an environment, so the environment's deployment rule enforces main.
A branch-editable workflow `if` condition is defense in depth, not a credential
boundary by itself.

The separate ordinary-image job deliberately retains this repository's prior
branch/tag short-SHA and `latest` publication behavior; it does not receive the
CodingWorkspace deploy key and does not inherit CodingWorkspace lint, SBOM, or
Trivy policy.

Trusted CodingWorkspace builds generate a Syft SPDX JSON SBOM, a complete Trivy
vulnerability report, BuildKit provenance/SBOM attestations in ECR, and a
release record with the source commits and resulting image digest. A second
Trivy pass automatically rejects any fixable CRITICAL finding while the
complete all-severity, fixed-and-unfixed JSON report remains available for
human review. The artifact includes `published-image.txt` plus `SHA256SUMS` and
is retained for 90 days only as a transfer window. Before production,
operations must verify the checksums and copy the exact bundle into the
course's independently backed-up, indefinite release record.

See [PIPELINE.md](PIPELINE.md) for credentials, promotion, rollback, and failure
handling.

## Tests

The non-secret check used on pull requests is:

```bash
codingworkspace-notebook/ci/validate-static.sh
```

It validates full pins, Python/shell/YAML syntax, immutable Action references,
the publication/promotion boundary, the pinned GitHub host key, and the expected
Docker/Jupyter hardening contract.

After a trusted local image build, the portable image contract smoke is:

```bash
codingworkspace-notebook/ci/smoke-image.sh contract \
  IMAGE "$(codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/CW_REF)" \
  "$(codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/GIZMOAPP_REF)"
```

An operator can build and scan one committed, unreleased CodingWorkspace
candidate through the trusted workflow without changing the release pin:

```bash
gh workflow run build.yml --repo ubc/jupyter-images --ref main \
  -f publish=true \
  -f scope=codingworkspace-notebook \
  -f promote_codingworkspace=false \
  -f codingworkspace_candidate_sha=0123456789abcdef0123456789abcdef01234567
```

Replace the example SHA with the intended private-repository commit. Candidate
overrides are evidence-producing tests only; advance the CodingWorkspace
`release` branch and let `track-cw.yml` update `CW_REF` for an accepted release.

On a Docker host that permits unprivileged user, mount, and PID namespaces, run:

```bash
codingworkspace-notebook/ci/smoke-image.sh namespace IMAGE
codingworkspace-notebook/ci/smoke-image.sh lifecycle IMAGE CW_FULL_SHA GIZMO_FULL_SHA
```

The lifecycle harness covers a fresh home, exact-empty legacy credential
directory cleanup, retained-home Python user-site shadow resistance and restart,
local starter creation, Bubblewrap,
proxy capability rejection, forbidden Jupyter routes, readiness, the exact
preStop helper, a new shutdown checkpoint with mandatory full integrity check,
and bounded best-effort primary-database telemetry,
missing-target refusal, and safe `CW-JH-STARTUP-001` refusal for nonempty,
linked, and specially typed stale state. It creates uniquely named temporary
containers and volumes and removes only those fixtures on exit.

These tests do not substitute for the preview-Hub acceptance run. The reviewed
image still must be tested with the production pod security context and kernel,
an actual retained EFS home, LiteLLM injection/expiry, the deployed preStop and
120-second grace period, culling, network policy, CloudWatch filters, and an
administrator-owned backup restore.

## Local fallback build

`build-and-push.sh` accepts local CodingWorkspace and GizmoApp checkouts and
passes both named contexts without a GitHub source credential:

```bash
ECR_ACCOUNT=123456789012 \
AWS_REGION=ca-central-1 \
CW_SRC=/path/to/CodingWorkspace \
GIZMO_SRC=/path/to/GizmoApp \
codingworkspace-notebook/build-and-push.sh
```

Both local source checkout HEADs must match `CW_REF` and `GIZMOAPP_REF` and must
have no tracked, staged, or untracked changes. The publisher also refuses any
tracked change in jupyter-images itself. A test source must first be
committed and its full pin deliberately updated, so image labels never describe
different content. The script builds and loads locally, runs the non-root image
contract, generates a checksummed CycloneDX SBOM and complete Trivy report,
enforces the same fixable-CRITICAL gate, and only then authenticates to ECR and
pushes. Its recorded `published-image.txt` names the resulting registry digest.
`PLATFORM` must match the EKS nodes; production promotion still uses the trusted
workflow, accepted digest, and independent release-record gate.
