#!/usr/bin/env bash
# Build the codingworkspace-notebook image locally and push it to ECR.
#
# This is the manual alternative to the repo's build.yml Action, used while the
# CodingWorkspace source repo is private and no CI credential is configured.
#
# Requirements on the machine you run this from:
#   - Docker with buildx (standard in modern Docker Desktop / docker-ce)
#   - AWS CLI configured with credentials that can push to ECR
#   - Read access to github.com/kevinlb1/CodingWorkspace (for the token below)
#
# IMPORTANT: the Dockerfile installs CodingWorkspace via `pip install git+...@<ref>`,
# which fetches from the REMOTE. Push the branch/tag referenced in the Dockerfile
# to kevinlb1/CodingWorkspace BEFORE running this, or the build will 404.
#
# Usage:
#   ECR_ACCOUNT=123456789012 AWS_REGION=ca-central-1 ./build-and-push.sh
#
# Optional overrides:
#   IMAGE_TAG=trial          # image tag to push (default: trial)
#   CW_TOKEN=ghp_xxx         # read token; default: $(gh auth token)
#   PLATFORM=linux/amd64     # target arch; MUST match your EKS nodes
set -euo pipefail

: "${ECR_ACCOUNT:?set ECR_ACCOUNT to your AWS account id}"
: "${AWS_REGION:?set AWS_REGION, e.g. ca-central-1}"
IMAGE_TAG="${IMAGE_TAG:-trial}"
PLATFORM="${PLATFORM:-linux/amd64}"
IMAGE_NAME="codingworkspace-notebook"

# Read token for the private CodingWorkspace repo. Default to the gh CLI login.
if [ -z "${CW_TOKEN:-}" ]; then
  if command -v gh >/dev/null 2>&1; then
    CW_TOKEN="$(gh auth token)"
  else
    echo "Set CW_TOKEN (a GitHub token with read access to kevinlb1/CodingWorkspace)," >&2
    echo "or install the gh CLI and run 'gh auth login'." >&2
    exit 1
  fi
fi
export CW_TOKEN

REGISTRY="${ECR_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

# Build context is the jupyter-images repo root (parent of this script's dir).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo ">> ECR login: ${REGISTRY}"
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${REGISTRY}"

echo ">> Ensure ECR repo exists: ${IMAGE_NAME}"
aws ecr describe-repositories --repository-names "${IMAGE_NAME}" --region "${AWS_REGION}" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name "${IMAGE_NAME}" --region "${AWS_REGION}" >/dev/null

echo ">> Build (${PLATFORM}) and push: ${IMAGE}"
docker buildx build \
  --platform "${PLATFORM}" \
  --secret id=cw_token,env=CW_TOKEN \
  -f "${SCRIPT_DIR}/Dockerfile" \
  -t "${IMAGE}" \
  --push \
  "${ROOT_DIR}"

echo ">> Done. Point z2jh singleuser.image at:"
echo "     name: ${REGISTRY}/${IMAGE_NAME}"
echo "     tag:  ${IMAGE_TAG}"
