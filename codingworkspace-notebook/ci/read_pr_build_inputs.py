#!/usr/bin/env python3
"""Safely read immutable image inputs from an approved PR checkout."""

from __future__ import annotations

import argparse
import os
import re
import stat
from pathlib import Path
from typing import Callable


MAX_INPUT_BYTES = 16 * 1024
SHA1 = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_VALUE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+:/~-]{0,255}")

RUNTIME_KEYS = (
    "BUBBLEWRAP_APT_VERSION",
    "NODE_VERSION",
    "NODE_LINUX_AMD64_SHA256",
    "NODE_LINUX_ARM64_SHA256",
    "OPENCODE_VERSION",
    "OPENCODE_LINUX_AMD64_BASELINE_SHA256",
    "OPENCODE_LINUX_ARM64_SHA256",
)
DEPENDENCY_KEYS = (
    "DEPENDENCY_WHEELHOUSE_LAYER_VERSION",
    "DEPENDENCY_BUILDER_REF",
    "DEPENDENCY_BUILDER_BLOB",
    "DEPENDENCY_WHEEL_INDEX_URL",
)


class InputError(ValueError):
    """A candidate build-input file is unsafe or malformed."""


def read_regular(path: Path) -> str:
    try:
        before = path.lstat()
    except OSError as exc:
        raise InputError(f"build input is unavailable: {path}") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_nlink != 1
        or before.st_size < 1
        or before.st_size > MAX_INPUT_BYTES
    ):
        raise InputError(f"build input must be a bounded single-link file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise InputError(f"build input is unavailable: {path}") from exc
    try:
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or details.st_nlink != 1
            or (details.st_dev, details.st_ino) != (before.st_dev, before.st_ino)
            or details.st_size != before.st_size
            or details.st_mtime_ns != before.st_mtime_ns
            or details.st_ctime_ns != before.st_ctime_ns
        ):
            raise InputError(f"build input changed while being read: {path}")
        chunks: list[bytes] = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                raise InputError(f"build input changed while being read: {path}")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise InputError(f"build input changed while being read: {path}")
        after = os.fstat(descriptor)
        if (
            after.st_nlink != 1
            or (after.st_dev, after.st_ino) != (details.st_dev, details.st_ino)
            or after.st_size != details.st_size
            or after.st_mtime_ns != details.st_mtime_ns
            or after.st_ctime_ns != details.st_ctime_ns
        ):
            raise InputError(f"build input changed while being read: {path}")
        try:
            current = path.lstat()
        except OSError as exc:
            raise InputError(f"build input changed while being read: {path}") from exc
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_nlink != 1
            or (current.st_dev, current.st_ino) != (after.st_dev, after.st_ino)
            or current.st_size != after.st_size
            or current.st_mtime_ns != after.st_mtime_ns
            or current.st_ctime_ns != after.st_ctime_ns
        ):
            raise InputError(f"build input changed while being read: {path}")
        content = b"".join(chunks)
    finally:
        os.close(descriptor)
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputError(f"build input is not UTF-8: {path}") from exc


def read_pin(path: Path) -> str:
    values = [
        line.strip()
        for line in read_regular(path).splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(values) != 1 or SHA1.fullmatch(values[0]) is None:
        raise InputError(f"Git pin must contain one full lowercase SHA-1: {path}")
    return values[0]


def read_assignments(path: Path, expected: tuple[str, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in read_regular(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise InputError(f"malformed build input assignment: {path}")
        key, value = line.split("=", 1)
        if key not in expected or key in values or SAFE_VALUE.fullmatch(value) is None:
            raise InputError(f"unsupported build input assignment: {path}")
        values[key] = value
    if tuple(values) != expected:
        raise InputError(f"build input keys or order differ from the contract: {path}")
    return values


def require(value: str, predicate: Callable[[str], bool], label: str) -> str:
    if not predicate(value):
        raise InputError(f"invalid {label}")
    return value


def load(root: Path) -> dict[str, str]:
    image = root / "codingworkspace-notebook"
    values = {
        "CW_REF": read_pin(image / "CW_REF"),
        "GIZMOAPP_REF": read_pin(image / "GIZMOAPP_REF"),
    }
    values.update(read_assignments(image / "RUNTIME_PINS.env", RUNTIME_KEYS))
    values.update(read_assignments(image / "DEPENDENCY_LAYER.env", DEPENDENCY_KEYS))

    for key in (
        "NODE_LINUX_AMD64_SHA256",
        "NODE_LINUX_ARM64_SHA256",
        "OPENCODE_LINUX_AMD64_BASELINE_SHA256",
        "OPENCODE_LINUX_ARM64_SHA256",
    ):
        require(values[key], lambda item: SHA256.fullmatch(item) is not None, key)
    for key in ("DEPENDENCY_BUILDER_REF", "DEPENDENCY_BUILDER_BLOB"):
        require(values[key], lambda item: SHA1.fullmatch(item) is not None, key)
    require(
        values["DEPENDENCY_WHEEL_INDEX_URL"],
        lambda item: item == "https://pypi.org/simple",
        "dependency wheel index URL",
    )
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    try:
        values = load(args.root)
    except InputError as exc:
        parser.error(str(exc))
    for key, value in values.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
