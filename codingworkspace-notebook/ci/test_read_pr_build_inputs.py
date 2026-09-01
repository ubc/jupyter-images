#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from read_pr_build_inputs import InputError, load


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
