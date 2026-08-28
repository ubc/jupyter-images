#!/usr/bin/env bash
# Produce local SBOM/vulnerability evidence and reject fixable CRITICAL issues.
# Usage: scan-local-image.sh IMAGE REPORT_DIRECTORY
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 IMAGE REPORT_DIRECTORY" >&2
  exit 2
fi

image=$1
report_dir=$2
trivy_version=0.74.0

case "$(uname -s):$(uname -m)" in
  Linux:x86_64)
    trivy_arch=64bit
    trivy_sha256=2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a
    ;;
  Linux:aarch64 | Linux:arm64)
    trivy_arch=ARM64
    trivy_sha256=b94ce1976bbf3c15b514b605ee88be7c6d94a29be2302847ff01cb794d47aad5
    ;;
  *)
    echo "Unsupported Trivy host: $(uname -s)/$(uname -m)" >&2
    exit 1
    ;;
esac

scan_tmp=$(mktemp -d)
cleanup() {
  rm -rf -- "$scan_tmp"
}
trap cleanup EXIT

archive="trivy_${trivy_version}_Linux-${trivy_arch}.tar.gz"
archive_path="${scan_tmp}/${archive}"
trivy="${scan_tmp}/trivy"
curl --fail --location --silent --show-error --retry 3 \
  "https://github.com/aquasecurity/trivy/releases/download/v${trivy_version}/${archive}" \
  --output "$archive_path"
printf '%s  %s\n' "$trivy_sha256" "$archive_path" | sha256sum --check --strict
tar -xzf "$archive_path" -C "$scan_tmp" trivy
test "$("$trivy" --version | sed -n 's/^Version: //p' | head -n1)" = "$trivy_version"

mkdir -p "$report_dir"
rm -f -- \
  "$report_dir/SHA256SUMS" \
  "$report_dir/published-image.txt" \
  "$report_dir/sbom.cdx.json" \
  "$report_dir/trivy-all.json" \
  "$report_dir/trivy-fixable-critical.json"

"$trivy" image \
  --cache-dir "$scan_tmp/cache" \
  --image-src docker \
  --scanners vuln \
  --format cyclonedx \
  --output "$report_dir/sbom.cdx.json" \
  --timeout 20m \
  "$image"

# Retain the complete all-severity, fixed-and-unfixed machine-readable report.
"$trivy" image \
  --cache-dir "$scan_tmp/cache" \
  --image-src docker \
  --scanners vuln \
  --severity UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL \
  --format json \
  --output "$report_dir/trivy-all.json" \
  --timeout 20m \
  "$image"

gate_status=0
"$trivy" image \
  --cache-dir "$scan_tmp/cache" \
  --image-src docker \
  --scanners vuln \
  --severity CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  --format json \
  --output "$report_dir/trivy-fixable-critical.json" \
  --timeout 20m \
  "$image" || gate_status=$?

test -s "$report_dir/sbom.cdx.json"
test -s "$report_dir/trivy-all.json"
test -s "$report_dir/trivy-fixable-critical.json"
(
  cd "$report_dir"
  sha256sum sbom.cdx.json trivy-all.json trivy-fixable-critical.json > SHA256SUMS
)

if [ "$gate_status" -ne 0 ]; then
  echo "Fixable CRITICAL vulnerability policy rejected $image; see $report_dir" >&2
  exit "$gate_status"
fi
echo "Local image security gate passed: $report_dir"
