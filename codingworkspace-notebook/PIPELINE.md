# codingworkspace-notebook CI/CD pipeline

Audience: LT Hub/AppCloud operators and course release maintainers. This
runbook describes the trust boundary, source pins, artifacts, promotion, and
rollback. The CodingWorkspace repository's `RELEASING.md` remains the
developer-facing release guide.

## Trust-separated flow

```text
fork or same-repo PR
  └─ select changed images: no secrets, no AWS, no image publication
       └─ CodingWorkspace/workflow paths only: run CW static validation

reviewed jupyter-images main push touching CodingWorkspace
  └─ validate → build/push immutable candidate → pull exact digest
                                                  └─ image smoke + SBOM/vulnerability scan
                                                     (CodingWorkspace preview/latest stay put)

reviewed jupyter-images main workflow_dispatch with an optional exact CW SHA
  └─ validate full lowercase commit in private clone → build/push/scan candidate
       (CW_REF is unchanged; promotion is categorically refused)

ordinary-image branch/tag push
  └─ existing short-SHA build/push → move that image's latest
     (no CodingWorkspace lint, source key, SBOM, or Trivy policy)

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

OpenCode has a separate automated source-input path. Every six hours the
reviewed default-branch `update-opencode.yml` definition reads the official
GitHub release API and chooses the newest non-draft, non-prerelease version
that has been public for at least 48 hours. It requires GitHub-published
SHA-256 digests for the amd64 baseline and arm64 archives, recomputes both
digests, rejects unsafe archive members, and runs the CLI contracts on amd64.
It changes only the three OpenCode values in `RUNTIME_PINS.env`, opens a
same-repository PR, dispatches non-secret validation for that exact branch,
merges that exact head subject to branch protection, explicitly dispatches the
protected-`main` publication, and waits for it to finish.

After that automation PR reaches `main`, the hardened job still builds the
exact image, runs the full image contract, produces an SBOM and all-severity
vulnerability report, and enforces the fixable-CRITICAL gate. Only then may
that narrowly identified automation commit move `latest` and `preview`.
If the protected build fails after merge, the updater validates and merges an
exact revert of that pin commit automatically. Promotion records both previous
tag digests before mutation and restores them if either tag move or readback
fails.
Production remains an immutable digest in `jhub-config`; never point it at a
moving tag.

The tracker's `GITHUB_TOKEN` push does not trigger another push workflow, so a
release movement results in the one explicitly dispatched image build, not a
push build plus a second dispatch build. If GitHub changes that recursion
behavior or the tracker is changed to use a PAT/App token, preserve an explicit
duplicate-build guard.

An image-source PR must leave `CW_REF` at the current CodingWorkspace `release`
head. Its merge may produce an immutable candidate combining the new image
source with that released CodingWorkspace revision, but cannot alter either
moving CodingWorkspace tag. After the image source lands, advancing
CodingWorkspace `release` is the action that makes the tracker update `CW_REF`
and request a promotion build. Do not pin unreleased application code in an
image PR or manually dispatch promotion merely to test one: the pin has not
passed the application release gate, and the next tracker run will reconcile
it back to the actual `release` head. Instead, use the exact-SHA candidate
dispatch described below. It tests a committed CodingWorkspace revision without
changing `CW_REF`, and it has no authority to move `preview` or `latest`.

## Workflow policy

`build.yml` has four separated paths:

1. **Non-secret selection.** Runs for every PR, branch/tag push, and dispatch
   with only `contents: read`. It determines the changed image directories and
   whether CodingWorkspace policy files changed. A root-level shared build
   input selects all images; docs/workflow-only changes do not silently publish
   an image. An explicit dispatch can select changed images, all images, or only
   `codingworkspace-notebook`.
2. **Path-selected CodingWorkspace validation.** Runs only when the
   CodingWorkspace image, a shared input, or its workflow policy changes. It
   checks source-pin format, workflow/YAML/Python/shell syntax, the
   source/promotion trust boundary, immutable Action pins, GitHub's pinned SSH
   host key, and expected image/config hardening. It is a peer job, not a
   dependency of unrelated image publication. Fork PR code never receives AWS
   OIDC permission or `CW_DEPLOY_KEY`.
3. **Ordinary-image publication.** Preserves the repository's existing
   branch/tag short-SHA build and `latest` movement for the six unrelated
   images. It deliberately does not inherit CodingWorkspace lint, its protected
   environment, source credential, SBOM, or Trivy release policy. Manual
   publication still requires `publish=true`.
4. **Hardened CodingWorkspace build/publish/scan/promote.** Runs only for a
   CodingWorkspace selection on a push to `main`, or a `workflow_dispatch` of
   `main` with `publish=true`. It resolves exact sources, publishes one
   immutable ECR image with BuildKit provenance/SBOM attestations, resolves and
   pulls that exact ECR digest, and runs the CodingWorkspace smoke, Syft, a
   complete Trivy report, and the automatic fixable-CRITICAL Trivy gate against
   the pulled digest. A rejected immutable candidate may remain in ECR for
   diagnosis, but it is never promoted.

The hardened job also accepts an optional `codingworkspace_candidate_sha` only
on a trusted `workflow_dispatch` of reviewed `main`. The value must be exactly
40 lowercase hexadecimal characters and must resolve to that exact commit in
the credentialed private clone. The workflow retains the tracker-owned
`CW_REF`, marks the build as an override, and fails before publication if the
same request asks for `promote_codingworkspace=true`. The promotion step has a
second independent condition that excludes every nonempty candidate input.

For `codingworkspace-notebook`, both `latest` and `preview` require reviewed
`main`, all image gates, and a trusted `workflow_dispatch` with `publish=true`
and `promote_codingworkspace=true`. The OpenCode updater first waits for an
exact-commit branch validation, merges that commit, then explicitly dispatches
and waits for the protected-`main` publication. This explicit dispatch is
required because a merge performed with `GITHUB_TOKEN` does not recursively
start a push workflow.

`ci/validate_ci_policy.py` regression-tests these conditions and the tracker
dispatch. Branch protection on `main` and required validation remain an
administrator setting outside this repository.

Both CodingWorkspace credential-bearing jobs name the
`codingworkspace-publication` GitHub environment. Configure that environment to
allow deployments only from `main`, move `CW_DEPLOY_KEY` into it, and delete
every repository-level copy. The AWS role trust policy must independently
require the exact OIDC subject
`repo:ubc/jupyter-images:environment:codingworkspace-publication` and intended
audience. GitHub environment jobs use the environment rather than the ref in
`sub`; the environment's deployment-branch rule is therefore what binds the
role to main. These are release prerequisites: a contributor can edit an `if`
condition in branch YAML.

## Immutable source resolution

| Input | Resolution and verification |
| --- | --- |
| jupyter-images | The checked-out full `GITHUB_SHA` on reviewed `main` |
| CodingWorkspace | Normally the tracker-owned lowercase 40-character SHA in `CW_REF`, which on `jupyter-images` main equals the CodingWorkspace `release` head. An explicit main-only manual candidate may instead select a different full lowercase SHA without editing `CW_REF`; it is non-promoting. In both cases the private clone uses `CW_DEPLOY_KEY`, the selected object must be that exact SHA-1 commit, and detached checkout must equal it. |
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
`<ji7>-r<run-id>-a<attempt>`. An exact-SHA override uses
`<ji7>-cw<cw40>-gz<gizmo7>-r<run-id>-a<attempt>`, preserving the full requested
commit in its tag. A rerun cannot overwrite an earlier candidate.
Tags are still pointers, not sufficient release evidence. The full GizmoApp and
CodingWorkspace commits, jupyter-images commit, tested ECR digest, scanner
versions, and workflow run are stored in the 90-day workflow artifact and image
labels. The artifact separately records the tracker pin, effective source,
candidate SHA, and candidate-override flag. Ninety days is only a transfer
window. Production promotion requires
verifying `SHA256SUMS` and copying the complete bundle—including the exact
`published-image.txt` digest—into the course's independently backed-up,
indefinite release record. Record that destination in the production change.

## Credentials and permissions

| Credential/capability | Scope | Used where |
| --- | --- | --- |
| `CW_DEPLOY_KEY` | Read-only deploy key for `kevinlb1/CodingWorkspace` | `codingworkspace-publication` environment secret only; delete any repository-level copy |
| AWS GitHub OIDC role `github` | ECR repository/image publication | Trusted build job only (`id-token: write`); trust exact `repo:ubc/jupyter-images:environment:codingworkspace-publication` subject, with the environment restricted to main |
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
  unfixed;
- a second Trivy pass blocks any fixable CRITICAL finding and retains its
  filtered JSON result; and
- the pushed BuildKit result includes maximum provenance plus an SBOM
  attestation.

The workflow artifact also records the exact source revisions, tested ECR
tag/digest, workflow run, whether CodingWorkspace promotion was requested,
`published-image.txt`, and checksums for every evidence file. Scanner-generation,
smoke, or fixable-CRITICAL failure blocks moving-tag promotion, though the
immutable candidate already pushed may remain for diagnosis. A release reviewer
must still triage noncritical and unfixed findings and record accepted exceptions
with an owner and expiry; the automatic threshold is a floor, not a declaration
that the full report is safe.

The Actions artifact expires after 90 days and is not the course record. Before
the accepted digest can enter the production Hub configuration, verify
`SHA256SUMS`, copy the exact evidence bundle into independently backed-up
indefinite storage, and record that storage location in the `jhub-config`
change. The destination/service is an operator configuration item outside this
repository; absence of a destination blocks production rather than weakening
the gate.

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
- adversarial retained Python user-site content that must never shadow the
  trusted control package;
- starter-backed project bootstrap without a network credential;
- direct-loopback capability rejection and allowed authenticated proxy access;
- direct denial of contents, kernel, session, terminal, Lab, and tree routes;
- exact same-UID/pidfd preStop targeting, bounded SIGTERM, a newly published
  shutdown checkpoint with a mandatory full SQLite quick check, bounded
  best-effort primary-database telemetry, and idempotent `not-running` success
  while Jupyter remains alive;
- retained workspace Git state; and
- generic diagnostic `503` (`CW-JH-STARTUP-001`) rather than proxy `504` for
  nonempty, linked, and specially typed forbidden stale state.

The Docker harness intentionally fails when its host cannot create the required
unprivileged namespaces. A passing Docker run is still not production evidence.
Repeat the release gates in the preview Hub using the exact ECR digest, real pod
security context/kernel, retained EFS storage, LiteLLM pre-spawn key, preStop and
120-second grace, culler, network rules, alerts, and backup/restore procedure.

The companion Hub profile must execute the image helper directly. Merge these
entries into the **existing CodingWorkspace profile** rather than treating this
fragment as a complete profile definition:

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

`kubespawner_override.lifecycle_hooks` replaces, rather than merges with,
top-level `singleuser.lifecycleHooks`. Preserve the CodingWorkspace profile's
existing `postStart` mapping as a sibling of `preStop`; setting the top-level
hook alone silently leaves the profile's override in effect and never runs this
helper. Likewise, merge `terminationGracePeriodSeconds` into the profile's
existing `extra_pod_config` rather than discarding its other pod settings.

`terminationGracePeriodSeconds` and
`CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS` are one deployment
contract and must be changed together. Kubernetes does not expose the actual
pod grace period to the child process; the environment value is therefore the
runtime's trusted mirror for deriving its bounded hook budget. Hub-config CI
must compare both configured values, and preview-Hub acceptance must verify the
rendered pod field and container environment agree before release.

Do not replace it with a drain-only signal or a SIGTERM sent only to Jupyter.
Simpervisor forwards parent SIGTERM to the child and then immediately exits
without awaiting CodingWorkspace's 90-second shutdown. The helper instead
selects the exact same-UID child with immutable process/environment evidence,
uses a pidfd to close PID-reuse races, derives the child timeout and complete
hook deadline from the required termination-grace environment value, and
detects a nonzero-exit supervisor restart. No exact process is an idempotent
`not-running` success; a present but invalid or ambiguous match fails closed.
At the configured 120 seconds, the derived budgets retain the 90-second child
timeout, replacement-quiet interval, at least 15 seconds for a mandatory full
quick check of the newly published shutdown checkpoint, and six seconds after
the hook for kubelet termination. The closed primary database is redundant once
that recovery checkpoint is verified, so its separate telemetry check uses at
most five seconds and may warn or skip for budget without failing the hook.
Success requires the new checkpoint and its full check, not a successful
primary check. A mandatory-contract failure is a release-blocking `CW_ALERT`;
prove the hook's `/proc`/pidfd access and timing in the real pod.

The LiteLLM mint hook should inject the key's actual
`CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH`. If the value is unavailable,
the image deliberately passes `0` so the UI reports only process-observed lower-
bound age. Restarting Jupyter does not reset the claimed credential age.

## Normal release and promotion

1. Land the CodingWorkspace changes on `main`; keep its `release` branch at the
   current accepted revision. Do not change `CW_REF` in the image PR.
2. Merge the image PR. Confirm non-secret validation and any trusted immutable
   candidate build pass. That candidate uses the current `release` pin; confirm
   `preview` and CodingWorkspace `latest` did not move.
3. Advance CodingWorkspace `release` to the approved source commit. Within 15
   minutes `track-cw.yml` updates `CW_REF` and dispatches the one promotion
   build. A manual tracker run avoids the wait.
4. Confirm the tracker and dispatched build are green. Run the namespace and
   lifecycle tests against the resulting exact digest. The automated gate must
   show no fixable CRITICAL finding; resolve other findings or record a
   reviewed, expiring exception.
5. Compare the release artifact's exact full refs and digest to the intended
   commits.
6. Stop/start a preview test server and complete the actual-Hub acceptance
   gates. Running pods are never hot-swapped.
7. Verify `SHA256SUMS` and copy the exact evidence bundle into the independent,
   indefinite course release record. Record its location in the change.
8. Promote to production only by a reviewed `jhub-config` change pinning the
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

To test one committed CodingWorkspace revision before advancing its `release`
branch, add its exact full lowercase SHA. This must still dispatch the reviewed
`jupyter-images` `main` workflow and select only the CodingWorkspace image:

```bash
gh workflow run build.yml --repo ubc/jupyter-images --ref main \
  -f publish=true \
  -f scope=codingworkspace-notebook \
  -f promote_codingworkspace=false \
  -f codingworkspace_candidate_sha=0123456789abcdef0123456789abcdef01234567
```

Replace the example with the intended commit. The run fails if the SHA is
malformed, absent from the private clone, not itself a commit, or combined with
promotion. It does not edit `CW_REF`; review the immutable digest and evidence,
then advance CodingWorkspace `release` through the normal tracker path if the
candidate is accepted.

Manual promotion is intentionally possible only as an explicit trusted
dispatch of `main`; normally use the tracker so `CW_REF` is first reconciled to
the release branch. Before any manual `promote_codingworkspace=true`, verify the
full `CW_REF` equals the intended CodingWorkspace `release` head and the pinned
GizmoApp commit is the reviewed starter.

## Automated OpenCode release

Normally no operator action is required. The scheduled workflow opens the PR,
waits for exact-head validation, merges through branch protection, then starts
and waits for the hardened `main` build. A failed digest, archive, CLI, image
contract, SBOM, or critical vulnerability gate leaves the old preview digest
untouched and automatically reverts the rejected pin on `main`. A partial tag
promotion restores both prior tag digests. The previous immutable digest is
never deleted by this workflow.

Run discovery immediately:

```bash
gh workflow run update-opencode.yml --repo ubc/jupyter-images --ref main
```

If repository policy requires a human approval, that remains the only routine
human step. Removing that requirement for this narrowly scoped bot PR is a
repository-administrator policy choice; never merge around a failed gate.

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
- `SHA256SUMS` validates the all-severity report, gate report, SBOM, release
  metadata, and `published-image.txt`;
- `preview` and the immutable tag resolve to the recorded digest; and
- the full GizmoApp pin in the artifact matches `GIZMOAPP_REF`.

## Rollback

Prefer reverting CodingWorkspace `release`; the tracker builds and promotes the
reverted source through the same evidence-producing path. For an urgent preview
rollback, an ECR-authorized operator may move `preview` to a previously accepted
immutable digest, then pause the tracker or revert `release` so the next cycle
does not move it forward again. Never rebuild an old tag or use an image without
checksummed release evidence.

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
| Exact-SHA candidate is rejected before build | Supply one lowercase 40-character commit available in the private clone, dispatch reviewed `main`, and keep `promote_codingworkspace=false`; never change `CW_REF` merely to test it |
| Tracker push loses a race | No force/rebase is used; the next scheduled run retries from fresh `main` |
| OpenCode update PR is not merged | Inspect its dispatched validation and branch-protection requirements; the next schedule revalidates and retries the exact open PR head |
| No eligible OpenCode update is proposed | Expected while newer stable releases are inside the 48-hour soak, lack both required published digests/assets, or are not newer than the pin |
| OpenCode automation build fails | Preview remains on the prior digest. Fix or quarantine the release; never move the tag forward around a failed gate |
| CodingWorkspace image-source merge succeeds but preview does not change | Expected; it may publish an immutable candidate but cannot move CodingWorkspace tags |
| Tracker unchanged on schedule and no build runs | Expected; unchanged scheduled runs do not rebuild. A manual tracker run explicitly rebuilds/promotes |
| Immutable build succeeds but no moving CodingWorkspace tag changes | Expected unless the trusted dispatch set `promote_codingworkspace=true` |
| SBOM/Trivy step cannot generate evidence | Publication stops; repair scanner/network/tooling rather than publishing without evidence |
| Fixable CRITICAL Trivy gate fails | Candidate remains unpromoted. Patch the image or document a deliberately reviewed policy change; do not disable the complete report |
| Trivy report contains noncritical or unfixed findings but workflow is green | The automatic floor passed; human triage is still required before production |
| Evidence has not reached the independent release record | Stop production promotion. Verify `SHA256SUMS`, transfer the exact bundle, and record its indefinite-storage location; the 90-day artifact is only a handoff window |
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
6. retain the checksummed release evidence in the independently backed-up,
   indefinite course operations record.
