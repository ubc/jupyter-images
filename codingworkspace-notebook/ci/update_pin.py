#!/usr/bin/env python3
"""Replace the sole value in a commented commit-pin file atomically."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(f"usage: {Path(sys.argv[0]).name} PIN_FILE FULL_SHA", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    new_ref = sys.argv[2]
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"pin must be a regular, non-symlink file: {path}")
    if not re.fullmatch(r"[0-9a-f]{40}", new_ref):
        raise SystemExit("replacement pin must be a lowercase full Git SHA")

    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    indexes = [
        index
        for index, line in enumerate(lines)
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(indexes) != 1 or not re.fullmatch(r"[0-9a-f]{40}", lines[indexes[0]].strip()):
        raise SystemExit(f"{path} does not contain exactly one replaceable full SHA")
    newline = "\r\n" if lines[indexes[0]].endswith("\r\n") else "\n"
    lines[indexes[0]] = new_ref + newline

    mode = path.stat().st_mode & 0o777
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
