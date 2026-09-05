#!/usr/bin/env python3
"""Refuse an image whose installed CodingWorkspace differs from its source commit.

The image installs CodingWorkspace with ``pip install`` from a ``git archive`` of
the tracked commit. setuptools reuses a ``build/lib`` tree when the archive
carries one, so a commit that accidentally tracks its build output installs
stale modules while every commit check, label, and smoke that trusts the commit
stays green; CodingWorkspace ``55f2691`` shipped three preview images that way.

Two phases run inside the image build, both as the installing user:

``archive``    before ``pip install``: the pristine archive must carry no
               setuptools output (``build/``, ``dist/``, ``*.egg-info``). An
               in-tree pip build creates ``build/`` legitimately, so this must
               run first.
``installed``  after ``pip install``: every installed package file must equal
               the file in the archive and every archive file must be
               installed, the reported ``__version__`` must end in the
               archive's release serial, and the distribution metadata must
               agree with the module.

Run with ``python -I`` so the interpreter cannot resolve the package from the
working directory instead of the installed copy.
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import importlib.util
import os
import re
import sys
from pathlib import Path

# setuptools outputs that must never be tracked in the source commit.
STALE_ARTIFACT_NAMES = ("build", "dist")
IGNORED_PARTS = frozenset({"__pycache__"})
SERIAL_FILE = "RELEASE_SERIAL"


class VerificationError(Exception):
    """A condition that must fail the image build; the message names it."""


def stale_build_artifacts(source_root: Path) -> list[str]:
    """Return tracked setuptools outputs in the archive, checked two levels deep."""
    found = [name for name in STALE_ARTIFACT_NAMES if os.path.lexists(source_root / name)]
    for pattern in ("*.egg-info", "*/*.egg-info"):
        found.extend(
            sorted(str(path.relative_to(source_root)) for path in source_root.glob(pattern))
        )
    return found


def _tree(root: Path) -> dict[Path, Path]:
    files: dict[Path, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if IGNORED_PARTS.intersection(relative.parts):
            continue
        if path.is_file():
            files[relative] = path
    return files


def tree_problems(source_package: Path, installed_package: Path) -> list[str]:
    """Installed files must equal their source, and every source file must be installed."""
    source = _tree(source_package)
    installed = _tree(installed_package)
    problems = []
    for relative in sorted(set(source) | set(installed), key=str):
        if relative not in source:
            problems.append(f"{relative}: installed but absent from the source commit")
        elif relative not in installed:
            problems.append(f"{relative}: in the source commit but not installed")
        elif source[relative].read_bytes() != installed[relative].read_bytes():
            problems.append(f"{relative}: installed copy differs from the source commit")
    return problems


def version_problems(
    source_package: Path, module_version: str, distribution_version: str
) -> list[str]:
    """The version the UI shows must follow the archive's serial and the metadata."""
    serial_path = source_package / SERIAL_FILE
    try:
        serial = serial_path.read_text(encoding="utf-8").strip()
    except OSError:
        return [f"{SERIAL_FILE}: missing from the source package; the version cannot be checked"]
    if not re.fullmatch(r"[1-9][0-9]*", serial):
        return [f"{SERIAL_FILE}: expected a positive integer, found {serial!r}"]
    problems = []
    if not module_version.endswith("." + serial):
        problems.append(
            f"__version__ is {module_version}; the source release serial is {serial}"
        )
    if distribution_version != module_version:
        problems.append(
            f"distribution metadata records {distribution_version}; "
            f"the module reports {module_version}"
        )
    return problems


def resolve_installed_package(package: str, source_root: Path) -> Path:
    """Locate the installed package and refuse an import that hit the source tree."""
    spec = importlib.util.find_spec(package)
    if spec is None or not spec.submodule_search_locations:
        raise VerificationError(f"{package} is not installed as a package")
    location = Path(next(iter(spec.submodule_search_locations))).resolve()
    resolved_root = source_root.resolve()
    if location == resolved_root or resolved_root in location.parents:
        raise VerificationError(
            f"{package} resolved to the source tree {location}, not the installed copy"
        )
    return location


def check_archive(source_root: Path) -> str:
    if not source_root.is_dir():
        raise VerificationError(f"source archive is not a directory: {source_root}")
    stale = stale_build_artifacts(source_root)
    if stale:
        raise VerificationError(
            "the source commit tracks setuptools output: "
            + ", ".join(stale)
            + ". pip would install those stale modules instead of the commit's "
            "source. Remove them from the repository and ignore build/, dist/, "
            "and *.egg-info/."
        )
    return f"source archive {source_root} carries no setuptools output"


def check_installed(source_root: Path, package: str) -> str:
    source_package = source_root / package
    if not source_package.is_dir():
        raise VerificationError(f"source archive has no package directory {source_package}")
    installed_package = resolve_installed_package(package, source_root)
    module = importlib.import_module(package)
    module_version = str(getattr(module, "__version__", ""))
    distribution_version = importlib.metadata.version(package)
    problems = tree_problems(source_package, installed_package)
    problems.extend(version_problems(source_package, module_version, distribution_version))
    if problems:
        raise VerificationError(
            f"installed {package} does not match the source commit:\n  "
            + "\n  ".join(problems)
        )
    count = len(_tree(installed_package))
    return (
        f"installed {package} {module_version} at {installed_package} matches the "
        f"source commit ({count} files)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    phases = parser.add_subparsers(dest="phase", required=True)
    archive = phases.add_parser("archive", help="before pip install: refuse tracked build output")
    archive.add_argument("--source", required=True, type=Path)
    installed = phases.add_parser(
        "installed", help="after pip install: compare the installed package with the archive"
    )
    installed.add_argument("--source", required=True, type=Path)
    installed.add_argument("--package", default="codingworkspace")
    args = parser.parse_args(argv)
    try:
        if args.phase == "archive":
            message = check_archive(args.source)
        else:
            message = check_installed(args.source, args.package)
    except VerificationError as exc:
        print(f"verify_installed_source: {exc}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
