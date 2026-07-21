#!/usr/bin/env bash
# Build the codingworkspace-notebook image locally and push it to ECR.
#
# This is the manual alternative to the repo's build.yml Action, used while the
# CodingWorkspace source repo is private and no CI credential is configured.
#
# CodingWorkspace is installed from a LOCAL checkout (passed to buildx as the
# `cwsrc` build context), so NO GitHub credential is needed and you build exactly
# what is on disk (no need to push the branch first).
#
# Requirements on the machine you run this from:
#   - Docker with buildx (standard in modern Docker Desktop / docker-ce)
#   - AWS CLI configured with credentials that can push to ECR
#   - A local checkout of kevinlb1/CodingWorkspace (see CW_SRC below)
#
# Usage:
#   ECR_ACCOUNT=123456789012 AWS_REGION=ca-central-1 ./build-and-push.sh
#
# Optional overrides:
#   IMAGE_TAG=<tag>          # default: <jupyter-images sha>-cw<codingworkspace sha>[.dirty]
#   CW_SRC=/path/to/CodingWorkspace   # default: ../CodingWorkspace next to this repo
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

# Image tag: default to <jupyter-images sha>-cw<codingworkspace sha>[.dirty] so each
# build is uniquely identified by the exact state of BOTH inputs (the image config in
# this repo AND the app source in CW_SRC). Override IMAGE_TAG to pin a release.
if [ -z "${IMAGE_TAG:-}" ]; then
  ji_sha="$(git -C "${SCRIPT_DIR}" rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
  cw_sha="$(git -C "${CW_SRC}" rev-parse --short=7 HEAD 2>/dev/null || echo nogit)"
  # Dirty only for modified TRACKED files (ignore untracked cruft like .DS_Store).
  dirty=""
  if ! git -C "${SCRIPT_DIR}" diff --quiet HEAD 2>/dev/null \
     || ! git -C "${CW_SRC}" diff --quiet HEAD 2>/dev/null; then
    dirty=".dirty"
  fi
  IMAGE_TAG="${ji_sha}-cw${cw_sha}${dirty}"
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
docker buildx build \
  --platform "${PLATFORM}" \
  --build-context "cwsrc=${CW_SRC}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  --push \
  "${ROOT_DIR}"

echo ">> Done. Point z2jh singleuser.image at:"
echo "     name: ${REGISTRY}/${IMAGE_NAME}"
echo "     tag:  ${IMAGE_TAG}"
