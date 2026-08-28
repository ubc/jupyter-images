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
The helper:

- accepts exactly one same-UID child with the immutable Python command, cwd,
  parent, and fail-closed Hub environment expected by this image;
- opens a Linux pidfd, revalidates the child, sends that exact process SIGTERM,
  and waits up to 105 seconds so CodingWorkspace receives its full 90-second
  internal drain/checkpoint budget;
- treats zero same-UID exact-command processes as an idempotent `not-running`
  success, but rejects any matching process whose full identity is ambiguous,
  changed, or invalid without falling back to a PID-reuse-prone signal;
- requires one newly published `shutdown` SQLite checkpoint, then runs
  `PRAGMA quick_check` against both it and the closed primary database, with a
  monotonic wall timer plus SQLite progress handler enforcing a 114-second
  whole-hook ceiling; and
- emits a credential-free `CW_ALERT` and exits nonzero on every unsafe outcome.

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
| CodingWorkspace | Full SHA in `CW_REF`; private source is cloned with the read-only deploy key and passed as the `cwsrc` build context |
| GizmoApp starter | Full SHA in `GIZMOAPP_REF`; public source is cloned and passed as the `gizmosrc` build context |

The GizmoApp checkout is baked at
`/opt/codingworkspace-starters/GizmoApp`, remains a SHA-1 Git repository, and is
root-owned and non-writable. New projects clone from that local source without
requiring a network or student Git credential. Network imports are limited to
credential-free HTTPS repositories on `github.students.cs.ubc.ca`.

The build verifies the exact source SHAs after checkout. Image labels and the
workflow's release-evidence artifact record the full CodingWorkspace and
GizmoApp commits. Dependency versions and checksums are fixed in the Dockerfile
and its pin files. The complete Python 3.13 proxy runtime is installed only from
hash-locked binary wheels reviewed for both Linux amd64 and arm64; update the
requirements and both architecture checks together.

## Validation and publication

`build.yml` separates untrusted validation from trusted publication:

- Every pull request, including a fork PR, runs static/configuration tests with
  `contents: read` and no AWS or source-repository secret.
- A reviewed `main` push may build, smoke-test, scan, and publish an immutable
  image. For CodingWorkspace it **does not** move `preview` or `latest`.
- `track-cw.yml` follows CodingWorkspace's `release` branch. When that branch
  moves, the tracker updates `CW_REF` and explicitly dispatches a trusted build
  with promotion enabled. That dispatch is the normal and only automatic path
  that moves CodingWorkspace's `preview` and `latest` tags.
- Production must pin the accepted immutable image digest in the Hub profile;
  it must never follow `preview` or `latest`.

The credential-bearing jobs use the `codingworkspace-publication` environment.
Repository administrators must restrict that environment to deployments from
`main`, store `CW_DEPLOY_KEY` only there (removing any repository-level copy),
and configure the AWS role to trust only the exact GitHub OIDC subject
`repo:ubc/jupyter-images:environment:codingworkspace-publication` (plus the
intended audience). GitHub uses the environment—not the ref—in `sub` for jobs
that name an environment, so the environment's deployment rule enforces main.
A branch-editable workflow `if` condition is defense in depth, not a credential
boundary by itself.

Trusted builds generate a Syft SPDX JSON SBOM, a complete Trivy vulnerability
report, BuildKit provenance/SBOM attestations in ECR, and a release record with
the source commits and resulting image digest. A second Trivy pass automatically
rejects any fixable CRITICAL finding while the complete all-severity,
fixed-and-unfixed JSON report remains available for human review. The artifact
includes `published-image.txt` plus `SHA256SUMS` and is retained for 90 days only
as a transfer window. Before production, operations must verify the checksums
and copy the exact bundle into the course's independently backed-up, indefinite
release record.

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

On a Docker host that permits unprivileged user, mount, and PID namespaces, run:

```bash
codingworkspace-notebook/ci/smoke-image.sh namespace IMAGE
codingworkspace-notebook/ci/smoke-image.sh lifecycle IMAGE CW_FULL_SHA GIZMO_FULL_SHA
```

The lifecycle harness covers a fresh home, exact-empty legacy credential
directory cleanup, retained-home Python user-site shadow resistance and restart,
local starter creation, Bubblewrap,
proxy capability rejection, forbidden Jupyter routes, readiness, the exact
preStop helper, a new shutdown checkpoint plus independent SQLite quick checks,
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
