#!/usr/bin/env bash
# Build the codingworkspace-notebook image locally and push it to ECR.
#
# This is the manual alternative to the repo's build.yml Action, used while the
# CodingWorkspace source repo is private and no CI credential is configured.
#
# CodingWorkspace and GizmoApp are installed from LOCAL checkouts converted to
# bundle-only Buildx contexts, so no GitHub credential is needed and the build
# uses exactly the reviewed Git commits on disk.
#
# Requirements on the machine you run this from:
#   - Docker with buildx (standard in modern Docker Desktop / docker-ce)
#   - AWS CLI configured with credentials that can push to ECR
#   - Local checkouts of kevinlb1/CodingWorkspace and kevinlb1/GizmoApp
#
# Usage:
#   ECR_ACCOUNT=123456789012 AWS_REGION=ca-central-1 ./build-and-push.sh
#
# Optional overrides:
#   IMAGE_TAG=<tag>          # default: <ji sha>-cw<cw sha>-gz<gizmo sha>
#   CW_SRC=/path/to/CodingWorkspace   # default: ../CodingWorkspace next to this repo
#   GIZMO_SRC=/path/to/GizmoApp       # default: ../GizmoApp next to this repo
#   PLATFORM=linux/amd64     # target arch; MUST match your EKS nodes
#   AWS_PROFILE=shared       # AWS CLI profile to use (default: shared)
#   SECURITY_REPORT_DIR=/path/to/evidence
set -euo pipefail

: "${ECR_ACCOUNT:?set ECR_ACCOUNT to your AWS account id}"
: "${AWS_REGION:?set AWS_REGION, e.g. ca-central-1}"
PLATFORM="${PLATFORM:-linux/amd64}"
AWS_PROFILE="${AWS_PROFILE:-shared}"
IMAGE_NAME="codingworkspace-notebook"
if [ "$PLATFORM" != "linux/amd64" ]; then
  echo "This reviewed CodingWorkspace image release is pinned to linux/amd64." >&2
  exit 1
fi

# Build context is the jupyter-images repo root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Local CodingWorkspace checkout to install from. Default: sibling of this repo.
CW_SRC="${CW_SRC:-${ROOT_DIR}/../CodingWorkspace}"
if [ ! -f "${CW_SRC}/pyproject.toml" ]; then
  echo "CodingWorkspace source not found at: ${CW_SRC}" >&2
  echo "Set CW_SRC=/path/to/CodingWorkspace (a checkout containing pyproject.toml)." >&2
  exit 1
fi
CW_SRC="$(cd "${CW_SRC}" && pwd)"

# The canonical starter is a separate, pinned source input rather than a
# network clone performed inside Docker. Both local source contexts must be
# clean exact commits matching their reviewed pin files.
GIZMO_SRC="${GIZMO_SRC:-${ROOT_DIR}/../GizmoApp}"
if [ ! -d "${GIZMO_SRC}/.git" ]; then
  echo "GizmoApp source not found at: ${GIZMO_SRC}" >&2
  echo "Set GIZMO_SRC=/path/to/GizmoApp (a Git checkout)." >&2
  exit 1
fi
GIZMO_SRC="$(cd "${GIZMO_SRC}" && pwd)"

cw_ref="$(git -C "${CW_SRC}" rev-parse HEAD)"
gizmo_ref="$(git -C "${GIZMO_SRC}" rev-parse HEAD)"
case "$cw_ref" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
  *) echo "CodingWorkspace checkout has no valid Git commit." >&2; exit 1 ;;
esac
case "$gizmo_ref" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
  *) echo "GizmoApp checkout has no valid Git commit." >&2; exit 1 ;;
esac
if [ "${#cw_ref}" -ne 40 ] || [ "${#gizmo_ref}" -ne 40 ]; then
  echo "Both source checkouts must use full 40-character SHA-1 commits." >&2
  exit 1
fi
if [ "$(git -C "${GIZMO_SRC}" rev-parse --show-object-format)" != sha1 ]; then
  echo "GizmoApp must use the supported SHA-1 Git object format." >&2
  exit 1
fi

# A published image must be reconstructible from the commits embedded in its
# tag and labels. Refuse staged or unstaged tracked changes in every input;
# source-context checks below retain the existing stricter untracked-file rule.
tracked_dirty=0
check_tracked_clean() {
  local name=$1
  local path=$2
  if ! git -C "$path" diff --quiet HEAD --; then
    echo "$name contains tracked changes and cannot be published." >&2
    tracked_dirty=1
  fi
}
check_tracked_clean jupyter-images "$ROOT_DIR"
check_tracked_clean CodingWorkspace "$CW_SRC"
check_tracked_clean GizmoApp "$GIZMO_SRC"
if [ "$tracked_dirty" -ne 0 ]; then
  echo "Commit or revert tracked changes before running build-and-push.sh." >&2
  exit 1
fi
pinned_cw_ref="$(python3 "${SCRIPT_DIR}/ci/read_pin.py" "${SCRIPT_DIR}/CW_REF")"
pinned_gizmo_ref="$(python3 "${SCRIPT_DIR}/ci/read_pin.py" "${SCRIPT_DIR}/GIZMOAPP_REF")"
. "${SCRIPT_DIR}/RUNTIME_PINS.env"
. "${SCRIPT_DIR}/DEPENDENCY_LAYER.env"
if [ "$cw_ref" != "$pinned_cw_ref" ]; then
  echo "CodingWorkspace HEAD ($cw_ref) does not match CW_REF ($pinned_cw_ref)." >&2
  echo "Use the pinned checkout, or deliberately update CW_REF before a test build." >&2
  exit 1
fi
if [ "$gizmo_ref" != "$pinned_gizmo_ref" ]; then
  echo "GizmoApp HEAD ($gizmo_ref) does not match GIZMOAPP_REF ($pinned_gizmo_ref)." >&2
  echo "Use the pinned checkout, or deliberately update GIZMOAPP_REF before a test build." >&2
  exit 1
fi
if [ -n "$(git -C "${CW_SRC}" status --porcelain --untracked-files=all)" ]; then
  echo "CodingWorkspace source contains tracked, staged, or untracked changes." >&2
  echo "Commit the exact source and update CW_REF before building." >&2
  exit 1
fi
if [ -n "$(git -C "${GIZMO_SRC}" status --porcelain --untracked-files=all)" ]; then
  echo "GizmoApp source contains tracked, staged, or untracked changes." >&2
  echo "Commit the exact source and update GIZMOAPP_REF before building." >&2
  exit 1
fi

# Use builder-independent, bundle-only named contexts. BuildKit may omit .git
# from local directory contexts, while the bundle preserves the exact reviewed
# commit object and history without transferring checkout credentials/config.
SOURCE_CONTEXT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/codingworkspace-source-context.XXXXXX")"
cleanup_source_contexts() {
  rm -rf -- "$SOURCE_CONTEXT_ROOT"
}
trap cleanup_source_contexts EXIT
CW_CONTEXT="${SOURCE_CONTEXT_ROOT}/cw"
GIZMO_CONTEXT="${SOURCE_CONTEXT_ROOT}/gizmo"
CW_BUILDER_CONTEXT="${SOURCE_CONTEXT_ROOT}/dependency-builder"
python3 "${SCRIPT_DIR}/ci/prepare_git_context.py" "$CW_SRC" "$cw_ref" "$CW_CONTEXT"
python3 "${SCRIPT_DIR}/ci/prepare_git_context.py" "$GIZMO_SRC" "$gizmo_ref" "$GIZMO_CONTEXT"
python3 "${SCRIPT_DIR}/ci/prepare_git_blob_context.py" \
  "$CW_SRC" "$DEPENDENCY_BUILDER_REF" scripts/build_dependency_wheelhouse.py \
  "$DEPENDENCY_BUILDER_BLOB" "$CW_BUILDER_CONTEXT"

DEPENDENCY_EXPORT="${SOURCE_CONTEXT_ROOT}/dependency-export"
DEPENDENCY_METADATA="${SOURCE_CONTEXT_ROOT}/dependency-metadata.env"
echo ">> Build exact linux/amd64 dependency metadata"
docker buildx build \
  --platform linux/amd64 \
  --target dependency-wheelhouse-evidence \
  --build-context "cwsrc=${CW_CONTEXT}" \
  --build-context "gizmosrc=${GIZMO_CONTEXT}" \
  --build-context "cwbuildersrc=${CW_BUILDER_CONTEXT}" \
  --build-arg "CW_REF=${cw_ref}" \
  --build-arg "GIZMOAPP_REF=${gizmo_ref}" \
  --build-arg "OPENCODE_VERSION=${OPENCODE_VERSION}" \
  --build-arg "DEPENDENCY_WHEELHOUSE_LAYER_VERSION=${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" \
  --build-arg "DEPENDENCY_BUILDER_REF=${DEPENDENCY_BUILDER_REF}" \
  --build-arg "DEPENDENCY_BUILDER_BLOB=${DEPENDENCY_BUILDER_BLOB}" \
  --build-arg "DEPENDENCY_WHEEL_INDEX_URL=${DEPENDENCY_WHEEL_INDEX_URL}" \
  --output "type=local,dest=${DEPENDENCY_EXPORT}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  "${ROOT_DIR}"
python3 "${SCRIPT_DIR}/ci/dependency_manifest_evidence.py" \
  "${DEPENDENCY_EXPORT}/manifest.json" "$DEPENDENCY_WHEELHOUSE_LAYER_VERSION" \
  --format github-env > "$DEPENDENCY_METADATA"
. "$DEPENDENCY_METADATA"

# Image tag: default to <jupyter-images sha>-cw<cw sha>-gz<gizmo sha>.
if [ -z "${IMAGE_TAG:-}" ]; then
  ji_sha="$(git -C "${SCRIPT_DIR}" rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
  cw_sha="${cw_ref:0:7}"
  gizmo_sha="${gizmo_ref:0:7}"
  IMAGE_TAG="${ji_sha}-cw${cw_sha}-gz${gizmo_sha}"
fi

REGISTRY="${ECR_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"
SECURITY_REPORT_DIR="${SECURITY_REPORT_DIR:-${TMPDIR:-/tmp}/codingworkspace-image-evidence/${IMAGE_TAG}}"

echo ">> Build and load (${PLATFORM}): ${IMAGE}"
echo ">> CodingWorkspace source: ${CW_SRC}"
echo ">> GizmoApp source: ${GIZMO_SRC}"
docker buildx build \
  --platform "${PLATFORM}" \
  --build-context "cwsrc=${CW_CONTEXT}" \
  --build-context "gizmosrc=${GIZMO_CONTEXT}" \
  --build-context "cwbuildersrc=${CW_BUILDER_CONTEXT}" \
  --build-arg "CW_REF=${cw_ref}" \
  --build-arg "GIZMOAPP_REF=${gizmo_ref}" \
  --build-arg "OPENCODE_VERSION=${OPENCODE_VERSION}" \
  --build-arg "DEPENDENCY_WHEELHOUSE_LAYER_VERSION=${DEPENDENCY_WHEELHOUSE_LAYER_VERSION}" \
  --build-arg "DEPENDENCY_BUILDER_REF=${DEPENDENCY_BUILDER_REF}" \
  --build-arg "DEPENDENCY_BUILDER_BLOB=${DEPENDENCY_BUILDER_BLOB}" \
  --build-arg "DEPENDENCY_WHEEL_INDEX_URL=${DEPENDENCY_WHEEL_INDEX_URL}" \
  --build-arg "DEPENDENCY_RUNTIME_ID=${DEPENDENCY_RUNTIME_ID}" \
  --build-arg "DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256=${DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  --load \
  "${ROOT_DIR}"

echo ">> Run the non-root image contract smoke"
"${SCRIPT_DIR}/ci/smoke-image.sh" contract "$IMAGE" "$cw_ref" "$gizmo_ref"

echo ">> Generate SBOM and vulnerability evidence before publication"
env \
  -u AWS_ACCESS_KEY_ID \
  -u AWS_SECRET_ACCESS_KEY \
  -u AWS_SESSION_TOKEN \
  -u AWS_SECURITY_TOKEN \
  "${SCRIPT_DIR}/ci/scan-local-image.sh" "$IMAGE" "$SECURITY_REPORT_DIR"

echo ">> Extract exact loaded-image dependency evidence"
dependency_container=$(docker create "$IMAGE")
cleanup_dependency_container() {
  docker rm -f "$dependency_container" >/dev/null 2>&1 || true
}
trap 'cleanup_dependency_container; cleanup_source_contexts' EXIT
docker cp \
  "$dependency_container:/opt/codingworkspace-dependency-wheelhouse/manifest.json" \
  "$SECURITY_REPORT_DIR/codingworkspace-dependency-wheelhouse-manifest.json"
docker cp \
  "$dependency_container:/etc/codingworkspace-dependency-wheelhouse.env" \
  "$SECURITY_REPORT_DIR/codingworkspace-dependency-wheelhouse-identity.env"
cleanup_dependency_container
trap cleanup_source_contexts EXIT
cmp "${DEPENDENCY_EXPORT}/manifest.json" \
  "$SECURITY_REPORT_DIR/codingworkspace-dependency-wheelhouse-manifest.json"
test "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE")" = linux/amd64
{
  printf 'image_platform=linux/amd64\n'
  printf 'dependency_builder_commit=%s\n' "$DEPENDENCY_BUILDER_REF"
  printf 'dependency_builder_blob=%s\n' "$DEPENDENCY_BUILDER_BLOB"
  printf 'dependency_wheel_index_url=%s\n' "$DEPENDENCY_WHEEL_INDEX_URL"
  printf 'dependency_layer_version=%s\n' "$DEPENDENCY_WHEELHOUSE_LAYER_VERSION"
  printf 'dependency_runtime_id=%s\n' "$DEPENDENCY_RUNTIME_ID"
  printf 'dependency_manifest_sha256=%s\n' "$DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256"
} > "$SECURITY_REPORT_DIR/codingworkspace-dependency-wheelhouse-release.txt"
(
  cd "$SECURITY_REPORT_DIR"
  sha256sum \
    codingworkspace-dependency-wheelhouse-manifest.json \
    codingworkspace-dependency-wheelhouse-identity.env \
    codingworkspace-dependency-wheelhouse-release.txt >> SHA256SUMS
)

echo ">> ECR login: ${REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo ">> Ensure ECR repo exists: ${IMAGE_NAME}"
aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${IMAGE_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}" >/dev/null

echo ">> Push tested candidate: ${IMAGE}"
docker push "$IMAGE"

image_digest=""
for attempt in $(seq 1 12); do
  manifest_json=$(docker buildx imagetools inspect \
    "${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}" \
    --format '{{json .Manifest}}' 2>/dev/null || true)
  image_digest=$(python3 -c \
    'import json, sys; value = json.load(sys.stdin).get("digest", ""); print(value if isinstance(value, str) else "")' \
    <<<"${manifest_json:-}" 2>/dev/null || true)
  [[ "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]] && break
  sleep 5
done
if ! [[ "$image_digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  echo "The registry did not return the pushed image digest: $image_digest" >&2
  exit 1
fi
printf '%s@%s\n' "${REGISTRY}/${IMAGE_NAME}" "$image_digest" \
  | tee "$SECURITY_REPORT_DIR/published-image.txt"
(
  cd "$SECURITY_REPORT_DIR"
  sha256sum published-image.txt >> SHA256SUMS
)

echo ">> Done. Point z2jh singleuser.image at:"
echo "     name: ${REGISTRY}/${IMAGE_NAME}"
echo "     tag:  ${IMAGE_TAG}"
echo "     digest: ${image_digest}"
echo ">> Evidence: ${SECURITY_REPORT_DIR}"
