"""Filesystem regressions for the disposable lifecycle legacy-state fixture."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

from smoke_legacy_fixture import prepare_legacy_fixture, verify_legacy_fixture


class LegacyFixtureTests(unittest.TestCase):
    def test_old_gnu_commands_inherit_setgid_and_new_fixture_is_exact_0700(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            home.chmod(0o2775)
            # Reproduce the old harness, including the apparently restrictive
            # chmod which GNU deliberately applies without clearing setgid.
            subprocess.run(["chmod", "0700", str(home)], check=True)
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o2700)
            run_dir = home / "cw" / "run"
            targets = [run_dir / name for name in ("github-credentials", "opencode-auth")]
            subprocess.run(
                ["install", "-d", "-m", "0700", str(run_dir), *(str(p) for p in targets)],
                check=True,
            )
            for target in targets:
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o2700)
            with self.assertRaisesRegex(ValueError, "mode=2700"):
                verify_legacy_fixture(home)
            for target in targets:
                target.rmdir()
            prepare_legacy_fixture(home)
            verify_legacy_fixture(home)
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o2700)
            for target in targets:
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_existing_state_is_not_normalized_or_removed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            target = home / "cw" / "run" / "github-credentials"
            target.mkdir(parents=True, mode=0o2755)
            retained = target / "retained"
            retained.write_text("keep")
            before = target.stat()
            with self.assertRaisesRegex(ValueError, "refusing existing state"):
                prepare_legacy_fixture(home)
            self.assertEqual(target.stat(), before)
            self.assertEqual(retained.read_text(), "keep")

    def test_verification_rejects_nonempty_wrong_mode_symlink_and_special_file(self):
        for kind in ("nonempty", "wrong-mode", "symlink", "fifo", "child-directory"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp_dir:
                home = Path(temp_dir)
                prepare_legacy_fixture(home)
                target = home / "cw" / "run" / "github-credentials"
                if kind == "nonempty":
                    (target / "retained").write_text("keep")
                elif kind == "wrong-mode":
                    target.chmod(0o2700)
                elif kind == "child-directory":
                    (target / "child").mkdir()
                else:
                    target.rmdir()
                    if kind == "symlink":
                        target.symlink_to(home)
                    else:
                        os.mkfifo(target)
                with self.assertRaises(ValueError):
                    verify_legacy_fixture(home)
                self.assertTrue(os.path.lexists(target))

    def test_verification_rejects_wrong_user_or_group(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            prepare_legacy_fixture(home)
            with mock.patch("smoke_legacy_fixture.os.geteuid", return_value=os.geteuid() + 1):
                with self.assertRaisesRegex(ValueError, "owned by the image user"):
                    verify_legacy_fixture(home)
            with mock.patch("smoke_legacy_fixture.os.getegid", return_value=os.getegid() + 1):
                with mock.patch("smoke_legacy_fixture.os.getgroups", return_value=[]):
                    with self.assertRaisesRegex(ValueError, "current group"):
                        verify_legacy_fixture(home)


if __name__ == "__main__":
    unittest.main()
