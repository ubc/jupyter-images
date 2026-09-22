#!/usr/bin/env bash
# Post-build smoke test for r-notebook. Run as:
#   r-notebook/ci/smoke.sh IMAGE_REF
set -euo pipefail

IMAGE="${1:?usage: smoke.sh IMAGE_REF}"

docker run --rm -i "$IMAGE" bash -s <<'INNER'
set -euo pipefail

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

# jupyter-ai and jupyter-server-documents (its transitive extension) must
# never be present in this image.
pip show jupyter-server-documents >/dev/null 2>&1 && fail "jupyter-server-documents present"
pip show jupyter-ai >/dev/null 2>&1 && fail "jupyter-ai present"

# jupyter labextension list marks a broken/incompatible extension with a
# red " X " marker. The color codes wrap the X in ANSI escapes, so strip
# them before matching or the marker never matches literally.
labext_output=$(jupyter labextension list 2>&1) || fail "jupyter labextension list crashed"
clean_labext=$(printf '%s\n' "$labext_output" | sed -E 's/\x1b\[[0-9;]*m//g')
printf '%s\n' "$clean_labext" | grep -qE " X( |$)" && fail "incompatible labextension detected"

server_ext_output=$(jupyter server extension list 2>&1) || fail "jupyter server extension list crashed"
printf '%s\n' "$server_ext_output" | grep -qi "validation failed" && fail "server extension validation failed"

echo OK
INNER
