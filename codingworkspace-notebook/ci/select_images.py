#!/usr/bin/env python3
"""Select top-level Docker image directories for a trusted build."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


NULL_SHA = "0" * 40
ROOT = Path(__file__).resolve().parents[2]


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return result.stdout.strip()


def image_directories() -> list[str]:
    return sorted(
        path.parent.name
        for path in ROOT.glob("*/Dockerfile")
        if path.parent.parent == ROOT
    )


def commit_exists(value: str) -> bool:
    if not value or value == NULL_SHA:
        return False
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


def changed_files(before: str, current: str) -> list[str]:
    if not commit_exists(current):
        raise SystemExit(f"current revision is not a commit: {current!r}")
    if not commit_exists(before):
        parent = git("rev-parse", "--verify", "--quiet", f"{current}^", check=False)
        before = parent if commit_exists(parent) else ""
    if before:
        output = git("diff", "--name-only", before, current)
    else:
        output = git("ls-tree", "-r", "--name-only", current)
    return [line for line in output.splitlines() if line]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="")
    parser.add_argument("--current", required=True)
    parser.add_argument(
        "--scope",
        choices=("changed", "codingworkspace-notebook", "all"),
        default="changed",
    )
    args = parser.parse_args()

    images = image_directories()
    if args.scope == "all":
        selected = images
    elif args.scope == "codingworkspace-notebook":
        if "codingworkspace-notebook" not in images:
            raise SystemExit("codingworkspace-notebook/Dockerfile is missing")
        selected = ["codingworkspace-notebook"]
    else:
        files = changed_files(args.before, args.current)
        # A changed root-level build input such as install-common.sh affects all
        # images. Workflow/docs-only changes do not silently publish images.
        shared_input_changed = any("/" not in item for item in files)
        selected = images if shared_input_changed else sorted(
            image for image in images if any(item.startswith(f"{image}/") for item in files)
        )

    print(json.dumps(selected, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
