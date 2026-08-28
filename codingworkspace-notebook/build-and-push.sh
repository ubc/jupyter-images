#!/usr/bin/env bash
# Build the codingworkspace-notebook image locally and push it to ECR.
#
# This is the manual alternative to the repo's build.yml Action, used while the
# CodingWorkspace source repo is private and no CI credential is configured.
#
# CodingWorkspace and GizmoApp are installed from LOCAL checkouts (passed to
# buildx as named contexts), so no GitHub credential is needed and the build
# uses exactly what is on disk.
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
#   IMAGE_TAG=<tag>          # default: <ji sha>-cw<cw sha>-gz<gizmo sha>[.dirty]
#   CW_SRC=/path/to/CodingWorkspace   # default: ../CodingWorkspace next to this repo
#   GIZMO_SRC=/path/to/GizmoApp       # default: ../GizmoApp next to this repo
#   PLATFORM=linux/amd64     # target arch; MUST match your EKS nodes
#   AWS_PROFILE=shared       # AWS CLI profile to use (default: shared)
set -euo pipefail

: "${ECR_ACCOUNT:?set ECR_ACCOUNT to your AWS account id}"
: "${AWS_REGION:?set AWS_REGION, e.g. ca-central-1}"
PLATFORM="${PLATFORM:-linux/amd64}"
AWS_PROFILE="${AWS_PROFILE:-shared}"
IMAGE_NAME="codingworkspace-notebook"

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
pinned_cw_ref="$(python3 "${SCRIPT_DIR}/ci/read_pin.py" "${SCRIPT_DIR}/CW_REF")"
pinned_gizmo_ref="$(python3 "${SCRIPT_DIR}/ci/read_pin.py" "${SCRIPT_DIR}/GIZMOAPP_REF")"
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

# Image tag: default to <jupyter-images sha>-cw<cw sha>-gz<gizmo sha>[.dirty].
# Source contexts must be clean; only a modified local jupyter-images tree can
# produce `.dirty`. Override IMAGE_TAG only for an explicitly local workflow.
ji_status="$(git -C "${ROOT_DIR}" status --porcelain --untracked-files=all)"
if [ -z "${IMAGE_TAG:-}" ]; then
  ji_sha="$(git -C "${SCRIPT_DIR}" rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
  cw_sha="${cw_ref:0:7}"
  gizmo_sha="${gizmo_ref:0:7}"
  # Source contexts above must be clean: source labels may never describe
  # uncommitted content. The jupyter-images configuration itself may be dirty
  # for a local test, and that state is visible in the non-deployable tag.
  dirty=""
  if [ -n "$ji_status" ]; then
    dirty=".dirty"
  fi
  IMAGE_TAG="${ji_sha}-cw${cw_sha}-gz${gizmo_sha}${dirty}"
elif [ -n "$ji_status" ] && [[ "$IMAGE_TAG" != *.dirty ]]; then
  echo "A modified jupyter-images tree may only be pushed with a .dirty tag." >&2
  exit 1
fi

REGISTRY="${ECR_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

echo ">> ECR login: ${REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" --profile "${AWS_PROFILE}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo ">> Ensure ECR repo exists: ${IMAGE_NAME}"
aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${IMAGE_NAME}" --region "${AWS_REGION}" --profile "${AWS_PROFILE}" >/dev/null

echo ">> Build (${PLATFORM}) and push: ${IMAGE}"
echo ">> CodingWorkspace source: ${CW_SRC}"
echo ">> GizmoApp source: ${GIZMO_SRC}"
docker buildx build \
  --platform "${PLATFORM}" \
  --build-context "cwsrc=${CW_SRC}" \
  --build-context "gizmosrc=${GIZMO_SRC}" \
  --build-arg "CW_REF=${cw_ref}" \
  --build-arg "GIZMOAPP_REF=${gizmo_ref}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  --push \
  "${ROOT_DIR}"

echo ">> Done. Point z2jh singleuser.image at:"
echo "     name: ${REGISTRY}/${IMAGE_NAME}"
echo "     tag:  ${IMAGE_TAG}"
