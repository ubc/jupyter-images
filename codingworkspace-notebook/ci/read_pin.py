#!/usr/bin/env python3
"""Read one immutable Git commit pin without accepting ambiguous syntax."""

from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {Path(sys.argv[0]).name} PIN_FILE", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if path.is_symlink() or not path.is_file():
        print(f"pin must be a regular, non-symlink file: {path}", file=sys.stderr)
        return 1
    values = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(values) != 1 or not re.fullmatch(r"[0-9a-f]{40}", values[0]):
        print(f"{path} must contain exactly one lowercase full Git SHA", file=sys.stderr)
        return 1
    print(values[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
