#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from prepare_git_context import BUNDLE_NAME, prepare


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


class PrepareGitContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repository = self.root / "source"
        git("init", "--quiet", "--initial-branch=main", str(self.repository))
        git("config", "user.name", "Context Test", cwd=self.repository)
        git("config", "user.email", "context-test@example.invalid", cwd=self.repository)
        (self.repository / "source.txt").write_text("reviewed source\n", encoding="utf-8")
        git("add", "source.txt", cwd=self.repository)
        git("commit", "--quiet", "-m", "Add reviewed source", cwd=self.repository)
        self.head = git("rev-parse", "HEAD", cwd=self.repository)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_bundle_only_context_clones_the_exact_detached_commit(self) -> None:
        context = self.root / "context"
        bundle = prepare(self.repository, self.head, context)

        self.assertEqual([BUNDLE_NAME], [path.name for path in context.iterdir()])
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o444)
        clone = self.root / "clone"
        git("clone", "--quiet", str(bundle), str(clone))
        self.assertEqual(git("rev-parse", "HEAD", cwd=clone), self.head)
        self.assertEqual(git("rev-parse", "--is-shallow-repository", cwd=clone), "false")
        self.assertEqual(git("status", "--porcelain", cwd=clone), "")

    def test_rejects_a_mismatched_ref(self) -> None:
        with self.assertRaisesRegex(SystemExit, "does not match expected ref"):
            prepare(self.repository, "0" * 40, self.root / "context")

    def test_rejects_uncommitted_input(self) -> None:
        (self.repository / "untracked.txt").write_text("not reviewed\n", encoding="utf-8")
        with self.assertRaisesRegex(SystemExit, "contains tracked, staged, or untracked changes"):
            prepare(self.repository, self.head, self.root / "context")

    def test_refuses_to_replace_an_existing_context(self) -> None:
        context = self.root / "context"
        context.mkdir()
        with self.assertRaisesRegex(SystemExit, "already exists"):
            prepare(self.repository, self.head, context)


if __name__ == "__main__":
    unittest.main()
