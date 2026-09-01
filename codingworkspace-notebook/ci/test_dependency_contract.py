#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codingworkspace_dependency_contract import (
    dependency_manifest_metadata,
    finalize_dependency_manifest,
    image_dependency_environment,
)


LAYER_VERSION = "v1"
PYTHON_RECORD = {
    "implementation": sys.implementation.name,
    "version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI")
    or sys.implementation.cache_tag
    or "unknown",
    "cacheTag": sys.implementation.cache_tag or "unknown",
    "machine": platform.machine() or "unknown",
    "platform": sysconfig.get_platform(),
}


class DependencyContractTests(unittest.TestCase):
    def manifest(self, *, machine: str | None = None, finalized: bool = True) -> bytes:
        python_record = dict(PYTHON_RECORD)
        machine = machine or str(PYTHON_RECORD["machine"])
        python_record["machine"] = machine
        if machine == "aarch64":
            python_record["abi"] = "cpython-313-aarch64-linux-gnu"
            python_record["platform"] = "linux-aarch64"
        manifest = {
            "schema": "codingworkspace-dependency-wheelhouse/v1",
            "runtimeId": f"codingworkspace-wheelhouse-probe-{LAYER_VERSION}",
            "python": python_record,
            "dependencyInputSha256": "a" * 64,
            "dependencyInputs": {},
            "wheels": [
                {
                    "filename": "example-1.0-py3-none-any.whl",
                    "sha256": "b" * 64,
                    "size": 1,
                }
            ],
        }
        probe = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        metadata = dependency_manifest_metadata(
            probe,
            LAYER_VERSION,
            require_runtime_match=False,
            require_wheel_set_match=False,
        )
        if finalized:
            manifest["runtimeId"] = metadata["runtime_id"]
            manifest["wheelSetSha256"] = metadata["wheel_set_sha256"]
        return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")

    def write_artifact(self, root: Path, raw_manifest: bytes) -> tuple[Path, Path]:
        wheelhouse = root / "wheelhouse"
        wheelhouse.mkdir(mode=0o755)
        manifest = wheelhouse / "manifest.json"
        manifest.write_bytes(raw_manifest)
        manifest.chmod(0o444)
        wheelhouse.chmod(0o555)
        metadata = dependency_manifest_metadata(raw_manifest, LAYER_VERSION)
        contract = root / "dependency.env"
        contract.write_text(
            "\n".join(
                (
                    f"DEPENDENCY_WHEELHOUSE_LAYER_VERSION={LAYER_VERSION}",
                    f"DEPENDENCY_RUNTIME_ID={metadata['runtime_id']}",
                    "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256="
                    f"{metadata['manifest_sha256']}",
                )
            )
            + "\n",
            encoding="ascii",
        )
        contract.chmod(0o444)
        return wheelhouse, contract

    def test_runtime_id_changes_with_final_architecture(self) -> None:
        amd64 = dependency_manifest_metadata(self.manifest(), LAYER_VERSION)
        arm64_manifest = self.manifest(machine="aarch64")
        arm64 = dependency_manifest_metadata(arm64_manifest, LAYER_VERSION)
        self.assertNotEqual(amd64["runtime_id"], arm64["runtime_id"])
        self.assertIn(
            f":{PYTHON_RECORD['platform']}:{PYTHON_RECORD['machine']}:",
            amd64["runtime_id"],
        )
        self.assertIn(":linux-aarch64:aarch64", arm64["runtime_id"])
        self.assertRegex(amd64["runtime_id"].rsplit(":", 1)[-1], r"^[0-9a-f]{64}$")

    def test_exact_manifest_contract_produces_fixed_proxy_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheelhouse, contract = self.write_artifact(
                Path(temporary), self.manifest()
            )
            environment = image_dependency_environment(
                wheelhouse=wheelhouse,
                contract=contract,
                required_uid=os.getuid(),
            )
        self.assertEqual(
            environment["CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE"], str(wheelhouse)
        )
        self.assertEqual(
            environment["CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE_MODE"], "prefer"
        )
        self.assertEqual(
            environment["CODINGWORKSPACE_DEPENDENCY_RUNTIME_ID"],
            dependency_manifest_metadata(self.manifest(), LAYER_VERSION)["runtime_id"],
        )

    def test_root_finalizer_changes_only_identity_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheelhouse = Path(temporary) / "wheelhouse"
            wheelhouse.mkdir()
            manifest_path = wheelhouse / "manifest.json"
            probe = self.manifest(finalized=False)
            original = json.loads(probe)
            manifest_path.write_bytes(probe)
            manifest_path.chmod(0o444)
            wheelhouse.chmod(0o555)

            metadata = finalize_dependency_manifest(
                manifest_path, LAYER_VERSION, required_uid=os.getuid()
            )
            finalized = json.loads(manifest_path.read_bytes())
            expected_fields = dict(original)
            expected_fields.pop("runtimeId")
            observed_fields = dict(finalized)
            observed_fields.pop("runtimeId")
            self.assertEqual(
                observed_fields.pop("wheelSetSha256"), metadata["wheel_set_sha256"]
            )
            self.assertEqual(observed_fields, expected_fields)
            self.assertEqual(finalized["runtimeId"], metadata["runtime_id"])
            self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o444)
            self.assertEqual(wheelhouse.stat().st_mode & 0o777, 0o555)
            before = manifest_path.read_bytes()
            self.assertEqual(
                finalize_dependency_manifest(
                    manifest_path, LAYER_VERSION, required_uid=os.getuid()
                ),
                metadata,
            )
            self.assertEqual(manifest_path.read_bytes(), before)

    def test_runtime_or_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            wheelhouse, contract = self.write_artifact(
                Path(temporary), self.manifest()
            )
            text = contract.read_text(encoding="ascii")
            contract.chmod(0o644)
            contract.write_text(
                text.replace("DEPENDENCY_RUNTIME_ID=", "DEPENDENCY_RUNTIME_ID=wrong-"),
                encoding="ascii",
            )
            contract.chmod(0o444)
            with self.assertRaisesRegex(RuntimeError, "runtime ID differs"):
                image_dependency_environment(
                    wheelhouse=wheelhouse,
                    contract=contract,
                    required_uid=os.getuid(),
                )

            metadata = dependency_manifest_metadata(self.manifest(), LAYER_VERSION)
            contract.chmod(0o644)
            contract.write_text(
                "\n".join(
                    (
                        f"DEPENDENCY_WHEELHOUSE_LAYER_VERSION={LAYER_VERSION}",
                        f"DEPENDENCY_RUNTIME_ID={metadata['runtime_id']}",
                        "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256="
                        f"{hashlib.sha256(b'wrong').hexdigest()}",
                    )
                )
                + "\n",
                encoding="ascii",
            )
            contract.chmod(0o444)
            with self.assertRaisesRegex(RuntimeError, "manifest hash differs"):
                image_dependency_environment(
                    wheelhouse=wheelhouse,
                    contract=contract,
                    required_uid=os.getuid(),
                )

    def test_manifest_wheel_set_and_python_mismatches_are_rejected(self) -> None:
        wheel_set_tamper = json.loads(self.manifest())
        wheel_set_tamper["wheelSetSha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "wheel-set hash is invalid"):
            dependency_manifest_metadata(
                (json.dumps(wheel_set_tamper) + "\n").encode("utf-8"),
                LAYER_VERSION,
            )

        python_tamper = json.loads(self.manifest())
        python_tamper["python"]["version"] = "0.0.0"
        with self.assertRaisesRegex(RuntimeError, "differs from the runtime"):
            dependency_manifest_metadata(
                (json.dumps(python_tamper) + "\n").encode("utf-8"),
                LAYER_VERSION,
                require_runtime_match=False,
                require_current_python=True,
            )


if __name__ == "__main__":
    unittest.main()
