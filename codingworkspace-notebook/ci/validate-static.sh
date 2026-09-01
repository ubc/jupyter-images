#!/usr/bin/env bash
# Non-secret checks safe to execute on an untrusted fork pull request.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

command -v grep >/dev/null 2>&1 || fail "grep is required for static validation"

# A forbidden-pattern check must distinguish "no matches" (grep status 1)
# from an execution or I/O failure.  In particular, never spell a security
# guard as `if grep ...; then fail`, because a missing/broken scanner would
# otherwise look exactly like a clean result.
reject_ere_matches() {
  local message=$1
  local pattern=$2
  shift 2
  local output status
  if output=$(grep -R -En -- "$pattern" "$@" 2>&1); then
    printf '%s\n' "$output" >&2
    fail "$message"
  else
    status=$?
    case "$status" in
      1) return 0 ;;
      *)
        printf '%s\n' "$output" >&2
        fail "could not evaluate forbidden-pattern check: $message"
        ;;
    esac
  fi
}

CW_REF=$(python3 codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/CW_REF)
GIZMOAPP_REF=$(python3 codingworkspace-notebook/ci/read_pin.py codingworkspace-notebook/GIZMOAPP_REF)
printf 'Validated full source pins: CW=%s GizmoApp=%s\n' "$CW_REF" "$GIZMOAPP_REF"
test "$CW_REF" = 3f7d93d4d1fc72c809c24df4757ecc91cdf4b415 \
  || fail "the image-source integration must retain the accepted CodingWorkspace release pin"
test "$GIZMOAPP_REF" = 2d9cad4af9decfe5336306f0e4afc529082a37fb \
  || fail "the wheelhouse image must use the reviewed offline-installer GizmoApp commit"
. codingworkspace-notebook/DEPENDENCY_LAYER.env
test "$DEPENDENCY_WHEELHOUSE_LAYER_VERSION" = v1 \
  || fail "the dependency layer version is not the reviewed value"
test "$DEPENDENCY_BUILDER_REF" = 83d4956dc2d091309daaf7be32c350c96d8b2aa2 \
  || fail "the dependency builder commit is not the reviewed source"
test "$DEPENDENCY_BUILDER_BLOB" = 7a30db859d3451293f9193b75175801b7ed49ec5 \
  || fail "the dependency builder blob is not the reviewed program"
test "$DEPENDENCY_WHEEL_INDEX_URL" = https://pypi.org/simple \
  || fail "the dependency wheel source is not the reviewed public index"

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

reject_ere_matches \
  "pull_request_target must not execute pull-request image code" \
  'pull_request_target' .github/workflows
grep -Eq "github.ref == 'refs/heads/main'" .github/workflows/build.yml \
  || fail "trusted publication is not restricted to main"
grep -Eq "inputs.publish == true" .github/workflows/build.yml \
  || fail "manual publication lacks an explicit publish gate"
grep -Eq "inputs.promote_codingworkspace == true" .github/workflows/build.yml \
  || fail "CodingWorkspace moving tags lack an explicit promotion gate"
grep -Eq -- '-f promote_codingworkspace=true' .github/workflows/track-cw.yml \
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
python3 codingworkspace-notebook/ci/test_prepare_git_context.py -v
python3 codingworkspace-notebook/ci/test_select_cw_build_ref.py -v
python3 codingworkspace-notebook/ci/test_verify_cw_candidate.py -v
python3 codingworkspace-notebook/ci/test_prepare_git_blob_context.py -v
python3 codingworkspace-notebook/ci/test_dependency_contract.py -v
python3 codingworkspace-notebook/ci/test_update_opencode_release.py -v

expected_host_fingerprint='SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU'
actual_host_fingerprint=$(ssh-keygen -lf codingworkspace-notebook/ci/github_known_hosts | awk '{print $2}')
test "$actual_host_fingerprint" = "$expected_host_fingerprint" \
  || fail "the pinned GitHub Ed25519 host key has an unexpected fingerprint"

dockerfile=codingworkspace-notebook/Dockerfile
grep -Eq '^ARG BASE_CONTAINER=.*@sha256:[0-9a-f]{64}$' "$dockerfile" \
  || fail "the base notebook image is not pinned by digest"
grep -Eq 'hub-5\.5\.0' "$dockerfile" || fail "the base image is not tied to JupyterHub 5.5.0"
grep -Eq '^jupyter-server-proxy==4\.5\.0' codingworkspace-notebook/proxy-requirements.txt \
  || fail "jupyter-server-proxy is not pinned to 4.5.0"
grep -Eq -- '--no-deps --only-binary=:all: --require-hashes' "$dockerfile" \
  || fail "the proxy Python runtime is not installed in hash-required binary-only mode"
grep -Eq 'proxy-requirements\.txt' "$dockerfile" \
  || fail "the hash-locked proxy requirement set is not used"
grep -Eq 'jupyterhub.*5\.5\.0|5\.5\.0.*jupyterhub' "$dockerfile" \
  || fail "JupyterHub Python 5.5.0 is not asserted by the image build"
grep -Eq 'JUPYTERHUB_SINGLEUSER_APP=jupyter_server\.serverapp\.ServerApp' "$dockerfile" \
  || fail "the single-user application is not pinned to plain Jupyter Server"
grep -Eq 'JUPYTER_RUNTIME_DIR=/tmp/codingworkspace-jupyter-runtime' "$dockerfile" \
  || fail "Jupyter runtime state is not fixed outside the retained home"
grep -Eq 'PYTHONSAFEPATH=1' "$dockerfile" \
  || fail "safe Python startup is not fixed in the image environment"
grep -Eq 'org\.codingworkspace\.opencode-version="\$\{OPENCODE_VERSION\}"' "$dockerfile" \
  || fail "the image label does not use the reviewed OpenCode pin"
grep -Eq '/etc/codingworkspace-runtime-pins\.env' "$dockerfile" \
  || fail "the reviewed runtime pin manifest is not retained in the image"
grep -Eq 'CODINGWORKSPACE_OPENCODE_RUNTIME_VERSION' codingworkspace-notebook/codingworkspace_server_proxy_config.py \
  || fail "the pod does not publish its baked OpenCode runtime version"
grep -Eq 'CODINGWORKSPACE_COURSE_CONTROL_URL' codingworkspace-notebook/codingworkspace_server_proxy_config.py \
  || fail "the pod cannot connect to central course control"
reject_ere_matches \
  "the image may not default the Hub-owned pod termination grace assertion" \
  'CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS' "$dockerfile"
grep -Eq 'bubblewrap' "$dockerfile" || fail "Bubblewrap is not installed"
grep -Fq 'test "${TARGETARCH}" = "amd64"' "$dockerfile" \
  || fail "the reviewed image is not pinned to amd64"
grep -Eq 'from=gizmosrc' "$dockerfile" || fail "the pinned GizmoApp build context is not used"
grep -Eq 'from=cwbuildersrc' "$dockerfile" \
  || fail "the reviewed dependency builder context is not used"
grep -Eq 'git bundle list-heads /cwsrc/source\.bundle' "$dockerfile" \
  || fail "CodingWorkspace is not verified from its bundle-only build context"
grep -Eq 'git bundle list-heads /gizmosrc/source\.bundle' "$dockerfile" \
  || fail "GizmoApp is not verified from its bundle-only build context"
grep -Fq 'git hash-object /cwbuildersrc/build_dependency_wheelhouse.py' "$dockerfile" \
  || fail "the dependency builder blob is not reverified inside BuildKit"
grep -Fq 'PIP_INDEX_URL="${DEPENDENCY_WHEEL_INDEX_URL}"' "$dockerfile" \
  || fail "the wheelhouse source is not fixed to public PyPI"
grep -Fq 'env -u PIP_EXTRA_INDEX_URL' "$dockerfile" \
  || fail "the wheelhouse build may inherit an extra package index"
grep -Fq 'finalize_dependency_manifest' "$dockerfile" \
  || fail "the exact wheel set is not bound into the finalized runtime identity"
reject_ere_matches \
  "dependency identity verification must not use removable Python assertions" \
  'assert metadata\[' "$dockerfile"
grep -Fq '/opt/codingworkspace-dependency-wheelhouse' "$dockerfile" \
  || fail "the immutable dependency wheelhouse is not built into the image"
grep -Eq '/usr/local/sbin/codingworkspace-prestop' "$dockerfile" \
  || fail "the image-side preStop helper is not installed"
grep -Eq 'git .* archive --format=tar' "$dockerfile" \
  || fail "CodingWorkspace must be installed from the pinned Git object, not working-tree contents"
grep -Eq 'notebook.*7\.6\.1|7\.6\.1.*notebook' "$dockerfile" \
  || fail "Notebook 7.6.1 is not asserted by the image build"
grep -Eq 'jupyterlab.*4\.6\.2|4\.6\.2.*jupyterlab' "$dockerfile" \
  || fail "JupyterLab 4.6.2 is not asserted by the image build"
reject_ere_matches \
  "an unpinned OpenCode or jupyter-server-proxy installer remains" \
  'https://opencode\.ai/install|pip install[^#]*jupyter-server-proxy([[:space:]\\]|$)' \
  "$dockerfile"
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
  'CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS' \
  'load_shutdown_budget()' \
  'PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS' \
  'os.pidfd_open' \
  'signal.pidfd_send_signal(pid_descriptor, signal.SIGTERM)' \
  'status=not-running' \
  'find_raw_matches(expected_uid, deadline)' \
  'prestop_target_ambiguous' \
  'prestop_target_restarted' \
  'prestop_hook_deadline_exceeded' \
  'signal.setitimer(signal.ITIMER_REAL, budget.hook_seconds)' \
  'prestop_shutdown_checkpoint_missing' \
  'prestop_checkpoint_sqlite_quick_check_failed' \
  'verify_primary_storage_best_effort' \
  'primary_quick_check=' \
  'connection.set_progress_handler(' \
  'PRAGMA quick_check'; do
  grep -Fq "$required" "$prestop" || fail "preStop helper is missing $required"
done
reject_ere_matches \
  "preStop may not use a PID-reuse-prone os.kill fallback" \
  'os\.kill\(' "$prestop"
reject_ere_matches \
  "preStop may not encode a fixed whole-hook deadline" \
  'MAX_HOOK_SECONDS|SHUTDOWN_WAIT_SECONDS' "$prestop"

python3 - <<'PY'
import ast
from pathlib import Path

paths = {
    "hook": Path("codingworkspace-notebook/codingworkspace_prestop.py"),
    "runtime": Path("codingworkspace-notebook/codingworkspace_jupyter_runtime.py"),
}
constant_names = {
    "TERMINATION_GRACE_ENV",
    "KUBELET_POST_HOOK_RESERVE_SECONDS",
    "PRESTOP_DISCOVERY_RESERVE_SECONDS",
    "PRESTOP_PROCESS_EXIT_RESERVE_SECONDS",
    "PRESTOP_REPLACEMENT_QUIET_SECONDS",
    "PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS",
    "MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS",
    "MAX_CODINGWORKSPACE_SHUTDOWN_SECONDS",
}

def constants(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id in constant_names:
            result[target.id] = ast.literal_eval(node.value)
    return result

seen = {name: constants(path) for name, path in paths.items()}
for name, values in seen.items():
    missing = sorted(constant_names - values.keys())
    if missing:
        raise SystemExit(f"{name} is missing shared preStop constants: {missing}")
if seen["hook"] != seen["runtime"]:
    raise SystemExit(
        "preStop/runtime shutdown budget constants diverged: "
        f"hook={seen['hook']!r} runtime={seen['runtime']!r}"
    )
PY

server_config=codingworkspace-notebook/codingworkspace_server_proxy_config.py
runtime_config=codingworkspace-notebook/codingworkspace_jupyter_runtime.py
dependency_config=codingworkspace-notebook/codingworkspace_dependency_contract.py
grep -Fq 'parse_termination_grace_seconds(' "$server_config" \
  || fail "Jupyter startup does not validate the asserted pod termination grace"
grep -Fq 'derive_codingworkspace_shutdown_seconds(' "$server_config" \
  || fail "the CodingWorkspace child timeout is not derived from pod grace"
reject_ere_matches \
  "the Jupyter config may not hard-code an independent child shutdown timeout" \
  '"CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS":[[:space:]]*"[0-9]+"' \
  "$server_config"
grep -Fq 'raw_credential_issued_at_epoch = os.environ.get(' "$server_config" \
  || fail "model credential issuance does not preserve the operator-supplied epoch"
grep -Fq '"CODINGWORKSPACE_MODEL_CREDENTIAL_ISSUED_AT_EPOCH", "0"' "$server_config" \
  || fail "missing model credential issuance does not use the unknown-age sentinel"
grep -Fq 'credential_issued_at_epoch != 0' "$runtime_config" \
  || fail "the runtime does not accept the unknown credential-age sentinel"
reject_ere_matches \
  "Jupyter restart time must not be misreported as model credential issuance" \
  'credential_issued_at_epoch = str\(int\(time\.time\(\)\)\)' "$server_config"
grep -Fq 'image_dependency_environment()' "$server_config" \
  || fail "Jupyter startup does not validate the baked dependency identity"
for required in \
  CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE \
  CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE_MODE \
  CODINGWORKSPACE_DEPENDENCY_RUNTIME_ID \
  '"CODINGWORKSPACE_PREVIEW_IDLE_TIMEOUT_SECONDS": "600"'; do
  grep -Fq "$required" "$server_config" "$dependency_config" \
    || fail "the fixed Hub dependency/idle environment is missing $required"
done
grep -Fq 'require_current_python=True' "$dependency_config" \
  || fail "the wheelhouse manifest is not compared with the final Python runtime"

config_text=$(cat codingworkspace-notebook/*.py)
for required in \
  request_headers_override \
  X-CodingWorkspace-Proxy-Token \
  CODINGWORKSPACE_PROXY_AUTH_TOKEN \
  CODINGWORKSPACE_ISOLATION_MODE \
  '"CODINGWORKSPACE_ISOLATION_MODE": "logical"' \
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
