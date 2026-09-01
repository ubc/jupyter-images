"""Immutable image contract for the baked dependency wheelhouse."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import stat
import sys
import sysconfig
from pathlib import Path
from typing import Mapping


WHEELHOUSE_SCHEMA = "codingworkspace-dependency-wheelhouse/v1"
WHEELHOUSE_PATH = Path("/opt/codingworkspace-dependency-wheelhouse")
WHEELHOUSE_MANIFEST = WHEELHOUSE_PATH / "manifest.json"
WHEELHOUSE_CONTRACT = Path("/etc/codingworkspace-dependency-wheelhouse.env")
MAX_MANIFEST_BYTES = 1_048_576
MAX_CONTRACT_BYTES = 16_384
RUNTIME_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}")
COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
LAYER_VERSION_RE = re.compile(r"v[1-9][0-9]{0,8}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
WHEEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*\.whl")


def _component(value: object, label: str) -> str:
    if not isinstance(value, str) or COMPONENT_RE.fullmatch(value) is None:
        raise RuntimeError(f"The dependency manifest contains an unsafe {label}")
    return value


def runtime_id_from_python_record(
    python_record: Mapping[str, object], layer_version: str, wheel_set_sha256: str
) -> str:
    """Return the reviewed-layer ID for one exact interpreter architecture."""

    if LAYER_VERSION_RE.fullmatch(layer_version) is None:
        raise RuntimeError("The dependency layer version is invalid")
    _component(python_record.get("implementation"), "implementation")
    abi = _component(python_record.get("abi"), "ABI")
    python_platform = _component(python_record.get("platform"), "platform")
    machine = _component(python_record.get("machine"), "machine")
    if SHA256_RE.fullmatch(wheel_set_sha256) is None:
        raise RuntimeError("The dependency wheel-set hash is invalid")
    runtime_id = (
        f"cw-wh-{layer_version}:{abi}:{python_platform}:{machine}:"
        f"{wheel_set_sha256}"
    )
    if RUNTIME_ID_RE.fullmatch(runtime_id) is None:
        raise RuntimeError("The derived dependency runtime ID is invalid")
    return runtime_id


def _current_python_record() -> dict[str, str]:
    return {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
        "abi": sysconfig.get_config_var("SOABI")
        or sys.implementation.cache_tag
        or "unknown",
        "cacheTag": sys.implementation.cache_tag or "unknown",
        "platform": sysconfig.get_platform(),
        "machine": platform.machine() or "unknown",
    }


def _wheel_set_sha256(manifest: Mapping[str, object]) -> str:
    wheels = manifest.get("wheels")
    if not isinstance(wheels, list) or not wheels:
        raise RuntimeError("The dependency manifest does not list wheels")
    canonical: list[dict[str, object]] = []
    folded_names: set[str] = set()
    for record in wheels:
        if not isinstance(record, dict):
            raise RuntimeError("The dependency manifest has an invalid wheel record")
        filename = record.get("filename")
        digest = record.get("sha256")
        size = record.get("size")
        if (
            not isinstance(filename, str)
            or WHEEL_NAME_RE.fullmatch(filename) is None
            or filename.casefold() in folded_names
            or not isinstance(digest, str)
            or SHA256_RE.fullmatch(digest) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
        ):
            raise RuntimeError("The dependency manifest has an invalid wheel record")
        folded_names.add(filename.casefold())
        canonical.append({"filename": filename, "sha256": digest, "size": size})
    canonical.sort(key=lambda item: str(item["filename"]).casefold())
    encoded = json.dumps(canonical, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def dependency_manifest_metadata(
    raw_manifest: bytes,
    layer_version: str,
    *,
    require_runtime_match: bool = True,
    require_wheel_set_match: bool = True,
    require_current_python: bool = False,
) -> dict[str, str]:
    """Validate the manifest identity and return label/evidence metadata."""

    if len(raw_manifest) > MAX_MANIFEST_BYTES:
        raise RuntimeError("The dependency manifest exceeds its safety limit")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("The dependency manifest is not valid JSON") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != WHEELHOUSE_SCHEMA:
        raise RuntimeError("The dependency manifest schema is invalid")
    python_record = manifest.get("python")
    if not isinstance(python_record, dict):
        raise RuntimeError("The dependency manifest is missing its Python identity")
    for name in ("implementation", "version", "abi", "cacheTag", "platform", "machine"):
        _component(python_record.get(name), f"Python {name}")
    if require_current_python and python_record != _current_python_record():
        raise RuntimeError("The dependency manifest Python identity differs from the runtime")
    wheel_set_sha256 = _wheel_set_sha256(manifest)
    if require_wheel_set_match and manifest.get("wheelSetSha256") != wheel_set_sha256:
        raise RuntimeError("The dependency manifest wheel-set hash is invalid")
    expected_runtime_id = runtime_id_from_python_record(
        python_record, layer_version, wheel_set_sha256
    )
    if require_runtime_match and manifest.get("runtimeId") != expected_runtime_id:
        raise RuntimeError("The dependency manifest runtime ID does not match its Python identity")
    return {
        "layer_version": layer_version,
        "runtime_id": expected_runtime_id,
        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "wheel_set_sha256": wheel_set_sha256,
    }


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def finalize_dependency_manifest(
    path: Path, layer_version: str, *, required_uid: int = 0
) -> dict[str, str]:
    """Atomically add content-derived identity to one freshly built manifest.

    The reviewed builder accepts an explicit runtime ID before it downloads
    wheels. The image invokes it once with a non-release probe ID, then this
    root-only build step binds the final ID to the exact downloaded wheel set.
    """

    path = Path(os.path.abspath(path))
    parent = path.parent
    if os.geteuid() != required_uid:
        raise RuntimeError("Dependency manifest finalization requires the artifact owner")
    if path.name != "manifest.json":
        raise RuntimeError("The dependency manifest finalization target is invalid")
    parent_details = parent.lstat()
    path_details = path.lstat()
    if (
        stat.S_ISLNK(parent_details.st_mode)
        or not stat.S_ISDIR(parent_details.st_mode)
        or parent_details.st_uid != required_uid
        or stat.S_IMODE(parent_details.st_mode) != 0o555
        or stat.S_ISLNK(path_details.st_mode)
        or not stat.S_ISREG(path_details.st_mode)
        or path_details.st_uid != required_uid
        or path_details.st_nlink != 1
        or stat.S_IMODE(path_details.st_mode) != 0o444
    ):
        raise RuntimeError("The dependency manifest cannot be safely finalized")
    raw_manifest = path.read_bytes()
    metadata = dependency_manifest_metadata(
        raw_manifest,
        layer_version,
        require_runtime_match=False,
        require_wheel_set_match=False,
        require_current_python=True,
    )
    manifest = json.loads(raw_manifest)
    expected_probe_id = f"codingworkspace-wheelhouse-probe-{layer_version}"
    existing_runtime_id = manifest.get("runtimeId")
    existing_wheel_set = manifest.get("wheelSetSha256")
    if (
        existing_runtime_id == metadata["runtime_id"]
        and existing_wheel_set == metadata["wheel_set_sha256"]
    ):
        return dependency_manifest_metadata(
            raw_manifest, layer_version, require_current_python=True
        )
    if existing_runtime_id != expected_probe_id or existing_wheel_set is not None:
        raise RuntimeError("The dependency manifest is not in the reviewed probe state")
    original_fields = dict(manifest)
    original_fields.pop("runtimeId")
    manifest["runtimeId"] = metadata["runtime_id"]
    manifest["wheelSetSha256"] = metadata["wheel_set_sha256"]
    finalized = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = parent / ".manifest.json.finalizing"
    descriptor = -1
    temporary_created = False
    parent.chmod(0o755)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        temporary_created = True
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(finalized)
            handle.flush()
            os.fsync(handle.fileno())
        os.close(descriptor)
        descriptor = -1
        temporary.chmod(0o444)
        os.replace(temporary, path)
        temporary_created = False
        _fsync_directory(parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_created:
            temporary.unlink()
        if path.exists():
            path.chmod(0o444)
        parent.chmod(0o555)
        _fsync_directory(parent)
    finalized_manifest = json.loads(path.read_bytes())
    finalized_fields = dict(finalized_manifest)
    finalized_fields.pop("runtimeId")
    if finalized_fields.pop("wheelSetSha256", None) != metadata["wheel_set_sha256"]:
        raise RuntimeError("The finalized dependency manifest lost its wheel-set identity")
    if finalized_fields != original_fields:
        raise RuntimeError("Dependency manifest finalization changed reviewed builder fields")
    return dependency_manifest_metadata(
        path.read_bytes(), layer_version, require_current_python=True
    )


def _read_immutable_file(path: Path, *, required_uid: int, maximum_bytes: int) -> bytes:
    try:
        named = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"The baked dependency artifact is unavailable: {path}") from exc
    if (
        not stat.S_ISREG(named.st_mode)
        or named.st_uid != required_uid
        or named.st_nlink != 1
        or stat.S_IMODE(named.st_mode) != 0o444
        or named.st_size > maximum_bytes
    ):
        raise RuntimeError(f"The baked dependency artifact is unsafe: {path}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != named.st_dev
            or opened.st_ino != named.st_ino
            or opened.st_uid != required_uid
            or opened.st_nlink != 1
            or stat.S_IMODE(opened.st_mode) != 0o444
        ):
            raise RuntimeError(f"The baked dependency artifact changed while opening: {path}")
        chunks: list[bytes] = []
        remaining = maximum_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1_048_576, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        if len(content) > maximum_bytes:
            raise RuntimeError(f"The baked dependency artifact exceeds its safety limit: {path}")
        opened_after = os.fstat(descriptor)
        if (
            opened_after.st_dev != opened.st_dev
            or opened_after.st_ino != opened.st_ino
            or opened_after.st_size != opened.st_size
        ):
            raise RuntimeError(f"The baked dependency artifact changed while reading: {path}")
        return content
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _contract_values(raw_contract: bytes) -> dict[str, str]:
    try:
        text = raw_contract.decode("ascii")
    except UnicodeError as exc:
        raise RuntimeError("The dependency contract is not ASCII") from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line or re.fullmatch(r"[A-Z0-9_]+=[A-Za-z0-9._:+-]+", line) is None:
            raise RuntimeError("The dependency contract is malformed")
        name, value = line.split("=", 1)
        if name in values:
            raise RuntimeError("The dependency contract contains a duplicate")
        values[name] = value
    expected_names = {
        "DEPENDENCY_WHEELHOUSE_LAYER_VERSION",
        "DEPENDENCY_RUNTIME_ID",
        "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256",
    }
    if set(values) != expected_names:
        raise RuntimeError("The dependency contract contains unexpected fields")
    return values


def image_dependency_environment(
    *,
    wheelhouse: Path = WHEELHOUSE_PATH,
    contract: Path = WHEELHOUSE_CONTRACT,
    required_uid: int = 0,
) -> dict[str, str]:
    """Validate the sealed image artifact and return fixed child settings."""

    try:
        directory = wheelhouse.lstat()
    except OSError as exc:
        raise RuntimeError("The baked dependency wheelhouse is unavailable") from exc
    if (
        not wheelhouse.is_absolute()
        or stat.S_ISLNK(directory.st_mode)
        or not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != required_uid
        or stat.S_IMODE(directory.st_mode) != 0o555
        or wheelhouse.resolve(strict=True) != wheelhouse
    ):
        raise RuntimeError("The baked dependency wheelhouse is unsafe")

    raw_contract = _read_immutable_file(
        contract, required_uid=required_uid, maximum_bytes=MAX_CONTRACT_BYTES
    )
    values = _contract_values(raw_contract)
    layer_version = values["DEPENDENCY_WHEELHOUSE_LAYER_VERSION"]
    if LAYER_VERSION_RE.fullmatch(layer_version) is None:
        raise RuntimeError("The dependency contract layer version is invalid")
    raw_manifest = _read_immutable_file(
        wheelhouse / "manifest.json",
        required_uid=required_uid,
        maximum_bytes=MAX_MANIFEST_BYTES,
    )
    metadata = dependency_manifest_metadata(
        raw_manifest, layer_version, require_current_python=True
    )
    if values["DEPENDENCY_RUNTIME_ID"] != metadata["runtime_id"]:
        raise RuntimeError("The configured dependency runtime ID differs from the manifest")
    if values["DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256"] != metadata["manifest_sha256"]:
        raise RuntimeError("The configured dependency manifest hash differs from the artifact")
    return {
        "CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE": str(wheelhouse),
        "CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE_MODE": "prefer",
        "CODINGWORKSPACE_DEPENDENCY_RUNTIME_ID": metadata["runtime_id"],
    }
