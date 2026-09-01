#!/usr/bin/env python3
"""Extract one reviewed Git blob into a credential-free BuildKit context."""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn


FULL_SHA1 = re.compile(r"[0-9a-f]{40}")
SAFE_PATH_PART = re.compile(r"[A-Za-z0-9._+-]+")


def fail(message: str) -> NoReturn:
    raise SystemExit(message)


def git(*args: str, cwd: Path, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=text,
    )
    return result.stdout.strip() if text else result.stdout


def prepare(
    repository: Path,
    expected_ref: str,
    source_path: str,
    expected_blob: str,
    output: Path,
) -> Path:
    if FULL_SHA1.fullmatch(expected_ref) is None or FULL_SHA1.fullmatch(expected_blob) is None:
        fail("expected commit and blob must be full lowercase SHA-1 identifiers")
    relative = PurePosixPath(source_path)
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} or SAFE_PATH_PART.fullmatch(part) is None for part in relative.parts)
    ):
        fail("source path must be a safe repository-relative path")
    if output.exists() or output.is_symlink():
        fail(f"output context already exists: {output}")

    repository = repository.resolve(strict=True)
    try:
        object_format = git("rev-parse", "--show-object-format", cwd=repository)
        shallow = git("rev-parse", "--is-shallow-repository", cwd=repository)
        status = git("status", "--porcelain", "--untracked-files=all", cwd=repository)
        resolved_ref = git("rev-parse", "--verify", f"{expected_ref}^{{commit}}", cwd=repository)
        tree_entry = git("ls-tree", expected_ref, "--", source_path, cwd=repository)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        fail(f"could not inspect builder source repository: {detail}")
    if object_format != "sha1" or shallow != "false":
        fail("builder source must be a complete SHA-1 repository")
    if status:
        fail("builder source repository contains tracked, staged, or untracked changes")
    if resolved_ref != expected_ref:
        fail("builder source commit did not resolve exactly")
    expected_entry = f"100644 blob {expected_blob}\t{source_path}"
    if tree_entry != expected_entry:
        fail(f"builder source path does not match the reviewed blob: {tree_entry!r}")

    try:
        content = git("cat-file", "blob", expected_blob, cwd=repository, text=False)
        assert isinstance(content, bytes)
        if b"\x00" in content:
            fail("builder source blob must be a text program")
        # Recompute from the exact bytes without relying on a worktree path.
        result = subprocess.run(
            ["git", "hash-object", "--stdin"],
            cwd=repository,
            input=content,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.stdout.decode("ascii").strip() != expected_blob:
            fail("extracted builder source does not match the reviewed blob")
        output.mkdir(mode=0o755, parents=True)
        destination = output / relative.name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(destination, flags, 0o444)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)
        destination.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return destination
    except BaseException:
        shutil.rmtree(output, ignore_errors=True)
        raise


def main(argv: list[str]) -> int:
    if len(argv) != 6:
        fail(
            f"usage: {argv[0]} REPOSITORY EXPECTED_COMMIT SOURCE_PATH "
            "EXPECTED_BLOB OUTPUT_CONTEXT"
        )
    prepare(Path(argv[1]), argv[2], argv[3], argv[4], Path(argv[5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
