#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from verify_cw_candidate import CandidateVerificationError, verify_candidate


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class VerifyCodingWorkspaceCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo = Path(self.tempdir.name) / "private-clone"
        self.repo.mkdir()
        git(self.repo, "init", "--quiet", "--initial-branch=main")
        git(self.repo, "config", "user.name", "CI Test")
        git(self.repo, "config", "user.email", "ci@example.invalid")

        fixture = self.repo / "fixture.txt"
        fixture.write_text("base\n", encoding="utf-8")
        git(self.repo, "add", "fixture.txt")
        git(self.repo, "commit", "--quiet", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

        fixture.write_text("main\n", encoding="utf-8")
        git(self.repo, "commit", "--quiet", "-am", "main tip")
        self.main_tip = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", self.main_tip)

        git(self.repo, "switch", "--quiet", "--detach", self.base)
        fixture.write_text("side\n", encoding="utf-8")
        git(self.repo, "commit", "--quiet", "-am", "unmerged side")
        self.side = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_accepts_origin_main_tip_and_ancestor(self) -> None:
        for candidate in (self.base, self.main_tip):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    verify_candidate(self.repo, candidate),
                    self.main_tip,
                )

    def test_rejects_existing_commit_not_reachable_from_origin_main(self) -> None:
        with self.assertRaisesRegex(CandidateVerificationError, "not reachable"):
            verify_candidate(self.repo, self.side)

    def test_rejects_unknown_commit_and_missing_origin_main(self) -> None:
        with self.assertRaises(CandidateVerificationError):
            verify_candidate(self.repo, "0" * 40)
        git(self.repo, "update-ref", "-d", "refs/remotes/origin/main")
        with self.assertRaises(CandidateVerificationError):
            verify_candidate(self.repo, self.base)

    def test_rejects_non_exact_candidate_values(self) -> None:
        for candidate in (self.base[:12], self.base.upper(), f"{self.base}\n"):
            with self.subTest(candidate=repr(candidate)):
                with self.assertRaisesRegex(CandidateVerificationError, "exactly 40"):
                    verify_candidate(self.repo, candidate)


if __name__ == "__main__":
    unittest.main()
