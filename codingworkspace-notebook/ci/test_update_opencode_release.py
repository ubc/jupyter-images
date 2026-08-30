#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import io
import tarfile
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("update_opencode_release.py")
SPEC = importlib.util.spec_from_file_location("update_opencode_release", MODULE_PATH)
assert SPEC and SPEC.loader
release_update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_update)


def release(version: str, published_at: str, *, prerelease: bool = False):
    return {
        "tag_name": f"v{version}",
        "published_at": published_at,
        "draft": False,
        "prerelease": prerelease,
        "assets": [
            {
                "name": name,
                "digest": f"sha256:{character * 64}",
                "browser_download_url": (
                    f"https://github.com/anomalyco/opencode/releases/download/v{version}/{name}"
                ),
            }
            for name, character in (
                ("opencode-linux-x64-baseline.tar.gz", "a"),
                ("opencode-linux-arm64.tar.gz", "b"),
            )
        ],
    }


class OpenCodeReleaseUpdateTests(unittest.TestCase):
    def test_selects_newest_stable_release_that_completed_soak(self) -> None:
        selected = release_update.select_release(
            [
                release("1.18.24", "2026-08-20T00:00:00Z"),
                release("1.18.25", "2026-08-29T12:00:00Z"),
                release("1.19.0", "2026-08-15T00:00:00Z", prerelease=True),
            ],
            "1.18.23",
            minimum_age_hours=48,
            now=datetime(2026, 8, 30, tzinfo=UTC),
        )
        self.assertEqual(selected["version"], "1.18.24")

    def test_rejects_missing_published_digest_or_unexpected_download_host(self) -> None:
        candidate = release("1.18.24", "2026-08-20T00:00:00Z")
        candidate["assets"][0]["digest"] = None
        self.assertIsNone(release_update.release_metadata(candidate))
        candidate = release("1.18.24", "2026-08-20T00:00:00Z")
        candidate["assets"][0]["browser_download_url"] = "https://example.test/archive"
        self.assertIsNone(release_update.release_metadata(candidate))

    def test_archive_digest_shape_and_cli_contract_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "opencode.tar.gz"
            program = b"""#!/bin/sh
case "$*" in
  --version) echo 'opencode 1.18.24' ;;
  'run --help') echo '--format --model --dir --session' ;;
  'auth login --help') echo '--provider --method' ;;
  *) exit 2 ;;
esac
"""
            with tarfile.open(archive_path, "w:gz") as archive:
                member = tarfile.TarInfo("opencode")
                member.size = len(program)
                member.mode = 0o755
                archive.addfile(member, io.BytesIO(program))
            digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            release_update.verify_archive(
                archive_path,
                digest,
                "1.18.24",
                execute_contract=True,
            )
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                release_update.verify_archive(
                    archive_path,
                    "0" * 64,
                    "1.18.24",
                    execute_contract=False,
                )

    def test_pin_replacement_changes_only_the_three_opencode_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pins = Path(temporary) / "pins.env"
            pins.write_text(
                "NODE_VERSION=22.23.2\n"
                "OPENCODE_VERSION=1.18.23\n"
                f"OPENCODE_LINUX_AMD64_BASELINE_SHA256={'a' * 64}\n"
                f"OPENCODE_LINUX_ARM64_SHA256={'b' * 64}\n",
                encoding="utf-8",
            )
            release_update.replace_pins(
                pins,
                {
                    "OPENCODE_VERSION": "1.18.24",
                    "OPENCODE_LINUX_AMD64_BASELINE_SHA256": "c" * 64,
                    "OPENCODE_LINUX_ARM64_SHA256": "d" * 64,
                },
            )
            values = release_update.pin_values(pins)
            self.assertEqual(values["NODE_VERSION"], "22.23.2")
            self.assertEqual(values["OPENCODE_VERSION"], "1.18.24")


if __name__ == "__main__":
    unittest.main()
