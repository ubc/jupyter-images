#!/usr/bin/env python3
"""Regression checks for the release/promotion trust boundary."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
TRACK = (ROOT / ".github/workflows/track-cw.yml").read_text(encoding="utf-8")
UPDATE_OPENCODE = (ROOT / ".github/workflows/update-opencode.yml").read_text(
    encoding="utf-8"
)
LOCAL_PUBLISH = (ROOT / "codingworkspace-notebook/build-and-push.sh").read_text(
    encoding="utf-8"
)
LOCAL_SCAN = (ROOT / "codingworkspace-notebook/ci/scan-local-image.sh").read_text(
    encoding="utf-8"
)

EXPECTED_ACTIONS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
    "anchore/sbom-action": "e22c389904149dbc22b58101806040fa8d37a610",
    "aquasecurity/trivy-action": "57a97c7e7821a5776cebc9bb87c984fa69cba8f1",
    "aws-actions/amazon-ecr-login": "03f1aad4c6c7ffd436567f42f9384779290529bd",
    "aws-actions/configure-aws-credentials": "7474bc4690e29a8392af63c5b98e7449536d5c3a",
    "docker/setup-buildx-action": "8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
}


def step(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(name)}\n(.*?)(?=^      - name: |\Z)",
        text,
    )
    if not match:
        raise SystemExit(f"workflow step is missing: {name}")
    return match.group(1)


def job(text: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-zA-Z0-9_-]+:\n|\Z)",
        text,
    )
    if not match:
        raise SystemExit(f"workflow job is missing: {name}")
    return match.group(1)


for path in (ROOT / ".github/workflows").glob("*.yml"):
    text = path.read_text(encoding="utf-8")
    if "pull_request_target" in text:
        raise SystemExit(f"pull_request_target is forbidden in {path}")
    for owner_repo, sha in re.findall(r"uses:\s*([^@\s]+)@([0-9a-f]{40})", text):
        expected = EXPECTED_ACTIONS.get(owner_repo)
        if expected is None:
            raise SystemExit(f"unreviewed external Action in {path}: {owner_repo}@{sha}")
        if sha != expected:
            raise SystemExit(f"unexpected pin for {owner_repo}: {sha}")

selection_job = job(BUILD, "select-images")
validation_job = job(BUILD, "validate-codingworkspace")
ordinary_job = job(BUILD, "build-and-push-ordinary")
publish_job_text = job(BUILD, "build-scan-publish")

for required in (
    "github.event.pull_request.base.sha",
    "--format github-output",
    "ordinary_images",
    "codingworkspace_images",
    "validate_codingworkspace",
):
    if required not in selection_job:
        raise SystemExit(f"image selection is missing {required}")

if "needs: select-images" not in validation_job or (
    "needs.select-images.outputs.validate_codingworkspace == 'true'"
    not in validation_job
):
    raise SystemExit("CodingWorkspace validation is not selected by changed paths")

# Ordinary images retain the upstream branch/tag + short-SHA/latest contract.
# They must not inherit CW's lint, evidence, scanning, or protected environment.
for required in (
    "needs: select-images",
    "needs.select-images.outputs.ordinary_images",
    "github.repository == 'ubc/jupyter-images'",
    "github.event_name == 'push'",
    "github.event_name == 'workflow_dispatch'",
    "inputs.publish == true",
    "docker buildx build --load",
    'tag="${GITHUB_SHA::7}"',
    'docker push "$repository:latest"',
):
    if required not in ordinary_job:
        raise SystemExit(f"ordinary image publication is missing {required}")
for forbidden in (
    "validate-codingworkspace",
    "codingworkspace-publication",
    "CW_DEPLOY_KEY",
    "trivy-action",
    "sbom-action",
):
    if forbidden in ordinary_job:
        raise SystemExit(f"ordinary image publication unexpectedly contains {forbidden}")
if not re.search(r'(?m)^    branches: \["\*"\]\s*$', BUILD) or not re.search(
    r'(?m)^    tags: \["\*"\]\s*$', BUILD
):
    raise SystemExit("ordinary image branch/tag push triggers were not preserved")

publish_gate = re.search(r"(?ms)^  build-scan-publish:.*?^    runs-on:", BUILD)
if not publish_gate:
    raise SystemExit("publish job gate is missing")
gate = publish_gate.group(0)
for required in (
    "github.repository == 'ubc/jupyter-images'",
    "github.ref == 'refs/heads/main'",
    "github.event_name == 'push'",
    "github.event_name == 'workflow_dispatch'",
    "inputs.publish == true",
):
    if required not in gate:
        raise SystemExit(f"publish job gate is missing {required}")
if "environment: codingworkspace-publication" not in publish_job_text:
    raise SystemExit("publication is not bound to the protected publication environment")
for required in (
    "needs: [select-images, validate-codingworkspace]",
    "needs.select-images.outputs.codingworkspace_images",
    "fromJSON(needs.select-images.outputs.codingworkspace_images)",
):
    if required not in publish_job_text:
        raise SystemExit(f"hardened publication is not CW-only: missing {required}")

promotion = step(BUILD, "Promote approved CodingWorkspace release")
for required in (
    "matrix.image == 'codingworkspace-notebook'",
    "github.event_name == 'workflow_dispatch'",
    "inputs.promote_codingworkspace == true",
    "move_and_verify latest",
    "move_and_verify preview",
    "previous_latest",
    "previous_preview",
    "restore_previous_tags",
):
    if required not in promotion:
        raise SystemExit(f"CodingWorkspace promotion step is missing {required}")

dispatch = step(TRACK, "Build and promote the approved release")
for required in (
    "-f publish=true",
    "-f scope=codingworkspace-notebook",
    "-f promote_codingworkspace=true",
):
    if required not in dispatch:
        raise SystemExit(f"trusted tracker dispatch is missing {required}")

tracker_job = re.search(r"(?ms)^  bump:.*?^    runs-on:", TRACK)
if not tracker_job or any(
    required not in tracker_job.group(0)
    for required in (
        "github.repository == 'ubc/jupyter-images'",
        "github.ref == 'refs/heads/main'",
    )
):
    raise SystemExit("release tracker is not restricted to its reviewed main definition")
if "environment: codingworkspace-publication" not in TRACK:
    raise SystemExit("release tracker is not bound to the protected publication environment")
if not re.search(
    r"(?ms)^permissions: \{\}\s*$.*?^  bump:.*?^    permissions:\s*$"
    r".*?^      contents: write\s*$.*?^      actions: write\s*$",
    TRACK,
):
    raise SystemExit("tracker write permissions are not isolated to its main-only job")

update_job = job(UPDATE_OPENCODE, "propose")
for required in (
    "github.repository == 'ubc/jupyter-images'",
    "github.ref == 'refs/heads/main'",
    "contents: write",
    "pull-requests: write",
    "actions: write",
    "https://api.github.com/repos/anomalyco/opencode/releases?per_page=100",
    "--minimum-age-hours 48",
    "update_opencode_release.py verify",
    "validate-static.sh",
    "gh workflow run build.yml",
    "publish=false",
    "gh run watch",
    "gh pr merge",
    "--match-head-commit",
    "--ref main",
    "publish=true",
    "promote_codingworkspace=true",
    "mergeCommit",
    "publication_run",
    "gh run watch \"$publication_run\" --exit-status",
    "rollback_branch",
    "git revert --no-edit \"$merge_sha\"",
    "roll back rejected OpenCode",
    "gh run watch \"$rollback_run\" --exit-status",
):
    if required not in update_job:
        raise SystemExit(f"OpenCode update automation is missing {required}")
if not re.search(r"(?m)^permissions: \{\}\s*$", UPDATE_OPENCODE):
    raise SystemExit("OpenCode update workflow has broad top-level permissions")

ordered_steps = (
    "Build and publish immutable candidate with provenance and BuildKit SBOM",
    "Run CodingWorkspace image contract smoke",
    "Generate SPDX SBOM",
    "Generate vulnerability report",
    "Enforce fixable CRITICAL vulnerability policy",
    "Record release evidence",
    "Upload build, SBOM, and vulnerability evidence",
    "Promote approved CodingWorkspace release",
)
positions = [BUILD.find(f"      - name: {name}") for name in ordered_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("published-digest smoke/scan/promotion steps are missing or out of order")
if publish_job_text.count("docker buildx build") != 1:
    raise SystemExit("the trusted job must build/push exactly once so scans match publication")
for required in (
    'docker pull "$ECR_REPOSITORY@$digest"',
    'docker tag "$ECR_REPOSITORY@$digest" "$LOCAL_IMAGE"',
    "printf 'IMAGE_DIGEST=%s\\n' \"$digest\" >> \"$GITHUB_ENV\"",
):
    if required not in publish_job_text:
        raise SystemExit(f"published digest is not made authoritative for evidence: {required}")
for required in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "-gz${GIZMOAPP_REF:0:7}"):
    if required not in publish_job_text:
        raise SystemExit(f"candidate tags are not run-unique and source-identifying: {required}")

for tag in ("latest", "preview"):
    if f"previous_{tag}=$(digest_for_tag {tag})" not in promotion:
        raise SystemExit(f"CodingWorkspace promotion does not retain the {tag} digest")
    if f'move_and_verify {tag} "$IMAGE_DIGEST"' not in promotion:
        raise SystemExit(f"CodingWorkspace promotion does not verify the {tag} digest")
if promotion.find('move_and_verify latest "$IMAGE_DIGEST"') > promotion.find(
    'move_and_verify preview "$IMAGE_DIGEST"'
):
    raise SystemExit("CodingWorkspace preview can move before latest is verified")
if "CODINGWORKSPACE_PREVIEW_MOVED=true" not in promotion:
    raise SystemExit("workflow cannot distinguish completed preview promotion")

evidence = step(BUILD, "Record release evidence")
for required in (
    "immutable_publish_result",
    "contract_smoke_result",
    "sbom_result",
    "vulnerability_scan_result",
    "vulnerability_gate_result",
    "codingworkspace_promotion_requested",
    "published-image.txt",
    "SHA256SUMS",
    "independent_release_record_required_before_production=true",
):
    if required not in evidence:
        raise SystemExit(f"release evidence is missing {required}")
upload = step(BUILD, "Upload build, SBOM, and vulnerability evidence")
for required in ("github.run_id", "github.run_attempt", "if: always()"):
    if required not in upload:
        raise SystemExit(f"failure/rerun evidence handling is missing {required}")
vulnerability_report = step(BUILD, "Generate vulnerability report")
for required in (
    "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL",
    "ignore-unfixed: false",
    "exit-code: 0",
):
    if required not in vulnerability_report:
        raise SystemExit(f"all-severity vulnerability evidence is missing {required}")
vulnerability_gate = step(BUILD, "Enforce fixable CRITICAL vulnerability policy")
for required in ("severity: CRITICAL", "ignore-unfixed: true", "exit-code: 1"):
    if required not in vulnerability_gate:
        raise SystemExit(f"fixable-CRITICAL gate is missing {required}")
summary = step(BUILD, "Summarize verified moving tags")
for required in (
    "if: always()",
    "continue-on-error: true",
    "GITHUB_STEP_SUMMARY",
    "CODINGWORKSPACE_LATEST_MOVED",
    "CODINGWORKSPACE_PREVIEW_MOVED",
):
    if required not in summary:
        raise SystemExit(f"verified promotion summary is missing {required}")

for input_name in ("jupyter-images", "CodingWorkspace", "GizmoApp"):
    if f"check_tracked_clean {input_name}" not in LOCAL_PUBLISH:
        raise SystemExit(f"local publisher does not reject tracked {input_name} changes")
ordered_local = (
    "docker buildx build",
    '"${SCRIPT_DIR}/ci/smoke-image.sh" contract',
    '"${SCRIPT_DIR}/ci/scan-local-image.sh"',
    'docker push "$IMAGE"',
    "published-image.txt",
)
local_positions = [LOCAL_PUBLISH.find(item) for item in ordered_local]
if any(position < 0 for position in local_positions) or local_positions != sorted(
    local_positions
):
    raise SystemExit("local publisher does not build/load/smoke/scan/push/record in order")
if "--load" not in LOCAL_PUBLISH or "--push" in LOCAL_PUBLISH:
    raise SystemExit("local publisher must load and gate the image before an explicit push")
for required in (
    "trivy_version=0.74.0",
    "2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a",
    "b94ce1976bbf3c15b514b605ee88be7c6d94a29be2302847ff01cb794d47aad5",
    "--severity CRITICAL",
    "--ignore-unfixed",
    "--exit-code 1",
    "trivy-all.json",
    "SHA256SUMS",
):
    if required not in LOCAL_SCAN:
        raise SystemExit(f"local image scan gate is missing {required}")

print("CI trust-boundary policy validation passed.")
