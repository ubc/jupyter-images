# Central media image: a concrete first build for issue #26

The course-control and typed-media services already exist in CodingWorkspace.
This dedicated workflow makes their first image review possible before LTIC
has selected its token-verifier package. It builds the real course source,
Python/Postgres runtime, and console entrypoints; it does not substitute a
mock API or invent an issuer. No student media flag or Hub profile is changed.

## Two acceptance stages

1. **This PR: image review.** Build an exact source commit, verify the installed
   package file for file, smoke under UID 10001 with a read-only filesystem and
   no network, and scan the exact image. The image has no verifier; both
   production verifier loaders must refuse authentication. Its label and
   receipt explicitly say `blocked-pending-reviewed-verifier`. There is no
   moving tag, deployment, or student-activation receipt.
2. **After LTIC names the issuer interface: authenticated activation.** Course
   staff implement/package the adapter. Use CodingWorkspace's existing
   `deploy/kubernetes/central-service-image/` production recipe and its complete
   verifier-inclusive lock, then publish and retest that different digest.
   LTIC supplies verifier material only at runtime, installs the services and
   routes, and supplies paired preview identities. The course runs the real
   six-model Newcastle smoke and the identity/rotation, Postgres, isolation,
   retention and recovery gates before requesting student enablement.

A review image cannot be passed off as the second stage. The production
recipe's required verifier wheel and all feature defaults are unchanged.
Its migration/real-cluster readiness tests are not replaced by this image smoke.

## What LTIC needs to configure for the first build

- Merge this PR, then create environment `codingworkspace-central-publication`,
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
