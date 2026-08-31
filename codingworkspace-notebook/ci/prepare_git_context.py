#!/usr/bin/env python3
"""Create a bundle-only BuildKit context for one exact Git checkout.

BuildKit builders do not consistently transfer a local checkout's ``.git``
directory.  A self-contained Git bundle preserves the reviewed commit object
and its reachable history without exposing checkout configuration or
credentials to the builder.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NoReturn


FULL_SHA1 = re.compile(r"[0-9a-f]{40}")
BUNDLE_NAME = "source.bundle"


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


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


def prepare(repository: Path, expected_ref: str, output: Path) -> Path:
    if FULL_SHA1.fullmatch(expected_ref) is None:
        fail("expected ref must be one full lowercase SHA-1 commit")
    if output.exists() or output.is_symlink():
        fail(f"output context already exists: {output}")

    repository = repository.resolve(strict=True)
    try:
        head = git("rev-parse", "--verify", "HEAD^{commit}", cwd=repository)
        object_format = git("rev-parse", "--show-object-format", cwd=repository)
        shallow = git("rev-parse", "--is-shallow-repository", cwd=repository)
        status = git("status", "--porcelain", "--untracked-files=all", cwd=repository)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        fail(f"could not inspect source repository: {detail}")

    if head != expected_ref:
        fail(f"source HEAD {head} does not match expected ref {expected_ref}")
    if object_format != "sha1":
        fail(f"source repository uses unsupported Git object format: {object_format}")
    if shallow != "false":
        fail("source repository must contain complete reachable history")
    if status:
        fail("source repository contains tracked, staged, or untracked changes")

    output.mkdir(mode=0o700, parents=True)
    bundle = output / BUNDLE_NAME
    try:
        git("bundle", "create", str(bundle), "HEAD", cwd=repository)
        advertised = git("bundle", "list-heads", str(bundle))
        if advertised != f"{expected_ref} HEAD":
            fail(f"source bundle advertises an unexpected ref: {advertised!r}")
        git("bundle", "verify", str(bundle), cwd=repository)
        bundle.chmod(0o444)
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise
    return bundle


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        fail(f"usage: {argv[0]} REPOSITORY EXPECTED_FULL_SHA1 OUTPUT_CONTEXT")
    prepare(Path(argv[1]), argv[2], Path(argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
