#!/usr/bin/env bash
# Exercise bundle-only named contexts without requiring either private source
# or a registry credential. The caller must configure a docker-container
# Buildx builder first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PROBE_ROOT="$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/cw-context-probe.XXXXXX")"

cleanup() {
  rm -rf -- "$PROBE_ROOT"
}
trap cleanup EXIT

probe_ref="$(git -C "$ROOT_DIR" rev-parse --verify 'HEAD^{commit}')"
test "${#probe_ref}" -eq 40
test "$(git -C "$ROOT_DIR" rev-parse --show-object-format)" = sha1
test "$(git -C "$ROOT_DIR" rev-parse --is-shallow-repository)" = false

cw_context="$PROBE_ROOT/cw"
gizmo_context="$PROBE_ROOT/gizmo"
exported="$PROBE_ROOT/exported"
python3 "$SCRIPT_DIR/prepare_git_context.py" \
  "$ROOT_DIR" "$probe_ref" "$cw_context"
python3 "$SCRIPT_DIR/prepare_git_context.py" \
  "$ROOT_DIR" "$probe_ref" "$gizmo_context"

docker buildx build \
  --target source-context-transport \
  --build-context "cwsrc=$cw_context" \
  --build-context "gizmosrc=$gizmo_context" \
  --output "type=local,dest=$exported" \
  -f "$ROOT_DIR/codingworkspace-notebook/Dockerfile" \
  "$ROOT_DIR"

cmp "$cw_context/source.bundle" "$exported/contexts/cw/source.bundle"
cmp "$gizmo_context/source.bundle" "$exported/contexts/gizmo/source.bundle"
echo "Bundle-only Buildx source-context transport passed."
