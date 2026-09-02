#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from read_pr_build_inputs import MAX_INPUT_BYTES, InputError, load


class PullRequestBuildInputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.image = self.root / "codingworkspace-notebook"
        self.image.mkdir()
        self.repository = Path(__file__).resolve().parents[2]
        checked_in = self.repository / "codingworkspace-notebook"
        for name in ("CW_REF", "GIZMOAPP_REF", "RUNTIME_PINS.env", "DEPENDENCY_LAYER.env"):
            (self.image / name).write_bytes((checked_in / name).read_bytes())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_loads_checked_in_exact_inputs(self) -> None:
        values = load(self.root)
        self.assertRegex(values["CW_REF"], r"^[0-9a-f]{40}$")
        self.assertRegex(values["DEPENDENCY_BUILDER_BLOB"], r"^[0-9a-f]{40}$")
        self.assertEqual(values["DEPENDENCY_WHEEL_INDEX_URL"], "https://pypi.org/simple")

    def test_rejects_shell_syntax_and_extra_keys(self) -> None:
        dependency = self.image / "DEPENDENCY_LAYER.env"
        dependency.write_text(
            dependency.read_text(encoding="utf-8") + "MALICIOUS=$(id)\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InputError, "unsupported"):
            load(self.root)

    def test_rejects_missing_duplicate_and_reordered_assignments(self) -> None:
        runtime = self.image / "RUNTIME_PINS.env"
        original = runtime.read_text(encoding="utf-8")
        active = [line for line in original.splitlines() if line and not line.startswith("#")]

        runtime.write_text("\n".join(active[:-1]) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(InputError, "keys or order"):
            load(self.root)

        runtime.write_text(original + f"{active[0]}\n", encoding="utf-8")
        with self.assertRaisesRegex(InputError, "unsupported"):
            load(self.root)

        reordered = active.copy()
        reordered[0], reordered[1] = reordered[1], reordered[0]
        runtime.write_text("\n".join(reordered) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(InputError, "keys or order"):
            load(self.root)

    def test_rejects_oversized_and_non_utf8_inputs(self) -> None:
        pin = self.image / "CW_REF"
        pin.write_bytes(b"a" * (MAX_INPUT_BYTES + 1))
        with self.assertRaisesRegex(InputError, "bounded single-link"):
            load(self.root)

        pin.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(InputError, "not UTF-8"):
            load(self.root)

    def test_rejects_invalid_pins_hashes_and_index(self) -> None:
        pin = self.image / "CW_REF"
        pin.write_text("A" * 40 + "\n", encoding="utf-8")
        with self.assertRaisesRegex(InputError, "full lowercase SHA-1"):
            load(self.root)

        checked_in = self.repository / "codingworkspace-notebook"
        pin.write_bytes((checked_in / "CW_REF").read_bytes())
        runtime = self.image / "RUNTIME_PINS.env"
        runtime_lines = runtime.read_text(encoding="utf-8").splitlines()
        runtime.write_text(
            "\n".join(
                "NODE_LINUX_AMD64_SHA256=" + "a" * 63
                if line.startswith("NODE_LINUX_AMD64_SHA256=")
                else line
                for line in runtime_lines
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InputError, "invalid NODE_LINUX_AMD64_SHA256"):
            load(self.root)

        runtime.write_bytes((checked_in / "RUNTIME_PINS.env").read_bytes())
        dependency = self.image / "DEPENDENCY_LAYER.env"
        dependency.write_text(
            dependency.read_text(encoding="utf-8").replace(
                "https://pypi.org/simple", "https://example.invalid/simple"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(InputError, "dependency wheel index URL"):
            load(self.root)

    def test_rejects_symlink_and_hardlink_inputs(self) -> None:
        pin = self.image / "CW_REF"
        target = self.image / "real-cw-ref"
        pin.replace(target)
        pin.symlink_to(target)
        with self.assertRaisesRegex(InputError, "single-link"):
            load(self.root)

        pin.unlink()
        target.replace(pin)
        os.link(pin, self.image / "linked-cw-ref")
        with self.assertRaisesRegex(InputError, "single-link"):
            load(self.root)


if __name__ == "__main__":
    unittest.main()
