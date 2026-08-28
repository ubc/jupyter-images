# codingworkspace-notebook CI/CD pipeline

Audience: LT Hub/AppCloud operators and course release maintainers. This
runbook describes the trust boundary, source pins, artifacts, promotion, and
rollback. The CodingWorkspace repository's `RELEASING.md` remains the
developer-facing release guide.

## Trust-separated flow

```text
fork or same-repo PR
  └─ validate: no secrets, no AWS, no image publication

reviewed jupyter-images main push
  └─ validate → build/push immutable candidate → pull exact digest
                                                  └─ image smoke + SBOM/vulnerability scan
                                                     (CodingWorkspace preview/latest stay put)

CodingWorkspace release branch moves
  └─ track-cw.yml (main, every 15 min or manual)
       ├─ resolve release with read-only CW_DEPLOY_KEY
       ├─ update the full SHA in CW_REF and push with GITHUB_TOKEN
       └─ explicitly dispatch build.yml on main with
            publish=true
            scope=codingworkspace-notebook
            promote_codingworkspace=true
              └─ build/push immutable digest → pull/smoke/scan that digest
                                             └─ move preview + latest only after checks

preview Hub: follows preview for new spawns
production Hub: pins the accepted immutable digest through jhub-config review
```

The tracker's `GITHUB_TOKEN` push does not trigger another push workflow, so a
release movement results in the one explicitly dispatched image build, not a
push build plus a second dispatch build. If GitHub changes that recursion
behavior or the tracker is changed to use a PAT/App token, preserve an explicit
duplicate-build guard.

An image-source merge can therefore be reviewed and merged while
CodingWorkspace `release` remains on a rollback commit: the merge produces an
immutable candidate but cannot alter either moving CodingWorkspace tag. Do not
manually dispatch promotion merely to test an image PR.

## Workflow policy

`build.yml` has three stages:

1. **Non-secret validation.** Runs for all PRs and `main` pushes with only
   `contents: read`. It validates source-pin format, workflow/YAML/Python/shell
   syntax, the source/promotion trust boundary, immutable Action pins, GitHub's
   pinned SSH host key, and the expected image/config hardening. Fork PR code
   never receives AWS OIDC permission or `CW_DEPLOY_KEY`.
2. **Trusted selection.** Determines changed image directories. A root-level
   shared build input rebuilds all images; docs/workflow-only changes do not
   silently publish an image. An explicit dispatch can select changed images,
   all images, or only `codingworkspace-notebook`.
3. **Trusted build/publish/scan/promote.** Runs only for a push to `main`, or a
   `workflow_dispatch` of `main` with `publish=true`. It resolves exact sources,
   publishes one immutable ECR image with BuildKit provenance/SBOM attestations,
   resolves and pulls that exact ECR digest, and runs the CodingWorkspace smoke,
   Syft, and Trivy against the pulled digest. Moving tags occur only after every
   check succeeds. A rejected immutable candidate may remain in ECR for
   diagnosis, but it is never promoted.

For non-CodingWorkspace images, a trusted `main` publication retains the
existing behavior of moving `latest`. For `codingworkspace-notebook`, both
`latest` and `preview` require all of these conditions:

- the event is `workflow_dispatch`;
- the workflow is running the reviewed `main` ref;
- `publish=true`; and
- `promote_codingworkspace=true`.

`ci/validate_ci_policy.py` regression-tests these conditions and the tracker
dispatch. Branch protection on `main` and required validation remain an
administrator setting outside this repository.

## Immutable source resolution

| Input | Resolution and verification |
| --- | --- |
| jupyter-images | The checked-out full `GITHUB_SHA` on reviewed `main` |
| CodingWorkspace | Exactly one lowercase 40-character SHA in `CW_REF`; private clone with `CW_DEPLOY_KEY`; detached checkout must equal that SHA |
| GizmoApp | Exactly one lowercase 40-character SHA in `GIZMOAPP_REF`; credential-free public clone; detached checkout must equal that SHA and use SHA-1 object format |
| Base image | Version tag plus `sha256` digest in `Dockerfile` |
| OpenCode and other runtime tools | Fixed versions/checksums in reviewed image pin files |

The private clone uses the checked-in GitHub Ed25519 host key at
`ci/github_known_hosts` with strict host checking. Static validation compares
its key fingerprint with GitHub's published
`SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU`. Review and update the key
from GitHub's official metadata/documentation if GitHub rotates it; never fall
back to `accept-new` or a live unverified `ssh-keyscan`.

Candidate tags are run-unique because this ECR repository must also support the
moving `preview`/`latest` tags and is therefore tag-mutable. CodingWorkspace uses
`<ji7>-cw<cw7>-gz<gizmo7>-r<run-id>-a<attempt>`; other images use
`<ji7>-r<run-id>-a<attempt>`. A rerun cannot overwrite an earlier candidate.
Tags are still pointers, not sufficient release evidence. The full GizmoApp and
CodingWorkspace commits, jupyter-images commit, tested ECR digest, scanner
versions, and workflow run are stored in the 90-day workflow artifact and image
labels. Production should record/copy that evidence into the course release
record before artifact expiry.

## Credentials and permissions

| Credential/capability | Scope | Used where |
| --- | --- | --- |
| `CW_DEPLOY_KEY` | Read-only deploy key for `kevinlb1/CodingWorkspace` | Trusted tracker and trusted CodingWorkspace image build only |
| AWS GitHub OIDC role `github` | ECR repository/image publication | Trusted build job only (`id-token: write`) |
| `GITHUB_TOKEN` | `contents: write`, `actions: write` | Tracker only, to update `CW_REF` and dispatch the trusted build |
| Public HTTPS | Read-only GizmoApp clone and fixed scanner/runtime artifacts | Trusted build |

The deploy-key file is created with a restrictive umask under `RUNNER_TEMP`, is
never passed into Docker, and is removed by a shell trap. The private clone is a
named BuildKit context; it is not part of the default repository context.

Third-party Actions are pinned by full commit SHA. The currently reviewed
major/release refs were resolved to these commits on 2026-08-27:

| Action | Immutable commit | Reviewed ref |
| --- | --- | --- |
| `actions/checkout` | `11d5960a326750d5838078e36cf38b85af677262` | `v4` |
| `docker/setup-buildx-action` | `8d2750c68a42422c14e847fe6c8ac0403b4cbd6f` | `v3` |
| `aws-actions/configure-aws-credentials` | `7474bc4690e29a8392af63c5b98e7449536d5c3a` | `v4` (peeled commit; `ff7170…` is the annotated tag object) |
| `aws-actions/amazon-ecr-login` | `03f1aad4c6c7ffd436567f42f9384779290529bd` | `v2` |
| `anchore/sbom-action` | `e22c389904149dbc22b58101806040fa8d37a610` | `v0` |
| `aquasecurity/trivy-action` | `57a97c7e7821a5776cebc9bb87c984fa69cba8f1` | `0.35.0` |
| `actions/upload-artifact` | `ea165f8d65b6e75b540449e92b4886f43607fa02` | `v4` |

Re-resolve and review the upstream source before changing any SHA. A Dependabot
or automated pin update is a proposed change, not authority to publish.

## SBOM, vulnerability, and release evidence

The trusted job publishes the immutable candidate once, resolves its registry
digest, pulls that exact digest, and then scans it:

- Syft `v1.51.1` writes SPDX JSON;
- Trivy `v0.74.0` writes a JSON report containing all severities, fixed and
  unfixed; and
- the pushed BuildKit result includes maximum provenance plus an SBOM
  attestation.

The workflow artifact also records the exact source revisions, tested ECR
tag/digest, workflow run, and whether CodingWorkspace promotion was requested.
Scanner-generation or smoke failure blocks moving-tag promotion, though the
immutable candidate already pushed may remain for diagnosis. Finding a
vulnerability does not currently fail the build (`exit-code: 0`): a release
reviewer must triage the report, record accepted exceptions with an owner/expiry,
and block promotion for an unacceptable finding. Converting that review into
severity/exception policy is follow-up work; silently treating a generated
report as a security pass is not acceptable.

## Automated and deployment smoke tests

The trusted job runs:

```bash
codingworkspace-notebook/ci/smoke-image.sh contract IMAGE CW_FULL_SHA GIZMO_FULL_SHA
```

It verifies the non-root runtime user, pinned Jupyter components, Bubblewrap and
OpenCode executables, exact immutable starter checkout, source labels, and
absence of the global direct-OpenCode credential path.

Before moving `release`, run on a compatible Docker/cluster host:

```bash
codingworkspace-notebook/ci/smoke-image.sh namespace IMAGE
codingworkspace-notebook/ci/smoke-image.sh lifecycle IMAGE CW_FULL_SHA GIZMO_FULL_SHA
```

The lifecycle mode creates uniquely named disposable Docker volumes and covers:

- fresh-home startup and successful `/livez`/`/readyz`;
- exact-empty legacy credential-directory cleanup;
- starter-backed project bootstrap without a network credential;
- direct-loopback capability rejection and allowed authenticated proxy access;
- direct denial of contents, kernel, session, terminal, Lab, and tree routes;
- exact same-UID/pidfd preStop targeting, bounded SIGTERM, a newly published
  shutdown checkpoint, independent primary/checkpoint SQLite quick checks, and
  idempotent `not-running` success while Jupyter remains alive;
- retained workspace Git state; and
- generic diagnostic `503` (`CW-JH-STARTUP-001`) rather than proxy `504` for
  nonempty, linked, and specially typed forbidden stale state.

The Docker harness intentionally fails when its host cannot create the required
unprivileged namespaces. A passing Docker run is still not production evidence.
Repeat the release gates in the preview Hub using the exact ECR digest, real pod
security context/kernel, retained EFS storage, LiteLLM pre-spawn key, preStop and
120-second grace, culler, network rules, alerts, and backup/restore procedure.

The companion Hub profile must execute the image helper directly:

```yaml
singleuser:
  extraPodConfig:
    terminationGracePeriodSeconds: 120
  lifecycleHooks:
    preStop:
      exec:
        command:
          - /usr/local/sbin/codingworkspace-prestop
```

Do not replace it with a drain-only signal or a SIGTERM sent only to Jupyter.
Simpervisor forwards parent SIGTERM to the child and then immediately exits
without awaiting CodingWorkspace's 90-second shutdown. The helper instead
selects the exact same-UID child with immutable process/environment evidence,
uses a pidfd to close PID-reuse races, waits up to 105 seconds, detects a
nonzero-exit supervisor restart, and bounds the complete hook—including both
SQLite quick checks—to 114 seconds. No exact process is an idempotent
`not-running` success; a present but invalid or ambiguous match fails closed.
After signalling, success requires a new shutdown checkpoint and both SQLite
quick checks. Its failure is a release-blocking `CW_ALERT`; prove the hook's
`/proc`/pidfd access and timing in the real pod.

The LiteLLM mint hook should inject the key's actual
`CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH`. If the value is unavailable,
the image deliberately passes `0` so the UI reports only process-observed lower-
bound age. Restarting Jupyter does not reset the claimed credential age.

## Normal release and promotion

1. Land the CodingWorkspace changes on `main`; keep its `release` branch on the
   last compatible rollback until the image PR is merged and reviewed.
2. Merge the image PR. Confirm non-secret validation and the trusted immutable
   candidate build pass. Confirm `preview` and CodingWorkspace `latest` did not
   move.
3. Run the namespace/lifecycle tests and resolve every scan finding or record a
   reviewed, expiring exception.
4. Advance CodingWorkspace `release` to the approved source commit. Within 15
   minutes `track-cw.yml` updates `CW_REF` and dispatches the one promotion
   build. A manual tracker run avoids the wait.
5. Confirm the tracker and dispatched build are green; compare the release
   artifact's exact full refs and digest to the intended commits.
6. Stop/start a preview test server and complete the actual-Hub acceptance
   gates. Running pods are never hot-swapped.
7. Promote to production only by a reviewed `jhub-config` change pinning the
   exact accepted digest.

Run the tracker immediately:

```bash
gh workflow run track-cw.yml --repo ubc/jupyter-images --ref main
```

Build an immutable CodingWorkspace candidate without moving tags:

```bash
gh workflow run build.yml --repo ubc/jupyter-images --ref main \
  -f publish=true \
  -f scope=codingworkspace-notebook \
  -f promote_codingworkspace=false
```

Manual promotion is intentionally possible only as an explicit trusted
dispatch of `main`; normally use the tracker so `CW_REF` is first reconciled to
the release branch. Before any manual `promote_codingworkspace=true`, verify the
full `CW_REF` equals the intended CodingWorkspace `release` head and the pinned
GizmoApp commit is the reviewed starter.

## Verification

```bash
gh run list --repo ubc/jupyter-images --workflow track-cw.yml --limit 3
gh run list --repo ubc/jupyter-images --workflow build.yml --branch main --limit 5
aws ecr describe-images \
  --repository-name codingworkspace-notebook \
  --region ca-central-1 \
  --query 'sort_by(imageDetails,&imagePushedAt)[-5:].{tags:imageTags,digest:imageDigest,pushed:imagePushedAt}'
```

Expected promotion evidence:

- the tracker resolved a full release SHA and updated or confirmed `CW_REF`;
- the dispatched workflow says promotion was explicitly enabled;
- contract/SBOM/Trivy steps passed;
- `preview` and the immutable tag resolve to the recorded digest; and
- the full GizmoApp pin in the artifact matches `GIZMOAPP_REF`.

## Rollback

Prefer reverting CodingWorkspace `release`; the tracker builds and promotes the
reverted source through the same evidence-producing path. For an urgent preview
rollback, an ECR-authorized operator may move `preview` to a previously accepted
immutable digest, then pause the tracker or revert `release` so the next cycle
does not move it forward again. Never rebuild an old tag or use an unrecorded
`.dirty` local image.

Production rollback is a reviewed `jhub-config` change back to a previously
accepted immutable digest. A pod Stop/Start is required to receive a changed
image; deleting a retained home/PVC is not a restart and is never part of this
runbook.

## Failure modes

| Symptom | Meaning / action |
| --- | --- |
| Fork PR asks for AWS or fails because a secret is absent | Workflow regression: PR validation must not enter the trusted publish job |
| Static validation rejects an Action | Resolve the desired upstream release and review/pin its full commit; do not switch to a floating tag |
| Tracker cannot clone CodingWorkspace | Check the read-only deploy key, the pinned GitHub host key, and repository access; never weaken strict host checking |
| Tracker push loses a race | No force/rebase is used; the next scheduled run retries from fresh `main` |
| Image-source merge succeeds but preview does not change | Expected; ordinary merges publish immutable candidates only |
| Tracker unchanged on schedule and no build runs | Expected; unchanged scheduled runs do not rebuild. A manual tracker run explicitly rebuilds/promotes |
| Immutable build succeeds but no moving CodingWorkspace tag changes | Expected unless the trusted dispatch set `promote_codingworkspace=true` |
| SBOM/Trivy step cannot generate evidence | Publication stops; repair scanner/network/tooling rather than publishing without evidence |
| Trivy report contains findings but workflow is green | Generation succeeded; human triage is still required before promotion |
| Lifecycle smoke fails only at Bubblewrap | The test host/pod cannot provide the required namespace boundary; production remains blocked until the real image/profile probe passes |
| Startup returns diagnostic 503 | Inspect the credential-safe `CW_ALERT`/reference; repair config or quarantine forbidden stale state. Do not enable the forbidden feature or delete ambiguous data automatically |
| Students see old behavior | Their server predates the image. Use Hub Control Panel Stop/Start; do not delete the PVC |

## Maintenance cadence

At least before each course release and monthly while deployed:

1. review the base digest and Jupyter component assertions;
2. review OpenCode/Node/Bubblewrap and every Action/scanner pin;
3. regenerate and triage the SBOM/vulnerability report;
4. run contract, namespace, lifecycle, and preview-Hub acceptance tests;
5. verify a previous immutable digest can be restored; and
6. retain the exact release evidence with the course operations record.
