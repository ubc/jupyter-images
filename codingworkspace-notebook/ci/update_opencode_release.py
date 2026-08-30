#!/usr/bin/env python3
"""Select, verify, and pin a soaked stable OpenCode release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tarfile
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any


ASSETS = {
    "amd64": "opencode-linux-x64-baseline.tar.gz",
    "arm64": "opencode-linux-arm64.tar.gz",
}
VERSION_RE = re.compile(r"^v?([0-9]+\.[0-9]+\.[0-9]+)$")
DIGEST_RE = re.compile(r"^sha256:([0-9a-f]{64})$")


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid stable version: {value}")
    return tuple(int(part) for part in match.group(1).split("."))  # type: ignore[return-value]


def pin_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not re.fullmatch(r"[A-Z0-9_]+=[^\s]+", stripped):
            raise ValueError(f"malformed runtime pin: {stripped}")
        key, value = stripped.split("=", 1)
        if key in values:
            raise ValueError(f"duplicate runtime pin: {key}")
        values[key] = value
    return values


def parse_timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("release timestamp has no timezone")
    return parsed.astimezone(UTC)


def release_metadata(release: dict[str, Any]) -> dict[str, str] | None:
    if release.get("draft") or release.get("prerelease"):
        return None
    match = VERSION_RE.fullmatch(str(release.get("tag_name") or "").strip())
    if not match:
        return None
    version = match.group(1)
    assets = {
        str(asset.get("name") or ""): asset
        for asset in release.get("assets") or []
        if isinstance(asset, dict)
    }
    result = {
        "version": version,
        "published_at": parse_timestamp(release.get("published_at")).isoformat(),
    }
    expected_prefix = f"https://github.com/anomalyco/opencode/releases/download/v{version}/"
    for architecture, name in ASSETS.items():
        asset = assets.get(name)
        if not asset:
            return None
        digest_match = DIGEST_RE.fullmatch(str(asset.get("digest") or ""))
        url = str(asset.get("browser_download_url") or "")
        if not digest_match or url != expected_prefix + name:
            return None
        result[f"{architecture}_url"] = url
        result[f"{architecture}_sha256"] = digest_match.group(1)
    return result


def select_release(
    releases: list[Any],
    current: str,
    *,
    minimum_age_hours: int,
    now: datetime,
) -> dict[str, str] | None:
    cutoff = now.astimezone(UTC) - timedelta(hours=minimum_age_hours)
    candidates = []
    for item in releases:
        if not isinstance(item, dict):
            continue
        try:
            metadata = release_metadata(item)
        except (TypeError, ValueError):
            continue
        if metadata and parse_timestamp(metadata["published_at"]) <= cutoff:
            candidates.append(metadata)
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: version_tuple(item["version"]))
    return selected if version_tuple(selected["version"]) > version_tuple(current) else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(
    path: Path,
    expected_digest: str,
    expected_version: str,
    *,
    execute_contract: bool,
) -> None:
    if path.is_symlink() or not path.is_file() or sha256(path) != expected_digest:
        raise ValueError(f"archive digest mismatch: {path.name}")
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            parts = PurePosixPath(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts:
                raise ValueError(f"archive contains an unsafe path: {member.name}")
            if not (member.isdir() or member.isreg()):
                raise ValueError(f"archive contains a linked or special member: {member.name}")
        binaries = [
            member for member in members if member.isreg() and PurePosixPath(member.name).name == "opencode"
        ]
        if len(binaries) != 1 or binaries[0].size <= 0 or binaries[0].size > 250_000_000:
            raise ValueError("archive must contain exactly one bounded OpenCode binary")
        source = archive.extractfile(binaries[0])
        if source is None:
            raise ValueError("OpenCode binary could not be read")
        if not execute_contract:
            return
        descriptor, temporary = tempfile.mkstemp(prefix="opencode-release-")
        try:
            with os.fdopen(descriptor, "wb") as target:
                while True:
                    chunk = source.read(1_048_576)
                    if not chunk:
                        break
                    target.write(chunk)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            checks = (
                ([temporary, "--version"], expected_version),
                ([temporary, "run", "--help"], "--format"),
                ([temporary, "auth", "login", "--help"], "--provider"),
            )
            for command, required in checks:
                result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
                output = f"{result.stdout}\n{result.stderr}"
                if result.returncode != 0 or required not in output:
                    raise ValueError(f"OpenCode compatibility check failed: {' '.join(command[1:])}")
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def replace_pins(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"([A-Z0-9_]+)=([^\s]+)(\r?\n)?", line)
        if match and match.group(1) in values:
            key = match.group(1)
            if key in seen:
                raise ValueError(f"duplicate runtime pin: {key}")
            seen.add(key)
            lines[index] = f"{key}={values[key]}{match.group(3) or ''}"
    if seen != set(values):
        raise ValueError(f"missing runtime pins: {sorted(set(values) - seen)}")
    mode = stat.S_IMODE(path.stat().st_mode)
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


def write_github_output(path: Path, values: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for key, value in sorted(values.items()):
            if "\n" in value or "\r" in value:
                raise ValueError("GitHub output value contains a newline")
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    select = subparsers.add_parser("select")
    select.add_argument("release_json", type=Path)
    select.add_argument("pins", type=Path)
    select.add_argument("--minimum-age-hours", type=int, default=48)
    select.add_argument("--github-output", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("release_json", type=Path)
    verify.add_argument("pins", type=Path)
    verify.add_argument("--version", required=True)
    verify.add_argument("--amd64", type=Path, required=True)
    verify.add_argument("--arm64", type=Path, required=True)
    arguments = parser.parse_args()

    releases = json.loads(arguments.release_json.read_text(encoding="utf-8"))
    if not isinstance(releases, list):
        raise SystemExit("GitHub release response must be a list")
    current = pin_values(arguments.pins)["OPENCODE_VERSION"]
    if arguments.command == "select":
        selected = select_release(
            releases,
            current,
            minimum_age_hours=arguments.minimum_age_hours,
            now=datetime.now(UTC),
        )
        output = {"update": "false"}
        if selected:
            output = {"update": "true", **selected}
        write_github_output(arguments.github_output, output)
        return 0

    matching = []
    for release in releases:
        if isinstance(release, dict):
            try:
                metadata = release_metadata(release)
            except (TypeError, ValueError):
                continue
            if metadata and metadata["version"] == arguments.version:
                matching.append(metadata)
    if len(matching) != 1:
        raise SystemExit("selected release no longer has unique verified metadata")
    metadata = matching[0]
    verify_archive(
        arguments.amd64,
        metadata["amd64_sha256"],
        arguments.version,
        execute_contract=True,
    )
    verify_archive(
        arguments.arm64,
        metadata["arm64_sha256"],
        arguments.version,
        execute_contract=False,
    )
    replace_pins(
        arguments.pins,
        {
            "OPENCODE_VERSION": arguments.version,
            "OPENCODE_LINUX_AMD64_BASELINE_SHA256": metadata["amd64_sha256"],
            "OPENCODE_LINUX_ARM64_SHA256": metadata["arm64_sha256"],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
