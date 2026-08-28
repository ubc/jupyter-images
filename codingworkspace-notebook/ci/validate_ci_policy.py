#!/usr/bin/env python3
"""Regression checks for the release/promotion trust boundary."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BUILD = (ROOT / ".github/workflows/build.yml").read_text(encoding="utf-8")
TRACK = (ROOT / ".github/workflows/track-cw.yml").read_text(encoding="utf-8")

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


for path in (ROOT / ".github/workflows").glob("*.yml"):
    text = path.read_text(encoding="utf-8")
    for owner_repo, sha in re.findall(r"uses:\s*([^@\s]+)@([0-9a-f]{40})", text):
        expected = EXPECTED_ACTIONS.get(owner_repo)
        if expected is None:
            raise SystemExit(f"unreviewed external Action in {path}: {owner_repo}@{sha}")
        if sha != expected:
            raise SystemExit(f"unexpected pin for {owner_repo}: {sha}")

publish_gate = re.search(r"(?ms)^  build-scan-publish:.*?^    runs-on:", BUILD)
if not publish_gate:
    raise SystemExit("publish job gate is missing")
gate = publish_gate.group(0)
for required in (
    "github.ref == 'refs/heads/main'",
    "github.event_name == 'push'",
    "github.event_name == 'workflow_dispatch'",
    "inputs.publish == true",
):
    if required not in gate:
        raise SystemExit(f"publish job gate is missing {required}")

ordinary_latest = step(BUILD, "Move ordinary latest tag")
if "matrix.image != 'codingworkspace-notebook'" not in ordinary_latest:
    raise SystemExit("an image-source merge could move CodingWorkspace latest")

promotion = step(BUILD, "Promote approved CodingWorkspace release")
for required in (
    "matrix.image == 'codingworkspace-notebook'",
    "github.event_name == 'workflow_dispatch'",
    "inputs.promote_codingworkspace == true",
    "$ECR_REPOSITORY:latest",
    "$ECR_REPOSITORY:preview",
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
if not tracker_job or "github.ref == 'refs/heads/main'" not in tracker_job.group(0):
    raise SystemExit("release tracker is not restricted to its reviewed main definition")
if not re.search(
    r"(?ms)^permissions: \{\}\s*$.*?^  bump:.*?^    permissions:\s*$"
    r".*?^      contents: write\s*$.*?^      actions: write\s*$",
    TRACK,
):
    raise SystemExit("tracker write permissions are not isolated to its main-only job")

ordered_steps = (
    "Build and publish immutable candidate with provenance and BuildKit SBOM",
    "Run CodingWorkspace image contract smoke",
    "Generate SPDX SBOM",
    "Generate vulnerability report",
    "Record release evidence",
    "Upload build, SBOM, and vulnerability evidence",
    "Promote approved CodingWorkspace release",
)
positions = [BUILD.find(f"      - name: {name}") for name in ordered_steps]
if any(position < 0 for position in positions) or positions != sorted(positions):
    raise SystemExit("published-digest smoke/scan/promotion steps are missing or out of order")
if BUILD.count("docker buildx build") != 1:
    raise SystemExit("the trusted job must build/push exactly once so scans match publication")
for required in (
    'docker pull "$ECR_REPOSITORY@$digest"',
    'docker tag "$ECR_REPOSITORY@$digest" "$LOCAL_IMAGE"',
    "printf 'IMAGE_DIGEST=%s\\n' \"$digest\" >> \"$GITHUB_ENV\"",
):
    if required not in BUILD:
        raise SystemExit(f"published digest is not made authoritative for evidence: {required}")
for required in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "-gz${GIZMOAPP_REF:0:7}"):
    if required not in BUILD:
        raise SystemExit(f"candidate tags are not run-unique and source-identifying: {required}")

for tag in ("latest", "preview"):
    if f"--image-ids imageTag={tag}" not in promotion:
        raise SystemExit(f"CodingWorkspace promotion does not verify the {tag} digest")
if promotion.find("imageTag=latest") > promotion.find("$ECR_REPOSITORY:preview"):
    raise SystemExit("CodingWorkspace preview can move before latest is verified")
if "CODINGWORKSPACE_PREVIEW_MOVED=true" not in promotion:
    raise SystemExit("workflow cannot distinguish completed preview promotion")

evidence = step(BUILD, "Record release evidence")
for required in (
    "immutable_publish_result",
    "contract_smoke_result",
    "sbom_result",
    "vulnerability_scan_result",
    "codingworkspace_promotion_requested",
):
    if required not in evidence:
        raise SystemExit(f"release evidence is missing {required}")
upload = step(BUILD, "Upload build, SBOM, and vulnerability evidence")
for required in ("github.run_id", "github.run_attempt", "if: always()"):
    if required not in upload:
        raise SystemExit(f"failure/rerun evidence handling is missing {required}")
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

print("CI trust-boundary policy validation passed.")
