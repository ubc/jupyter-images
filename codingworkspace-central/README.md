# Central images: staging promotion and packaging review

The course builds and publishes the central application image. Its native Hub
verifier now ships in the application wheel; deployment does not wait for LTIC
to choose a signer or verifier package, or for the course to package an adapter.
LTIC deploys by admitting that published image through
[Promote CodingWorkspace central image](../.github/workflows/promote-cw-central.yml).
The separate review-build workflow below is for packaging inspection only.

## Current staging deployment path

1. Select the exact course-published digest and its receipt from the private
   [course staging handoff](https://github.com/kevinlb1/CodingWorkspace/blob/main/deploy/ltic-media-activation/STAGING_IMAGE.md).
   Use the full commit holding that receipt as the promotion workflow's
   `receipt_ref`; do not substitute a moving tag or a review-build receipt.
2. Run the promotion workflow's admission checks. It verifies the receipt,
   source revision, runtime identity and attestation manifests, rejects the
   review-image label, and applies LTIC's vulnerability policy. Publication
   copies the existing image index and preserves its digest and attestations;
   it does not rebuild the application. Keep the destination package private
   and leave `allow_package_creation=false`.
3. Pin the admitted digest in LTIC's staging workloads and migration Jobs.
   Supply the agreed runtime identity, database and secret configuration through
   LTIC's deployment mechanisms. The course and LTIC then complete the live
   Hub, media, database-role, isolation and recovery checks before student
   enablement. A registry admission receipt is not an activation receipt.

The private staging handoff owns the selected image, configuration and remaining
integration gates. Neither this README nor the review workflow changes student
media flags or Hub profiles.

## Separate packaging review build

[Build CodingWorkspace central media review image](../.github/workflows/build-cw-central.yml)
builds an exact source commit, verifies the installed package file for file,
smokes under UID 10001 with a read-only filesystem and no network, and scans the
exact image. It deliberately leaves production verifier settings unconfigured;
its smoke confirms that the verifier loaders refuse that missing configuration.
Its image label and receipt retain `blocked-pending-reviewed-verifier` to mark
this non-deployable artifact. That marker does not describe the current
course-published staging image or a missing LTIC implementation.

Do not deploy or promote `Dockerfile.review` output, even when its selected
source includes the native verifier. The promotion gate rejects the review
label. Use the course-published image and receipt for staging; review smoke
does not replace migration or real-cluster readiness tests.

## Optional review-build setup

The following procedure configures the optional review build. Promotion uses
the same protected environment, with its own workflow's credentials and checks;
it does not require a review build or the optional ECR setup below.

- Ensure environment `codingworkspace-central-publication` exists,
  restrict it to `main`, require an independent reviewer, prevent self-review,
  and disable administrator bypass. The reviewer checks the requested full
  CodingWorkspace SHA and the dependency/base pins before approving each run.
- Set its `CODINGWORKSPACE_CENTRAL_POLICY_ACK` to
  `main-only-independent-review-no-admin-bypass-v1` only after those protections
  are installed. The acknowledgement is not a substitute for the settings.
- Put the existing read-only CodingWorkspace `CW_DEPLOY_KEY` in that environment.
  A `publish=false` build needs no AWS role or new ECR repository. It builds,
  tests, scans and returns review evidence without uploading private source,
  wheel bytes or an image archive.
- For optional `publish=true`, create ECR repository `codingworkspace-central`
  and role `github-codingworkspace-central-publication`. Its OIDC subject must
  be `repo:ubc/jupyter-images:environment:codingworkspace-central-publication`
  and audience `sts.amazonaws.com`. Give `ecr:GetAuthorizationToken` on `*`,
  and only `BatchCheckLayerAvailability`, `BatchGetImage`,
  `GetDownloadUrlForLayer`, `InitiateLayerUpload`, `UploadLayerPart`,
  `CompleteLayerUpload`, and `PutImage` on this repository. No create/delete,
  discovery, notebook-repository or Hub permissions are needed. Set
  `AWS_ACCOUNT_ID` as an environment secret and `AWS_REGION` as a variable.

From the workflow's **main** definition, dispatch **Build CodingWorkspace
central media review image** with a full `codingworkspace_sha` reachable from
CodingWorkspace `main`. `publish` defaults to false. Forks/PR events run only
the credential-free tests. Manual runs from forks or non-main branches cannot
enter the private-source build. The workflow does not touch `CW_REF`, the
student release tracker, or the existing notebook publication environment.

## Source and dependency evidence

`runtime-lock.json` pins the official Python 3.12 slim image by registry digest
and every public wheel by filename, URL, version and SHA-256. The downloader
accepts only exact `files.pythonhosted.org` HTTPS files and refuses redirects.
Build and runtime package installations use `--network=none`, `--no-index` and
the verified wheel set. The builder uses separate locked setuptools tooling;
the final image receives only the application/Postgres venv, not the source
context, build tools, Git, OpenCode, Jupyter or credentials.

Source acquisition reuses the notebook pipeline's reviewed known-hosts file
and exact-main ancestry validator. A temporary deploy key is removed before
packaging. A clean `git archive` exports only the package and its build
metadata, avoiding the BuildKit `.git` transport issue without sending Git
history/configuration to the builder. Tracked build output, bytecode, symlinks
and dirty source are rejected. Installed package contents must match the
source receipt, catching the D12 stale `build/lib` failure.

Publication uses a run/attempt-unique `review-<CW SHA>-r<RUN>-a<ATTEMPT>` tag,
BuildKit provenance/SBOM, and the Buildx-reported digest. A pull by that exact
digest precedes smoke and scanning; a failed candidate may remain under its
unique tag but produces no passing review receipt. The retained evidence has
the source/image-repository commits, dependency lock, digest (when published),
runtime smoke, SBOM, all-severity report, fixable-CRITICAL policy result, and
checksums. It contains neither the private source/wheels nor the AWS account.

Evidence artifacts are retained for 90 days. Before relying on a receipt in a
longer-lived gate ledger, its owner must archive the evidence and checksums in
the course/LTIC evidence store; an Actions link alone is not permanent storage.
Build-only runs produce scan evidence (including the scanner's SBOM), but do
not publish BuildKit provenance or an OCI SBOM attestation. Only the publication
path provides those attestations; a local image receipt is not a published digest.

The first build-only review retains the pinned official Docker Hub base so it
needs no AWS setup. An LTIC mirror is a reasonable availability improvement,
independent of where the final service runs, once its exact repository and
digest are supplied. Adopt it through a reviewed lock/validator change that
checks content equivalence and runs the same image smoke. Do not silently
substitute a mutable mirror tag or relax the registry allowlist. If Docker Hub
rate-limits the review build, record that failure and retry the pinned build.

## Local validation

```bash
python3 -m unittest discover -s codingworkspace-central -p 'test_*.py' -v
```

For an authorized clean CodingWorkspace checkout at the selected commit:

```bash
python3 codingworkspace-central/prepare_context.py /path/to/CodingWorkspace FULL_SHA /tmp/central-inputs
base=$(python3 -c 'import json; print(json.load(open("codingworkspace-central/runtime-lock.json"))["baseImage"])')
docker buildx build --load --platform linux/amd64 \
  --build-arg "CENTRAL_PYTHON_BASE=$base" --build-arg CW_REF=FULL_SHA \
  --build-context inputs=/tmp/central-inputs \
  -f codingworkspace-central/Dockerfile.review -t local/codingworkspace-central:review codingworkspace-central
docker run --rm -i --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=32m \
  --entrypoint /opt/codingworkspace/bin/python local/codingworkspace-central:review - FULL_SHA \
  < codingworkspace-central/smoke.py
```

The actual Docker image build, image scans and service activation are distinct
checks. Passing the local unit suite does not claim any of those ran.
