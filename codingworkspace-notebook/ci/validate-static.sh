#!/usr/bin/env bash
# Non-secret checks safe to execute on an untrusted fork pull request.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

CW_REF=$(python3 codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/CW_REF)
GIZMOAPP_REF=$(python3 codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/GIZMOAPP_REF)
printf 'Validated full source pins: CW=%s GizmoApp=%s\n' "$CW_REF" "$GIZMOAPP_REF"

for workflow in .github/workflows/*.yml; do
  if command -v ruby >/dev/null 2>&1; then
    ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), aliases: true)' "$workflow"
  elif python3 -c 'import yaml' >/dev/null 2>&1; then
    python3 -c 'import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding="utf-8"))' "$workflow"
  else
    fail "Ruby or Python PyYAML is required for offline workflow syntax validation"
  fi
  while IFS= read -r use; do
    case "$use" in
      ./* | docker://*) ;;
      *@????????????????????????????????????????) ;;
      *) fail "$workflow contains a mutable or malformed Action reference: $use" ;;
    esac
  done < <(sed -nE 's/^[[:space:]]*-?[[:space:]]*uses:[[:space:]]*([^[:space:]#]+).*/\1/p' "$workflow")
done

if rg -n 'pull_request_target' .github/workflows; then
  fail "pull_request_target must not execute pull-request image code"
fi
rg -q "github.ref == 'refs/heads/main'" .github/workflows/build.yml \
  || fail "trusted publication is not restricted to main"
rg -q "inputs.publish == true" .github/workflows/build.yml \
  || fail "manual publication lacks an explicit publish gate"
rg -q "inputs.promote_codingworkspace == true" .github/workflows/build.yml \
  || fail "CodingWorkspace moving tags lack an explicit promotion gate"
rg -q -- '-f promote_codingworkspace=true' .github/workflows/track-cw.yml \
  || fail "the release tracker does not explicitly authorize promotion"

for script in codingworkspace-notebook/*.sh codingworkspace-notebook/ci/*.sh; do
  bash -n "$script"
done
python3 - <<'PY'
from pathlib import Path

for path in sorted(Path("codingworkspace-notebook").glob("*.py")) + sorted(
    Path("codingworkspace-notebook/ci").glob("*.py")
):
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
python3 codingworkspace-notebook/ci/validate_ci_policy.py

expected_host_fingerprint='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
actual_host_fingerprint=$(ssh-keygen -lf codingworkspace-notebook/ci/github_known_hosts | awk '{print $2}')
test "$actual_host_fingerprint" = "$expected_host_fingerprint" \
  || fail "the pinned GitHub Ed25519 host key has an unexpected fingerprint"

dockerfile=codingworkspace-notebook/Dockerfile
rg -q '^ARG BASE_CONTAINER=.*@sha256:[0-9a-f]{64}$' "$dockerfile" \
  || fail "the base notebook image is not pinned by digest"
rg -q 'hub-5\.5\.0' "$dockerfile" || fail "the base image is not tied to JupyterHub 5.5.0"
rg -q '^jupyter-server-proxy==4\.5\.0' codingworkspace-notebook/proxy-requirements.txt \
  || fail "jupyter-server-proxy is not pinned to 4.5.0"
rg -q -- '--no-deps --only-binary=:all: --require-hashes' "$dockerfile" \
  || fail "the proxy Python runtime is not installed in hash-required binary-only mode"
rg -q 'proxy-requirements\.txt' "$dockerfile" \
  || fail "the hash-locked proxy requirement set is not used"
rg -q 'jupyterhub.*5\.5\.0|5\.5\.0.*jupyterhub' "$dockerfile" \
  || fail "JupyterHub Python 5.5.0 is not asserted by the image build"
rg -q 'JUPYTERHUB_SINGLEUSER_APP=jupyter_server\.serverapp\.ServerApp' "$dockerfile" \
  || fail "the single-user application is not pinned to plain Jupyter Server"
rg -q 'JUPYTER_RUNTIME_DIR=/tmp/codingworkspace-jupyter-runtime' "$dockerfile" \
  || fail "Jupyter runtime state is not fixed outside the retained home"
rg -q 'PYTHONSAFEPATH=1' "$dockerfile" \
  || fail "safe Python startup is not fixed in the image environment"
rg -q 'bubblewrap' "$dockerfile" || fail "Bubblewrap is not installed"
rg -q 'from=gizmosrc' "$dockerfile" || fail "the pinned GizmoApp build context is not used"
rg -q '/usr/local/sbin/codingworkspace-prestop' "$dockerfile" \
  || fail "the image-side preStop helper is not installed"
rg -q 'git .* archive --format=tar' "$dockerfile" \
  || fail "CodingWorkspace must be installed from the pinned Git object, not working-tree contents"
rg -q 'notebook.*7\.6\.1|7\.6\.1.*notebook' "$dockerfile" \
  || fail "Notebook 7.6.1 is not asserted by the image build"
rg -q 'jupyterlab.*4\.6\.2|4\.6\.2.*jupyterlab' "$dockerfile" \
  || fail "JupyterLab 4.6.2 is not asserted by the image build"
if rg -n 'https://opencode\.ai/install|pip install[^#]*jupyter-server-proxy([[:space:]\\]|$)' "$dockerfile"; then
  fail "an unpinned OpenCode or jupyter-server-proxy installer remains"
fi
test ! -e codingworkspace-notebook/opencode.json \
  || fail "the global direct-OpenCode pod-key configuration must be removed"

python3 - <<'PY'
from pathlib import Path
import re

path = Path("codingworkspace-notebook/proxy-requirements.txt")
physical = path.read_text(encoding="utf-8").splitlines()
logical: list[str] = []
buffer = ""
for raw in physical:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        continue
    buffer = f"{buffer} {stripped}".strip()
    if buffer.endswith("\\"):
        buffer = buffer[:-1].rstrip()
        continue
    logical.append(buffer)
    buffer = ""
if buffer:
    raise SystemExit("unterminated continuation in proxy-requirements.txt")

expected = {
    "aiohappyeyeballs": "2.7.1",
    "aiosignal": "1.4.0",
    "attrs": "26.1.0",
    "frozenlist": "1.8.0",
    "multidict": "6.7.1",
    "propcache": "0.5.2",
    "idna": "3.19",
    "yarl": "1.24.5",
    "aiohttp": "3.14.3",
    "jupyter-server-proxy": "4.5.0",
    "simpervisor": "1.0.0",
}
seen: dict[str, str] = {}
for requirement in logical:
    first, *rest = requirement.split()
    if "==" not in first:
        raise SystemExit(f"unversioned proxy requirement: {first}")
    name, version = first.split("==", 1)
    hashes = [item.removeprefix("--hash=sha256:") for item in rest]
    if not hashes or any(not re.fullmatch(r"[0-9a-f]{64}", item) for item in hashes):
        raise SystemExit(f"missing/malformed wheel hash for {name}")
    seen[name] = version
if seen != expected:
    raise SystemExit(f"proxy requirement set mismatch: expected {expected}, got {seen}")
PY

prestop=codingworkspace-notebook/codingworkspace_prestop.py
for required in \
  'EXPECTED_COMMAND = (' \
  'SHUTDOWN_WAIT_SECONDS = 105' \
  'MAX_HOOK_SECONDS = 114.0' \
  'os.pidfd_open' \
  'signal.pidfd_send_signal(pid_descriptor, signal.SIGTERM)' \
  'status=not-running' \
  'find_raw_matches(expected_uid, deadline)' \
  'prestop_target_ambiguous' \
  'prestop_target_restarted' \
  'prestop_hook_deadline_exceeded' \
  'signal.setitimer(signal.ITIMER_REAL, MAX_HOOK_SECONDS)' \
  'prestop_shutdown_checkpoint_missing' \
  'connection.set_progress_handler(' \
  'PRAGMA quick_check'; do
  grep -Fq "$required" "$prestop" || fail "preStop helper is missing $required"
done
if rg -n 'os\.kill\(' "$prestop"; then
  fail "preStop may not use a PID-reuse-prone os.kill fallback"
fi

server_config=codingworkspace-notebook/codingworkspace_server_proxy_config.py
runtime_config=codingworkspace-notebook/codingworkspace_jupyter_runtime.py
grep -Fq 'raw_credential_issued_at_epoch = os.environ.get(' "$server_config" \
  || fail "model credential issuance does not preserve the operator-supplied epoch"
grep -Fq '"CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH", "0"' "$server_config" \
  || fail "missing model credential issuance does not use the unknown-age sentinel"
grep -Fq 'credential_issued_at_epoch != 0' "$runtime_config" \
  || fail "the runtime does not accept the unknown credential-age sentinel"
if grep -Fq 'credential_issued_at_epoch = str(int(time.time()))' "$server_config"; then
  fail "Jupyter restart time must not be misreported as model credential issuance"
fi

config_text=$(cat codingworkspace-notebook/*.py)
for required in \
  request_headers_override \
  X-CodingWorkspace-Proxy-Token \
  CODINGWORKSPACE_PROXY_AUTH_TOKEN \
  CODINGWORKSPACE_ISOLATION_MODE \
  bubblewrap \
  '"CODINGWORKSPACE_OPENCODE_COMMAND": "/usr/local/bin/opencode"' \
  '"CODINGWORKSPACE_ISOLATION_OPENCODE_COMMAND": "/usr/local/bin/opencode"' \
  CODINGWORKSPACE_GITHUB_BACKUP_ENABLED \
  CODINGWORKSPACE_PERSONAL_MODEL_AUTH_ENABLED \
  CODINGWORKSPACE_REMOTE_WORKERS_ENABLED \
  CODINGWORKSPACE_STARTER_REPO_URL \
  /opt/codingworkspace-starters/GizmoApp \
  CODINGWORKSPACE_SQLITE_JOURNAL_MODE \
  CODINGWORKSPACE_SQLITE_SYNCHRONOUS; do
  grep -Fq "$required" <<<"$config_text" || fail "server config is missing $required"
done
for required in \
  '"PYTHONNOUSERSITE": "1"' \
  '"PYTHONSAFEPATH": "1"' \
  '"/opt/conda/bin/python",' \
  '"-I",' \
  '"-P",'; do
  grep -Fq "$required" <<<"$config_text" \
    || fail "the isolated Python child contract is missing $required"
done

for required in \
  'class CodingWorkspaceOnlyAuthorizer' \
  '_allowed = frozenset({("read", "api")})' \
  'c.ServerApp.authorizer_class = CodingWorkspaceOnlyAuthorizer' \
  'c.ServerApp.terminals_enabled = False' \
  '"jupyter_server_proxy": False' \
  '"jupyterlab": False' \
  '"notebook": False'; do
  grep -Fq "$required" <<<"$config_text" \
    || fail "the deny-by-default Jupyter contract is missing $required"
done

echo "Static CodingWorkspace image validation passed."
