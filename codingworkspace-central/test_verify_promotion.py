"""Promotion-gate regressions. No registry, network or credential required."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / "verify_promotion.py"
DIGEST = "sha256:" + "0a" * 32
OTHER_DIGEST = "sha256:" + "0b" * 32
COMMIT = "a6725bd58692c04cb5662884325be6ada3b9c5fa"
SOURCE_REPOSITORY = "ghcr.io/kevinlb1/codingworkspace-central"
SOURCE_URL = "https://github.com/kevinlb1/CodingWorkspace"


def receipt(**overrides: object) -> dict:
    body = {
        "schemaVersion": 1,
        "status": "staging-candidate-passed",
        "productionActivated": False,
        "image": f"{SOURCE_REPOSITORY}@{DIGEST}",
        "sourceCommit": COMMIT,
        "platform": "linux/amd64",
    }
    body.update(overrides)
    return body


def index(*, attestation: bool = True, architectures: tuple[str, ...] = ("amd64",)) -> dict:
    manifests = [
        {"digest": "sha256:" + f"{position:02x}" * 32,
         "platform": {"architecture": architecture, "os": "linux"}}
        for position, architecture in enumerate(architectures, start=1)
    ]
    if attestation:
        manifests.append({
            "digest": "sha256:" + "ff" * 32,
            "platform": {"architecture": "unknown", "os": "unknown"},
            "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
        })
    return {"mediaType": "application/vnd.oci.image.index.v1+json", "manifests": manifests}


def config(**label_overrides: object) -> dict:
    labels = {
        "org.opencontainers.image.revision": COMMIT,
        "org.opencontainers.image.source": SOURCE_URL,
    }
    labels.update(label_overrides)
    return {"config": {"User": "10001:10001", "Labels": labels}}


class PromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="cw-promotion-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name: str, body: object) -> str:
        path = self.root / name
        path.write_text(json.dumps(body), encoding="utf-8")
        return str(path)

    def run_gate(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), *arguments],
                              text=True, capture_output=True)

    # --- receipt ---------------------------------------------------------

    def check_receipt(self, body: dict, digest: str = DIGEST) -> subprocess.CompletedProcess[str]:
        return self.run_gate(
            "receipt", "--receipt", self.write("receipt.json", body), "--digest", digest,
            "--expect-repository", SOURCE_REPOSITORY,
            "--write-source-commit", str(self.root / "commit.txt"))

    def test_passing_receipt_exports_the_source_commit(self):
        result = self.check_receipt(receipt())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / "commit.txt").read_text(encoding="utf-8").strip(), COMMIT)

    def test_receipt_for_a_different_digest_is_rejected(self):
        result = self.check_receipt(receipt(), digest=OTHER_DIGEST)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not the requested", result.stderr)

    def test_receipt_from_an_unexpected_repository_is_rejected(self):
        body = receipt(image=f"ghcr.io/someone-else/codingworkspace-central@{DIGEST}")
        self.assertEqual(self.check_receipt(body).returncode, 1)

    def test_unpassed_candidate_is_rejected(self):
        for status in ("staging-candidate-failed", "in-progress", None):
            with self.subTest(status=status):
                self.assertEqual(self.check_receipt(receipt(status=status)).returncode, 1)

    def test_unsupported_schema_version_is_rejected(self):
        self.assertEqual(self.check_receipt(receipt(schemaVersion=2)).returncode, 1)

    def test_non_amd64_receipt_is_rejected(self):
        self.assertEqual(self.check_receipt(receipt(platform="linux/arm64")).returncode, 1)

    def test_production_activated_false_is_accepted(self):
        # The course team withholds activation until live integration passes;
        # promotion is a registry move and must not require it.
        self.assertEqual(self.check_receipt(receipt(productionActivated=False)).returncode, 0)

    def test_malformed_digest_argument_is_refused_before_any_check(self):
        result = self.check_receipt(receipt(), digest="latest")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not an immutable sha256 digest", result.stderr)

    # --- image -----------------------------------------------------------

    def check_image(self, manifest: dict, image_config: dict,
                    commit: str = COMMIT) -> subprocess.CompletedProcess[str]:
        return self.run_gate(
            "image", "--manifest", self.write("manifest.json", manifest),
            "--config", self.write("config.json", image_config),
            "--source-commit", commit, "--expect-source", SOURCE_URL)

    def test_production_image_passes(self):
        result = self.check_image(index(), config())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_review_image_is_rejected(self):
        result = self.check_image(
            index(), config(**{"io.codingworkspace.activation": "blocked-pending-reviewed-verifier"}))
        self.assertEqual(result.returncode, 1)
        self.assertIn("review image", result.stderr)

    def test_index_without_attestation_is_rejected(self):
        result = self.check_image(index(attestation=False), config())
        self.assertEqual(result.returncode, 1)
        self.assertIn("attestation", result.stderr)

    def test_revision_disagreeing_with_the_receipt_is_rejected(self):
        result = self.check_image(index(), config(), commit="b" * 40)
        self.assertEqual(result.returncode, 1)
        self.assertIn("revision label", result.stderr)

    def test_foreign_source_label_is_rejected(self):
        body = config(**{"org.opencontainers.image.source": "https://github.com/attacker/repo"})
        self.assertEqual(self.check_image(index(), body).returncode, 1)

    def test_unexpected_runtime_user_is_rejected(self):
        body = config()
        body["config"]["User"] = "0:0"
        self.assertEqual(self.check_image(index(), body).returncode, 1)

    def test_single_manifest_not_an_index_is_rejected(self):
        body = {"mediaType": "application/vnd.oci.image.manifest.v1+json"}
        self.assertEqual(self.check_image(body, config()).returncode, 1)

    def test_missing_amd64_manifest_is_rejected(self):
        result = self.check_image(index(architectures=("arm64",)), config())
        self.assertEqual(result.returncode, 1)
        self.assertIn("amd64", result.stderr)

    def test_duplicate_amd64_manifests_are_rejected(self):
        self.assertEqual(self.check_image(index(architectures=("amd64", "amd64")), config()).returncode, 1)

    # --- destination -----------------------------------------------------

    def check_destination(self, source: dict, destination: dict,
                          destination_digest: str = DIGEST) -> subprocess.CompletedProcess[str]:
        return self.run_gate(
            "destination", "--manifest", self.write("source.json", source),
            "--destination-manifest", self.write("destination.json", destination),
            "--digest", DIGEST, "--destination-digest", destination_digest)

    def test_identical_destination_passes(self):
        body = index()
        result = self.check_destination(body, json.loads(json.dumps(body)))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_destination_digest_is_rejected(self):
        result = self.check_destination(index(), index(), destination_digest=OTHER_DIGEST)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not match", result.stderr)

    def test_destination_that_dropped_the_attestation_is_rejected(self):
        # The failure mode a naive docker pull/push would introduce.
        result = self.check_destination(index(), index(attestation=False))
        self.assertEqual(result.returncode, 1)
        self.assertIn("attestations or platform", result.stderr)

    def test_destination_that_dropped_a_platform_is_rejected(self):
        source = index(architectures=("amd64", "arm64"))
        self.assertEqual(self.check_destination(source, index(architectures=("amd64",))).returncode, 1)

    # --- admission receipt ----------------------------------------------

    def test_admission_receipt_records_the_promotion_without_claiming_activation(self):
        output = self.root / "admission.json"
        result = self.run_gate(
            "admission-receipt", "--digest", DIGEST,
            "--source-repository", SOURCE_REPOSITORY,
            "--destination-repository", "ghcr.io/ubc/codingworkspace-central",
            "--tag", "promoted-abc-r1-a1", "--source-commit", COMMIT,
            "--course-receipt-path", "deploy/.../staging-receipt.json",
            "--workflow-commit", "c" * 40, "--run-id", "1", "--attempt", "1",
            "--output", str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        body = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(body["promotedImage"], f"ghcr.io/ubc/codingworkspace-central@{DIGEST}")
        self.assertEqual(body["sourceImage"], f"{SOURCE_REPOSITORY}@{DIGEST}")
        self.assertTrue(body["digestPreserved"])
        self.assertFalse(body["studentActivation"])


if __name__ == "__main__":
    unittest.main()
