#!/usr/bin/env python3
"""Verify that an exact CodingWorkspace candidate belongs to origin/main."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path


FULL_LOWER_SHA = re.compile(r"[0-9a-f]{40}")
ORIGIN_MAIN = "refs/remotes/origin/main"


class CandidateVerificationError(ValueError):
    """Raised when a candidate is not an exact reachable SHA-1 commit."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or error.stdout.strip() or "Git command failed"
        raise CandidateVerificationError(detail) from error


def _exact_commit(repo: Path, ref: str, description: str) -> str:
    resolved = _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").stdout.strip()
    if not FULL_LOWER_SHA.fullmatch(resolved):
        raise CandidateVerificationError(
            f"{description} did not resolve to one full lowercase SHA-1 commit"
        )
    return resolved


def verify_candidate(repo: Path, candidate_sha: str) -> str:
    """Return origin/main's tip after verifying candidate is its ancestor."""

    if not FULL_LOWER_SHA.fullmatch(candidate_sha):
        raise CandidateVerificationError(
            "candidate SHA must be exactly 40 lowercase hexadecimal characters"
        )
    if not repo.is_dir():
        raise CandidateVerificationError(f"private clone is not a directory: {repo}")
    object_format = _git(repo, "rev-parse", "--show-object-format").stdout.strip()
    if object_format != "sha1":
        raise CandidateVerificationError(
            f"private clone must use SHA-1 objects, found {object_format or 'unknown'}"
        )

    origin_main = _exact_commit(repo, ORIGIN_MAIN, "freshly cloned origin/main")
    candidate = _exact_commit(repo, candidate_sha, "candidate SHA")
    if candidate != candidate_sha:
        raise CandidateVerificationError("candidate did not resolve to its exact SHA")

    ancestry = _git(
        repo,
        "merge-base",
        "--is-ancestor",
        candidate_sha,
        origin_main,
        check=False,
    )
    if ancestry.returncode == 1:
        raise CandidateVerificationError(
            "candidate SHA is not reachable from the freshly cloned origin/main"
        )
    if ancestry.returncode != 0:
        detail = ancestry.stderr.strip() or ancestry.stdout.strip() or "Git ancestry check failed"
        raise CandidateVerificationError(detail)
    return origin_main


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", type=Path)
    parser.add_argument("candidate_sha")
    args = parser.parse_args()
    try:
        origin_main = verify_candidate(args.repo, args.candidate_sha)
    except CandidateVerificationError as error:
        parser.error(str(error))
    print(origin_main)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
