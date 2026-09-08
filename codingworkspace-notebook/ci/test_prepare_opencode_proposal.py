#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "prepare_opencode_proposal", Path(__file__).with_name("prepare_opencode_proposal.py")
)
assert SPEC and SPEC.loader
proposal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proposal)
REAL_RUN = proposal.run


def pins(version: str, digest: str) -> str:
    return (
        "# Reviewed runtime pins\nNODE_VERSION=22.23.2\n"
        f"OPENCODE_VERSION={version}\n"
        f"OPENCODE_LINUX_AMD64_BASELINE_SHA256={digest * 64}\n"
        f"OPENCODE_LINUX_ARM64_SHA256={digest * 64}\n"
    )


class ProposalRetryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="opencode-proposal-test-")
        self.root = Path(self.temporary.name)
        self.previous_cwd = Path.cwd()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.chdir, self.previous_cwd)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        os.chdir(self.repo)
        REAL_RUN("git", "init", "--initial-branch=main")
        REAL_RUN("git", "config", "user.name", "Proposal test")
        REAL_RUN("git", "config", "user.email", "proposal-test@example.invalid")
        self.pin_path = Path(proposal.PINS)
        self.pin_path.parent.mkdir(parents=True)
        self.before = pins("1.18.25", "a")
        self.after = pins("1.18.29", "b")
        self.pin_path.write_text(self.before, encoding="utf-8")
        Path("reviewed.txt").write_text("keep\n", encoding="utf-8")
        REAL_RUN("git", "add", ".")
        REAL_RUN("git", "commit", "-m", "reviewed base")
        REAL_RUN("git", "init", "--bare", str(self.root / "origin.git"))
        REAL_RUN("git", "remote", "add", "origin", str(self.root / "origin.git"))
        REAL_RUN("git", "push", "origin", "main")
        self.branch = "automation/opencode-v1.18.29"
        self.summary = self.root / "summary.md"
        self.gh_calls: list[tuple[str, ...]] = []
        self.gh_error = proposal.POLICY_DENIAL
        self.open_url = ""
        self.created_url = "https://github.com/ubc/jupyter-images/pull/123"

    def fake_run(self, *command: str, check: bool = True):
        if command[0] != "gh":
            return REAL_RUN(*command, check=check)
        self.gh_calls.append(command)
        if command[1:3] == ("pr", "list"):
            return subprocess.CompletedProcess(command, 0, self.open_url, "")
        self.assertEqual(command[1:3], ("pr", "create"))
        body = Path(command[command.index("--body-file") + 1]).read_text()
        self.assertIn("passed the 48-hour soak", body)
        return subprocess.CompletedProcess(
            command, 1 if self.gh_error else 0,
            "" if self.gh_error else self.created_url, self.gh_error,
        )

    def prepare(self) -> str:
        with mock.patch.object(proposal, "run", side_effect=self.fake_run), mock.patch.dict(
            os.environ, {"GITHUB_STEP_SUMMARY": str(self.summary)}
        ), contextlib.redirect_stderr(io.StringIO()):
            return proposal.prepare_proposal("1.18.29", "2026-09-04T23:47:16+00:00")

    def remote_head(self) -> str:
        return REAL_RUN("git", "ls-remote", "origin", f"refs/heads/{self.branch}").stdout.split()[0]

    def orphan(self, *, extra_file: bool = False, node_change: bool = False, wrong_pin: bool = False) -> str:
        REAL_RUN("git", "switch", "--create", self.branch)
        contents = pins("1.18.29", "c") if wrong_pin else self.after
        if node_change:
            contents = contents.replace("22.23.2", "23.0.0")
        self.pin_path.write_text(contents, encoding="utf-8")
        if extra_file:
            Path("reviewed.txt").write_text("changed\n", encoding="utf-8")
        REAL_RUN("git", "add", ".")
        REAL_RUN("git", "commit", "-m", "orphan proposal")
        REAL_RUN("git", "push", "origin", self.branch)
        head = self.remote_head()
        REAL_RUN("git", "switch", "main")
        self.pin_path.write_text(self.after, encoding="utf-8")
        return head

    def test_policy_denial_and_retry_preserve_existing_branch_and_main(self) -> None:
        main = REAL_RUN("git", "rev-parse", "main").stdout
        self.pin_path.write_text(self.after, encoding="utf-8")
        self.assertEqual(self.prepare(), "")
        first_head = self.remote_head()
        REAL_RUN("git", "switch", "main")
        self.pin_path.write_text(self.after, encoding="utf-8")
        self.assertEqual(self.prepare(), "")
        self.assertEqual(self.remote_head(), first_head)
        self.assertEqual(REAL_RUN("git", "rev-parse", "main").stdout, main)
        summary = self.summary.read_text()
        self.assertIn("deferred by repository policy", summary)
        self.assertIn(f"compare/main...{self.branch}?expand=1", summary)
        self.assertIn("no runtime pin was merged", summary)

    def test_existing_orphan_can_get_pr_when_policy_permits(self) -> None:
        head = self.orphan()
        self.gh_error = ""
        self.assertEqual(self.prepare(), self.created_url)
        self.assertEqual(self.remote_head(), head)
        self.assertEqual(REAL_RUN("git", "status", "--porcelain").stdout, "")

    def test_refuses_existing_branch_with_other_file_changes(self) -> None:
        head = self.orphan(extra_file=True)
        with self.assertRaisesRegex(ValueError, "not an isolated"):
            self.prepare()
        self.assertEqual(self.remote_head(), head)
        self.assertEqual(len(self.gh_calls), 1)

    def test_refuses_existing_branch_with_non_opencode_pin_change(self) -> None:
        head = self.orphan(node_change=True)
        with self.assertRaisesRegex(ValueError, "outside the three"):
            self.prepare()
        self.assertEqual(self.remote_head(), head)

    def test_refuses_existing_branch_with_different_verified_digest(self) -> None:
        head = self.orphan(wrong_pin=True)
        with self.assertRaisesRegex(ValueError, "freshly verified"):
            self.prepare()
        self.assertEqual(self.remote_head(), head)

    def test_unrelated_pr_creation_error_still_fails(self) -> None:
        self.orphan()
        self.gh_error = "GraphQL: Resource not accessible by integration"
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertFalse(self.summary.exists())

    def test_network_error_still_fails_without_attempting_pr_creation(self) -> None:
        self.pin_path.write_text(self.after, encoding="utf-8")
        REAL_RUN("git", "remote", "set-url", "origin", str(self.root / "missing.git"))
        with self.assertRaises(subprocess.CalledProcessError):
            self.prepare()
        self.assertEqual(len(self.gh_calls), 1)
        self.assertFalse(self.summary.exists())

    def test_open_pr_is_reused_without_branch_mutation(self) -> None:
        head = self.orphan()
        self.open_url = self.created_url
        self.assertEqual(self.prepare(), self.created_url)
        self.assertEqual(len(self.gh_calls), 1)
        self.assertEqual(self.remote_head(), head)
        self.assertEqual(REAL_RUN("git", "status", "--porcelain").stdout, "")

    def test_only_exact_policy_error_is_deferred(self) -> None:
        for code, output, error in (
            (0, "", proposal.POLICY_DENIAL),
            (1, "unexpected response", proposal.POLICY_DENIAL),
            (1, "", proposal.POLICY_DENIAL + "\nconnection failed"),
            (1, "", "HTTP 403: Resource not accessible by integration"),
        ):
            self.assertFalse(proposal.policy_blocked(subprocess.CompletedProcess([], code, output, error)))
        self.assertTrue(proposal.policy_blocked(subprocess.CompletedProcess([], 1, "", proposal.POLICY_DENIAL)))


if __name__ == "__main__":
    unittest.main()
