#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verify_installed_source import (
    main,
    stale_build_artifacts,
    tree_problems,
    version_problems,
)


PACKAGE = "verifysourcepkg"


def write(path: Path, content: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


class VerifyInstalledSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "cwbuild"
        self.package = self.source / PACKAGE
        write(self.source / "pyproject.toml", "[project]\nname = 'x'\n")
        write(self.package / "__init__.py", '__version__ = "1.0.15"\n')
        write(self.package / "exercises.py", "def hub_asset_problem(path):\n    return None\n")
        write(self.package / "RELEASE_SERIAL", "15\n")
        write(self.package / "exercise_data" / "catalog.json", "[]\n")
        write(self.package / "exercise_data" / "fridge.bundle", b"\x00bundle")
        self.site = self.root / "site-packages"
        self.installed = self.site / PACKAGE
        shutil.copytree(self.package, self.installed)
        write(self.installed / "__pycache__" / "__init__.cpython-313.pyc", b"\x00pyc")
        write(
            self.site / f"{PACKAGE}-1.0.15.dist-info" / "METADATA",
            f"Metadata-Version: 2.1\nName: {PACKAGE}\nVersion: 1.0.15\n",
        )

    def tearDown(self) -> None:
        sys.modules.pop(PACKAGE, None)
        if str(self.site) in sys.path:
            sys.path.remove(str(self.site))
        self.temporary.cleanup()

    def test_pristine_archive_reports_no_setuptools_output(self) -> None:
        self.assertEqual(stale_build_artifacts(self.source), [])

    def test_tracked_setuptools_output_is_named(self) -> None:
        write(self.source / "build" / "lib" / PACKAGE / "exercises.py", "stale\n")
        write(self.source / "dist" / "x-1.0.14-py3-none-any.whl", b"\x00")
        write(self.source / f"{PACKAGE}.egg-info" / "PKG-INFO", "Name: x\n")
        write(self.source / "src" / "other.egg-info" / "PKG-INFO", "Name: y\n")
        self.assertEqual(
            stale_build_artifacts(self.source),
            ["build", "dist", f"{PACKAGE}.egg-info", "src/other.egg-info"],
        )

    def test_dangling_build_symlink_still_counts(self) -> None:
        (self.source / "build").symlink_to(self.root / "nowhere")
        self.assertEqual(stale_build_artifacts(self.source), ["build"])

    def test_identical_trees_pass_and_ignore_bytecode_caches(self) -> None:
        write(self.package / "__pycache__" / "exercises.cpython-313.pyc", b"\x00other")
        self.assertEqual(tree_problems(self.package, self.installed), [])

    def test_stale_installed_module_is_named(self) -> None:
        write(self.installed / "exercises.py", "def hub_asset_problem(path):\n    return 'root'\n")
        problems = tree_problems(self.package, self.installed)
        self.assertEqual(len(problems), 1)
        self.assertIn("exercises.py", problems[0])
        self.assertIn("differs", problems[0])

    def test_missing_and_extra_installed_files_are_named(self) -> None:
        (self.installed / "exercise_data" / "fridge.bundle").unlink()
        write(self.installed / "leftover.py", "\n")
        problems = tree_problems(self.package, self.installed)
        self.assertEqual(
            problems,
            [
                "exercise_data/fridge.bundle: in the source commit but not installed",
                "leftover.py: installed but absent from the source commit",
            ],
        )

    def test_version_must_follow_the_source_serial_and_metadata(self) -> None:
        self.assertEqual(version_problems(self.package, "1.0.15", "1.0.15"), [])
        self.assertEqual(version_problems(self.package, "2.3.15", "2.3.15"), [])
        stale = version_problems(self.package, "1.0.14", "1.0.14")
        self.assertEqual(len(stale), 1)
        self.assertIn("serial is 15", stale[0])
        metadata = version_problems(self.package, "1.0.15", "0.0.0")
        self.assertEqual(len(metadata), 1)
        self.assertIn("0.0.0", metadata[0])
        write(self.package / "RELEASE_SERIAL", "0\n")
        self.assertIn("positive integer", version_problems(self.package, "1.0.0", "1.0.0")[0])
        (self.package / "RELEASE_SERIAL").unlink()
        self.assertIn("missing", version_problems(self.package, "1.0.0", "1.0.0")[0])

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_archive_phase_exit_status(self) -> None:
        code, out, err = self._run(["archive", "--source", str(self.source)])
        self.assertEqual((code, err), (0, ""))
        self.assertIn("no setuptools output", out)
        write(self.source / "build" / "lib" / PACKAGE / "__init__.py", "\n")
        code, out, err = self._run(["archive", "--source", str(self.source)])
        self.assertEqual(code, 1)
        self.assertIn("tracks setuptools output: build", err)
        self.assertIn("stale modules", err)

    def test_installed_phase_end_to_end(self) -> None:
        sys.path.insert(0, str(self.site))
        code, out, err = self._run(
            ["installed", "--source", str(self.source), "--package", PACKAGE]
        )
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"installed {PACKAGE} 1.0.15", out)
        self.assertIn("(5 files)", out)
        write(self.installed / "exercises.py", "stale\n")
        code, out, err = self._run(
            ["installed", "--source", str(self.source), "--package", PACKAGE]
        )
        self.assertEqual(code, 1)
        self.assertIn("exercises.py: installed copy differs", err)

    def test_installed_phase_refuses_an_import_from_the_source_tree(self) -> None:
        sys.path.insert(0, str(self.source))
        code, _, err = self._run(
            ["installed", "--source", str(self.source), "--package", PACKAGE]
        )
        self.assertEqual(code, 1)
        self.assertIn("resolved to the source tree", err)
        sys.path.remove(str(self.source))


if __name__ == "__main__":
    unittest.main()
