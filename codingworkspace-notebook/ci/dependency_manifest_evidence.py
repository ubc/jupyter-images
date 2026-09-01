#!/usr/bin/env python3
"""Validate an exported dependency manifest and emit trusted build metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codingworkspace_dependency_contract import dependency_manifest_metadata  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("layer_version")
    parser.add_argument("--format", choices=("github-env", "text"), default="text")
    arguments = parser.parse_args()
    metadata = dependency_manifest_metadata(
        arguments.manifest.read_bytes(), arguments.layer_version
    )
    if arguments.format == "github-env":
        print(f"DEPENDENCY_RUNTIME_ID={metadata['runtime_id']}")
        print(
            "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256="
            f"{metadata['manifest_sha256']}"
        )
    else:
        print(f"runtime_id={metadata['runtime_id']}")
        print(f"manifest_sha256={metadata['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
