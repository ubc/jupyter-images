#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from prepare_git_blob_context import prepare


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


class PrepareGitBlobContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "source"
        git("init", "--quiet", "--initial-branch=main", str(self.repository))
        git("config", "user.name", "Context Test", cwd=self.repository)
        git("config", "user.email", "context-test@example.invalid", cwd=self.repository)
        git(
            "remote",
            "add",
            "origin",
            "https://builder-user:builder-secret@example.invalid/private.git",
            cwd=self.repository,
        )
        (self.repository / ".gitignore").write_text("ignored-secret\n", encoding="utf-8")
        scripts = self.repository / "scripts"
        scripts.mkdir()
        self.builder = scripts / "builder.py"
        self.builder.write_text("print('reviewed builder')\n", encoding="utf-8")
        git("add", ".gitignore", "scripts/builder.py", cwd=self.repository)
        git("commit", "--quiet", "-m", "Add builder", cwd=self.repository)
        self.ref = git("rev-parse", "HEAD", cwd=self.repository)
        self.blob = git("rev-parse", "HEAD:scripts/builder.py", cwd=self.repository)
        (self.repository / "ignored-secret").write_text("credential", encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_extracts_only_the_reviewed_blob(self) -> None:
        output = self.root / "context"
        destination = prepare(
            self.repository,
            self.ref,
            "scripts/builder.py",
            self.blob,
            output,
        )
        self.assertEqual(["builder.py"], [entry.name for entry in output.iterdir()])
        self.assertEqual(destination.read_text(encoding="utf-8"), "print('reviewed builder')\n")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o444)
        self.assertNotIn("builder-secret", destination.read_text(encoding="utf-8"))

    def test_rejects_a_commit_to_blob_mismatch(self) -> None:
        with self.assertRaisesRegex(SystemExit, "does not match the reviewed blob"):
            prepare(
                self.repository,
                self.ref,
                "scripts/builder.py",
                "0" * 40,
                self.root / "context",
            )


if __name__ == "__main__":
    unittest.main()
