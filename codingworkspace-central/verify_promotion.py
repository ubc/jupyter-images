#!/usr/bin/env python3
"""Verify a course-published central image before and after promoting it.

The course team builds and publishes this image; we admit it to the platform
registry. Admission is a real gate, not a formality: it re-derives every claim
from the registry itself rather than trusting the requested digest, and it
refuses the review image, which is a different artifact that deliberately has
no working verifier.

Promotion copies the exact index digest, so the course team's provenance and
attestation manifests survive. Losing the attestation manifest would leave a
digest that no longer carries its SBOM/provenance, which is the whole reason to
promote rather than rebuild -- so its presence is asserted, not assumed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
INDEX_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}
# The review image (ubc/jupyter-images PR #30) carries this label. It has no
# production verifier and both verifier loaders refuse authentication, so it
# must never be promoted as if it were the deployable artifact.
REVIEW_LABEL = "io.codingworkspace.activation"


class Rejected(Exception):
    pass


def require(condition: object, message: str) -> None:
    if not condition:
        raise Rejected(message)


def load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise Rejected(f"cannot read {path}: {error}") from error


def check_receipt(arguments: argparse.Namespace) -> None:
    """Confirm the course receipt actually vouches for the requested digest."""
    receipt = load(arguments.receipt)
    require(receipt.get("schemaVersion") == 1,
            f"unsupported receipt schemaVersion: {receipt.get('schemaVersion')!r}")
    require(receipt.get("status") == "staging-candidate-passed",
            f"receipt status is not a passed candidate: {receipt.get('status')!r}")
    require(receipt.get("platform") == "linux/amd64",
            f"receipt platform is not linux/amd64: {receipt.get('platform')!r}")

    image = receipt.get("image", "")
    repository, _, digest = image.partition("@")
    require(digest == arguments.digest,
            f"receipt vouches for {digest!r}, not the requested {arguments.digest!r}")
    require(repository == arguments.expect_repository,
            f"receipt image repository is {repository!r}, expected {arguments.expect_repository!r}")

    commit = receipt.get("sourceCommit", "")
    require(COMMIT.fullmatch(commit), f"receipt sourceCommit is not a full SHA: {commit!r}")

    # productionActivated false is EXPECTED and not a rejection: the course team
    # withholds that until live integration passes. Promotion moves an artifact
    # between registries; it does not activate anything for students.
    print(f"receipt ok: digest vouched, source commit {commit}")
    Path(arguments.write_source_commit).write_text(commit + "\n", encoding="utf-8")


def check_image(arguments: argparse.Namespace) -> None:
    """Re-derive the image's own claims from the registry manifest and config."""
    manifest = load(arguments.manifest)
    config = load(arguments.config)

    require(manifest.get("mediaType") in INDEX_TYPES,
            f"expected a manifest index, got {manifest.get('mediaType')!r}")

    children = manifest.get("manifests") or []
    platforms = [
        (child.get("platform") or {}).get("architecture")
        for child in children
        if (child.get("annotations") or {}).get("vnd.docker.reference.type") != "attestation-manifest"
    ]
    require(platforms.count("amd64") == 1,
            f"expected exactly one linux/amd64 image manifest, found platforms {platforms}")

    attestations = [
        child for child in children
        if (child.get("annotations") or {}).get("vnd.docker.reference.type") == "attestation-manifest"
    ]
    require(attestations,
            "index carries no attestation manifest: promoting this would drop the "
            "provenance/SBOM the course build attached, which defeats copying by digest")

    settings = config.get("config") or {}
    labels = settings.get("Labels") or {}

    require(REVIEW_LABEL not in labels,
            f"image carries {REVIEW_LABEL}={labels.get(REVIEW_LABEL)!r}: this is the "
            "review image, which has no production verifier and is not deployable")

    require(settings.get("User") == arguments.expect_user,
            f"image runs as {settings.get('User')!r}, expected {arguments.expect_user!r}")

    revision = labels.get("org.opencontainers.image.revision")
    require(revision == arguments.source_commit,
            f"image revision label is {revision!r}, but the receipt names {arguments.source_commit!r}")

    source = labels.get("org.opencontainers.image.source")
    require(source == arguments.expect_source,
            f"image source label is {source!r}, expected {arguments.expect_source!r}")

    print(f"image ok: amd64 + {len(attestations)} attestation manifest(s), "
          f"user {settings.get('User')}, revision {revision}")


def check_destination(arguments: argparse.Namespace) -> None:
    """Confirm the promoted copy is byte-identical in the ways that matter."""
    require(arguments.destination_digest == arguments.digest,
            f"destination digest {arguments.destination_digest!r} does not match the "
            f"promoted source digest {arguments.digest!r}")

    source = load(arguments.manifest)
    destination = load(arguments.destination_manifest)

    def describe(index: dict) -> list[tuple[str, str]]:
        return sorted(
            (child.get("digest", ""),
             (child.get("annotations") or {}).get("vnd.docker.reference.type", "image"))
            for child in index.get("manifests") or []
        )

    require(describe(source) == describe(destination),
            "destination manifest set differs from source; attestations or platform "
            f"manifests were lost\n  source:      {describe(source)}\n  destination: {describe(destination)}")

    print(f"destination ok: same index digest, {len(describe(destination))} manifests preserved")


def write_admission_receipt(arguments: argparse.Namespace) -> None:
    receipt = {
        "kind": "CodingWorkspaceCentralAdmissionReceipt",
        "schemaVersion": 1,
        "sourceImage": f"{arguments.source_repository}@{arguments.digest}",
        "promotedImage": f"{arguments.destination_repository}@{arguments.digest}",
        "promotedTag": arguments.tag,
        "digestPreserved": True,
        "sourceCommit": arguments.source_commit,
        "courseReceipt": arguments.course_receipt_path,
        "imageRepositoryCommit": arguments.workflow_commit,
        "runId": arguments.run_id,
        "attempt": arguments.attempt,
        # Admission is a registry decision. It is not a student-activation
        # receipt and does not stand in for the course team's live integration
        # checks or the cluster deployment gates.
        "studentActivation": False,
        "scope": "registry admission of a course-published image; verification and "
                 "vulnerability policy re-applied on this side",
    }
    Path(arguments.output).write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {arguments.output}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)

    receipt = subcommands.add_parser("receipt")
    receipt.add_argument("--receipt", required=True)
    receipt.add_argument("--digest", required=True)
    receipt.add_argument("--expect-repository", required=True)
    receipt.add_argument("--write-source-commit", required=True)
    receipt.set_defaults(handler=check_receipt)

    image = subcommands.add_parser("image")
    image.add_argument("--manifest", required=True)
    image.add_argument("--config", required=True)
    image.add_argument("--source-commit", required=True)
    image.add_argument("--expect-user", default="10001:10001")
    image.add_argument("--expect-source", required=True)
    image.set_defaults(handler=check_image)

    destination = subcommands.add_parser("destination")
    destination.add_argument("--manifest", required=True)
    destination.add_argument("--destination-manifest", required=True)
    destination.add_argument("--digest", required=True)
    destination.add_argument("--destination-digest", required=True)
    destination.set_defaults(handler=check_destination)

    admission = subcommands.add_parser("admission-receipt")
    admission.add_argument("--digest", required=True)
    admission.add_argument("--source-repository", required=True)
    admission.add_argument("--destination-repository", required=True)
    admission.add_argument("--tag", required=True)
    admission.add_argument("--source-commit", required=True)
    admission.add_argument("--course-receipt-path", required=True)
    admission.add_argument("--workflow-commit", required=True)
    admission.add_argument("--run-id", required=True)
    admission.add_argument("--attempt", required=True)
    admission.add_argument("--output", required=True)
    admission.set_defaults(handler=write_admission_receipt)

    arguments = parser.parse_args()
    if getattr(arguments, "digest", None) and not DIGEST.fullmatch(arguments.digest):
        print(f"not an immutable sha256 digest: {arguments.digest!r}", file=sys.stderr)
        return 2
    try:
        arguments.handler(arguments)
    except Rejected as rejection:
        print(f"PROMOTION REJECTED: {rejection}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
