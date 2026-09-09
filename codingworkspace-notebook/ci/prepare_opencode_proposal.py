#!/usr/bin/env python3
"""Create or safely resume a verified OpenCode proposal without force-pushing."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


PINS = "codingworkspace-notebook/RUNTIME_PINS.env"
KEYS = {
    "OPENCODE_VERSION",
    "OPENCODE_LINUX_AMD64_BASELINE_SHA256",
    "OPENCODE_LINUX_ARM64_SHA256",
}
POLICY_DENIAL = (
    "pull request create failed: GraphQL: GitHub Actions is not permitted "
    "to create or approve pull requests (createPullRequest)"
)
REPOSITORY = "ubc/jupyter-images"


def run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=check)


def validate_pin_change(before: str, after: str) -> None:
    def remaining(text: str) -> list[str]:
        lines = text.splitlines(keepends=True)
        found = [line.split("=", 1)[0] for line in lines if line.split("=", 1)[0] in KEYS]
        if set(found) != KEYS or len(found) != len(KEYS):
            raise ValueError("proposal must contain each OpenCode pin exactly once")
        return [line for line in lines if line.split("=", 1)[0] not in KEYS]

    if remaining(before) != remaining(after):
        raise ValueError("proposal changes runtime content outside the three OpenCode pins")


def validate_existing_branch(reference: str, expected_pins: str) -> None:
    base = run("git", "merge-base", "HEAD", reference).stdout.strip()
    paths = run("git", "diff", "--name-only", base, reference).stdout.splitlines()
    if paths != [PINS]:
        raise ValueError("existing proposal branch is not an isolated OpenCode pin update")
    previous = run("git", "show", f"{base}:{PINS}").stdout
    proposed = run("git", "show", f"{reference}:{PINS}").stdout
    validate_pin_change(previous, proposed)
    if proposed != expected_pins:
        raise ValueError("existing proposal branch does not match the freshly verified runtime pins")


def policy_blocked(result: subprocess.CompletedProcess[str]) -> bool:
    # Only this precise repository policy restriction is a deferred outcome.
    # Authentication, network, branch protection and all other errors still fail.
    return result.returncode != 0 and not result.stdout.strip() and result.stderr.strip() == POLICY_DENIAL


def prepare_proposal(version: str, published_at: str) -> str:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("invalid stable OpenCode version")
    branch = f"automation/opencode-v{version}"
    existing = run(
        "gh", "pr", "list", "--repo", REPOSITORY, "--state", "open", "--head", branch,
        "--json", "url", "--jq", '.[0].url // ""',
    ).stdout.strip()
    expected = Path(PINS).read_text(encoding="utf-8")
    if run("git", "diff", "--name-only", "HEAD").stdout.splitlines() != [PINS]:
        raise ValueError("working tree must contain only the freshly verified runtime pin change")
    validate_pin_change(run("git", "show", f"HEAD:{PINS}").stdout, expected)
    remote = run("git", "ls-remote", "--exit-code", "--heads", "origin", f"refs/heads/{branch}", check=False)
    if remote.returncode == 0:
        # A preceding run may have pushed successfully, then failed to create
        # its PR. Reuse only the exact verified pin change; never reset/rebase it.
        run("git", "fetch", "--no-tags", "origin", f"refs/heads/{branch}")
        validate_existing_branch("FETCH_HEAD", expected)
        # The verified change is already durable on the remote branch. Keep
        # this checkout clean so later validation/rollback can switch refs.
        run("git", "restore", "--source=HEAD", "--staged", "--worktree", "--", PINS)
    elif remote.returncode == 2:
        if existing:
            raise ValueError("open proposal no longer has its expected remote branch")
        run("git", "switch", "--create", branch)
        run("git", "add", PINS)
        run("git", "commit", "-m", f"auto: update OpenCode to {version}")
        run("git", "push", "origin", f"HEAD:refs/heads/{branch}")
    else:
        remote.check_returncode()
    if existing:
        return existing

    body = (
        f"Automated stable-release update. The release was published at {published_at}, "
        "passed the 48-hour soak, matched GitHub's published SHA-256 digests for "
        "amd64-baseline and arm64, and passed the image CLI contract checks. "
        "After protected validation and merge, a trusted main dispatch will rebuild, "
        "smoke-test, produce an SBOM, scan, and reject fixable critical vulnerabilities "
        "before moving preview."
    )
    with tempfile.TemporaryDirectory(prefix="opencode-proposal-") as temporary:
        body_path = Path(temporary) / "body.md"
        body_path.write_text(body + "\n", encoding="utf-8")
        result = run(
            "gh", "pr", "create", "--repo", REPOSITORY, "--base", "main", "--head", branch,
            "--title", f"auto: update OpenCode to {version}", "--body-file", str(body_path), check=False,
        )
    if policy_blocked(result):
        compare = f"https://github.com/{REPOSITORY}/compare/main...{branch}?expand=1"
        message = (
            "OpenCode update deferred: repository policy does not permit GitHub Actions "
            "to create pull requests. The verified proposal branch was retained; "
            "no runtime pin was merged and no image was built or promoted. "
            f"A maintainer may review/open the proposal at {compare}."
        )
        print(f"::notice::{message}", file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as target:
                target.write(f"### OpenCode update deferred by repository policy\n\n{message}\n")
        return ""
    result.check_returncode()
    url = result.stdout.strip()
    if not re.fullmatch(r"https://github\.com/ubc/jupyter-images/pull/[0-9]+", url):
        raise ValueError("GitHub did not return the created update pull request URL")
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--published-at", required=True)
    arguments = parser.parse_args()
    try:
        print(prepare_proposal(arguments.version, arguments.published_at))
    except subprocess.CalledProcessError as error:
        print(error.stderr or error.stdout or str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
