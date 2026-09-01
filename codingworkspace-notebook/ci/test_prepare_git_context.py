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
        git(
            "remote",
            "add",
            "origin",
            "https://bundle-user:bundle-secret@example.invalid/private.git",
            cwd=self.repository,
        )
        (self.repository / ".gitignore").write_text("ignored-secret.txt\n", encoding="utf-8")
        (self.repository / "source.txt").write_text("reviewed source\n", encoding="utf-8")
        git("add", ".gitignore", "source.txt", cwd=self.repository)
        git("commit", "--quiet", "-m", "Add reviewed source", cwd=self.repository)
        (self.repository / "source.txt").write_text("reviewed source v2\n", encoding="utf-8")
        git("commit", "--quiet", "-am", "Update reviewed source", cwd=self.repository)
        (self.repository / "ignored-secret.txt").write_text(
            "working-tree credential\n", encoding="utf-8"
        )
        unreachable_secret = self.root / "unreachable-secret.txt"
        unreachable_secret.write_text("unreachable object credential\n", encoding="utf-8")
        self.unreachable_object = git(
            "hash-object", "-w", str(unreachable_secret), cwd=self.repository
        )
        self.head = git("rev-parse", "HEAD", cwd=self.repository)
        git("checkout", "--quiet", "--detach", self.head, cwd=self.repository)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_bundle_only_context_clones_the_exact_detached_commit(self) -> None:
        context = self.root / "context"
        bundle = prepare(self.repository, self.head, context)

        self.assertEqual([BUNDLE_NAME], [path.name for path in context.iterdir()])
        self.assertEqual(context.stat().st_mode & 0o777, 0o755)
        self.assertEqual(bundle.stat().st_mode & 0o777, 0o444)
        clone = self.root / "clone"
        git("clone", "--quiet", "--no-local", "--no-hardlinks", str(bundle), str(clone))
        self.assertEqual(git("rev-parse", "HEAD", cwd=clone), self.head)
        self.assertEqual(git("rev-parse", "--is-shallow-repository", cwd=clone), "false")
        self.assertEqual(git("status", "--porcelain", cwd=clone), "")
        self.assertNotIn("bundle-secret", git("config", "--list", cwd=clone))
        source_objects = {
            line.split(" ", 1)[0]
            for line in git("rev-list", "--objects", "HEAD", cwd=self.repository).splitlines()
        }
        clone_objects = {
            line.split(" ", 1)[0]
            for line in git("rev-list", "--objects", "HEAD", cwd=clone).splitlines()
        }
        self.assertEqual(clone_objects, source_objects)
        missing = subprocess.run(
            ["git", "cat-file", "-e", self.unreachable_object],
            cwd=clone,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.assertNotEqual(missing.returncode, 0)
        git("fsck", "--full", "--strict", cwd=clone)

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
