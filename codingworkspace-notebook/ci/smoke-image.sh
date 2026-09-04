#!/usr/bin/env bash
# Image-contract checks for CI plus an opt-in lifecycle harness for a compatible
# Docker host. The actual JupyterHub/kernel/PVC acceptance run remains required.
set -euo pipefail

# Referenced when asserting the image OpenCode label against
# RUNTIME_PINS.env. Same derivation as ci/validate-static.sh.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat >&2 <<'EOF'
usage:
  smoke-image.sh contract IMAGE CW_REF GIZMOAPP_REF
  smoke-image.sh namespace IMAGE
  smoke-image.sh lifecycle IMAGE CW_REF GIZMOAPP_REF

"contract" is safe for ordinary trusted CI. "namespace" requires a host that
permits unprivileged user/mount/PID namespaces. "lifecycle" additionally runs
fresh/retained/stale-home and Jupyter route/proxy/shutdown checks with Docker.
EOF
  exit 2
}

MODE=${1:-}
IMAGE=${2:-}
[ -n "$MODE" ] && [ -n "$IMAGE" ] || usage

require_ref() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || {
    echo "expected a lowercase full Git SHA, got: $1" >&2
    exit 1
  }
}

contract() {
  local cw_ref=${3:-}
  local gizmo_ref=${4:-}
  require_ref "$cw_ref"
  require_ref "$gizmo_ref"
  docker image inspect "$IMAGE" >/dev/null
  docker run --rm --network none \
    -e "EXPECTED_CW_REF=$cw_ref" \
    -e "EXPECTED_GIZMOAPP_REF=$gizmo_ref" \
    --entrypoint /bin/bash "$IMAGE" -lc '
      set -euo pipefail
      test "$(id -u)" != 0
      command -v bwrap >/dev/null
      command -v opencode >/dev/null
      command -v codingworkspace >/dev/null
      pinned_opencode=$(sed -n 's/^OPENCODE_VERSION=//p' /etc/codingworkspace-runtime-pins.env)
      test -n "$pinned_opencode"
      test "$(opencode --version)" = "$pinned_opencode"
      python - <<"PY"
import importlib.machinery
import importlib.metadata as md
import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
assert md.version("jupyter-server-proxy") == "4.5.0"
assert md.version("jupyterhub") == "5.5.0"
assert md.version("notebook") == "7.6.1"
assert md.version("jupyterlab") == "4.6.2"
assert md.version("codingworkspace")

sys.path.insert(0, "/opt/codingworkspace-jupyter/runtime")
from codingworkspace_jupyter_runtime import (
    derive_codingworkspace_shutdown_seconds,
    parse_termination_grace_seconds,
)
from codingworkspace_dependency_contract import image_dependency_environment
dependency_environment = image_dependency_environment()
assert dependency_environment["CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE"] == "/opt/codingworkspace-dependency-wheelhouse"
assert dependency_environment["CODINGWORKSPACE_DEPENDENCY_WHEELHOUSE_MODE"] == "prefer"
assert dependency_environment["CODINGWORKSPACE_DEPENDENCY_RUNTIME_ID"].startswith("cw-wh-v1:")
assert parse_termination_grace_seconds("120") == 120
assert derive_codingworkspace_shutdown_seconds(120) == 90
assert derive_codingworkspace_shutdown_seconds(100) == 73
for invalid in (None, "", "56", "0120", "120 ", "120.0", "3601"):
    try:
        parse_termination_grace_seconds(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe termination grace accepted: {invalid!r}")

loader = importlib.machinery.SourceFileLoader(
    "codingworkspace_prestop_contract", "/usr/local/sbin/codingworkspace-prestop"
)
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
prestop = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = prestop
loader.exec_module(prestop)

saved_grace = os.environ.pop(prestop.TERMINATION_GRACE_ENV, None)
try:
    for invalid, expected_code in (
        (None, "prestop_termination_grace_invalid"),
        ("nonsense", "prestop_termination_grace_invalid"),
        ("0120", "prestop_termination_grace_invalid"),
        ("56", "prestop_termination_grace_unsafe"),
    ):
        if invalid is None:
            os.environ.pop(prestop.TERMINATION_GRACE_ENV, None)
        else:
            os.environ[prestop.TERMINATION_GRACE_ENV] = invalid
        try:
            prestop.load_shutdown_budget()
        except prestop.PreStopFailure as exc:
            assert exc.code == expected_code, exc.code
        else:
            raise AssertionError(f"unsafe helper grace accepted: {invalid!r}")

    os.environ[prestop.TERMINATION_GRACE_ENV] = "120"
    budget = prestop.load_shutdown_budget()
    assert budget.hook_seconds == (
        120 - prestop.KUBELET_POST_HOOK_RESERVE_SECONDS
    )
    assert budget.child_shutdown_seconds == 90
    valid_child_budget = {
        prestop.TERMINATION_GRACE_ENV: "120",
        "CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS": "90",
    }
    assert prestop.exact_budget_environment(
        valid_child_budget, budget, child=True
    )
    for name, bad_value in (
        (prestop.TERMINATION_GRACE_ENV, "119"),
        ("CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS", "89"),
    ):
        mismatched = dict(valid_child_budget)
        mismatched[name] = bad_value
        assert not prestop.exact_budget_environment(
            mismatched, budget, child=True
        )

    # The real CodingWorkspace child is non-dumpable, which makes its
    # /proc/<pid>/exe, cwd, and environ unreadable to this same-UID helper. The
    # hook must still identify it through cmdline/status plus its dumpable
    # Jupyter parent, or every Stop ends the container before the shutdown
    # checkpoint is written. Reproduce that shape with a throwaway parent that
    # carries the parent assertions and a child that drops dumpability.
    import ctypes
    import subprocess
    with tempfile.TemporaryDirectory(prefix="cw-prestop-identity-") as identity_root:
        cwd = Path(identity_root) / "empty-root"
        cwd.mkdir()
        child_marker = f"cw-prestop-child-{os.getpid()}"
        # execve resets dumpability, so the child must drop it itself, exactly
        # as CodingWorkspace does at startup (PR_SET_DUMPABLE = 4).
        child_command = (
            sys.executable,
            "-c",
            "import ctypes, time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); time.sleep(60)",
            child_marker,
        )
        parent_script = (
            "import subprocess, sys\n"
            "child = subprocess.Popen(sys.argv[1:])\n"
            "print(child.pid, flush=True)\n"
            "child.wait()\n"
        )
        parent_environment = {
            **prestop.EXPECTED_PARENT_ENVIRONMENT,
            prestop.TERMINATION_GRACE_ENV: "120",
            "PATH": os.environ.get("PATH", ""),
        }
        parent = subprocess.Popen(
            [sys.executable, "-c", parent_script, *child_command],
            cwd=str(cwd),
            env=parent_environment,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            child_pid = int(parent.stdout.readline().strip())
            saved = (prestop.EXPECTED_COMMAND, prestop.EXPECTED_CWD)
            prestop.EXPECTED_COMMAND = child_command
            prestop.EXPECTED_CWD = str(cwd)
            try:
                deadline = time.monotonic() + 10
                # Prove the shape: the child exe link is unreadable while cmdline is not.
                for _attempt in range(50):
                    try:
                        os.readlink(f"/proc/{child_pid}/exe")
                    except PermissionError:
                        break
                    time.sleep(0.1)
                else:
                    raise AssertionError("throwaway child is still dumpable")
                assert prestop.raw_process_match(child_pid, os.geteuid())
                assert prestop.find_raw_matches(os.geteuid(), deadline) == [child_pid]
                candidate = prestop.identify_candidate(child_pid, os.geteuid(), budget)
                assert candidate is not None, "non-dumpable child was not identified"
                assert candidate.pid == child_pid and candidate.parent_pid == parent.pid
                # A parent that does not carry the Hub grace assertion is rejected.
                wrong_budget = prestop.ShutdownBudget(
                    termination_grace_seconds=121, hook_seconds=115.0, child_shutdown_seconds=90
                )
                assert prestop.identify_candidate(child_pid, os.geteuid(), wrong_budget) is None
            finally:
                prestop.EXPECTED_COMMAND, prestop.EXPECTED_CWD = saved
        finally:
            parent.kill()
            parent.wait()
            try:
                os.kill(child_pid, 9)
            except (ProcessLookupError, NameError):
                pass

    # Drive the hook through its real entry point on this interpreter. The
    # conda CPython in the image lacks os.pidfd_open and signal.pidfd_send_signal,
    # which made run_prestop fail its precondition before signalling anything
    # on every real Stop; a test that only calls the matching functions cannot
    # see that. The throwaway child writes a valid shutdown checkpoint when it
    # receives SIGTERM, so the whole sequence must return 0 and report status=ok.
    import contextlib
    import io
    with tempfile.TemporaryDirectory(prefix="cw-prestop-entry-") as entry_root:
        root = Path(entry_root)
        run_dir = root / "run"
        backup_dir = run_dir / "metadata-backups"
        cwd = root / "empty-root"
        backup_dir.mkdir(parents=True)
        cwd.mkdir()
        run_dir.chmod(0o700)
        backup_dir.chmod(0o700)
        state_db = run_dir / "CodingWorkspace.sqlite3"
        connection = sqlite3.connect(state_db)
        connection.execute("CREATE TABLE durable(value TEXT NOT NULL)")
        connection.commit()
        connection.close()
        state_db.chmod(0o600)
        child_script = (
            "import ctypes, os, signal, sqlite3, sys, time\n"
            "ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)\n"
            "def stop(*_ignored):\n"
            "    name = time.strftime(\"%Y%m%dT%H%M%S\") + \".000000Z-shutdown-0badf00d.sqlite3\"\n"
            "    path = os.path.join(sys.argv[1], name)\n"
            "    connection = sqlite3.connect(path)\n"
            "    connection.execute(\"CREATE TABLE checkpoint(value TEXT NOT NULL)\")\n"
            "    connection.commit()\n"
            "    connection.close()\n"
            "    os.chmod(path, 0o600)\n"
            "    raise SystemExit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            "while True:\n"
            "    time.sleep(0.1)\n"
        )
        child_command = (sys.executable, "-c", child_script, str(backup_dir))
        parent_script = (
            "import subprocess, sys\n"
            "child = subprocess.Popen(sys.argv[1:])\n"
            "print(child.pid, flush=True)\n"
            "raise SystemExit(child.wait())\n"
        )
        parent_environment = {
            **prestop.EXPECTED_PARENT_ENVIRONMENT,
            prestop.TERMINATION_GRACE_ENV: "120",
            "PATH": os.environ.get("PATH", ""),
        }
        parent = subprocess.Popen(
            [sys.executable, "-c", parent_script, *child_command],
            cwd=str(cwd),
            env=parent_environment,
            stdout=subprocess.PIPE,
            text=True,
        )
        saved = (
            prestop.EXPECTED_COMMAND, prestop.EXPECTED_CWD, prestop.EXPECTED_RUN_DIR,
            prestop.EXPECTED_STATE_DB, prestop.EXPECTED_BACKUP_DIR,
        )
        try:
            child_pid = int(parent.stdout.readline().strip())
            prestop.EXPECTED_COMMAND = child_command
            prestop.EXPECTED_CWD = str(cwd)
            prestop.EXPECTED_RUN_DIR = str(run_dir)
            prestop.EXPECTED_STATE_DB = str(state_db)
            prestop.EXPECTED_BACKUP_DIR = str(backup_dir)
            for _attempt in range(50):
                try:
                    os.readlink(f"/proc/{child_pid}/exe")
                except PermissionError:
                    break
                time.sleep(0.1)
            else:
                raise AssertionError("throwaway child is still dumpable")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = prestop.run_prestop(time.monotonic() + 40, budget)
            assert result == 0, output.getvalue()
            assert "CW_PRESTOP v=1 status=ok" in output.getvalue(), output.getvalue()
            assert "checkpoint_quick_check=ok" in output.getvalue(), output.getvalue()
            checkpoints = sorted(
                name for name in os.listdir(backup_dir)
                if prestop.SHUTDOWN_CHECKPOINT_RE.fullmatch(name)
            )
            assert len(checkpoints) == 1, checkpoints
            assert parent.wait(timeout=10) == 0
        finally:
            (
                prestop.EXPECTED_COMMAND, prestop.EXPECTED_CWD, prestop.EXPECTED_RUN_DIR,
                prestop.EXPECTED_STATE_DB, prestop.EXPECTED_BACKUP_DIR,
            ) = saved
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            try:
                os.kill(child_pid, 9)
            except (ProcessLookupError, NameError):
                pass

    with tempfile.TemporaryDirectory(prefix="cw-prestop-contract-") as temporary:
        root = Path(temporary)
        run_dir = root / "run"
        backup_dir = run_dir / "metadata-backups"
        backup_dir.mkdir(parents=True)
        run_dir.chmod(0o700)
        backup_dir.chmod(0o700)
        state_db = run_dir / "CodingWorkspace.sqlite3"
        connection = sqlite3.connect(state_db)
        connection.execute("CREATE TABLE durable(value TEXT NOT NULL)")
        connection.commit()
        connection.close()
        state_db.chmod(0o600)
        corrupt_checkpoint = (
            backup_dir
            / "20260828T120000.000000Z-shutdown-deadbeef.sqlite3"
        )
        corrupt_checkpoint.write_bytes(b"not a sqlite database")
        corrupt_checkpoint.chmod(0o600)
        prestop.EXPECTED_RUN_DIR = str(run_dir)
        prestop.EXPECTED_STATE_DB = str(state_db)
        prestop.EXPECTED_BACKUP_DIR = str(backup_dir)
        try:
            prestop.verify_shutdown_storage(
                set(), os.geteuid(), time.monotonic() + 5
            )
        except prestop.PreStopFailure as exc:
            assert exc.code == "prestop_checkpoint_sqlite_quick_check_failed"
        else:
            raise AssertionError("corrupt mandatory shutdown checkpoint passed")

        original_quick_check = prestop.sqlite_quick_check
        try:
            for warning_code in (
                "prestop_primary_sqlite_quick_check_timeout",
                "prestop_primary_sqlite_quick_check_failed",
            ):
                def fail_primary(*_args, _code=warning_code, **_kwargs):
                    raise prestop.PreStopFailure(_code)

                prestop.sqlite_quick_check = fail_primary
                assert prestop.verify_primary_storage_best_effort(
                    os.geteuid(), time.monotonic() + 10
                ) == "warning"
        finally:
            prestop.sqlite_quick_check = original_quick_check
finally:
    if saved_grace is None:
        os.environ.pop(prestop.TERMINATION_GRACE_ENV, None)
    else:
        os.environ[prestop.TERMINATION_GRACE_ENV] = saved_grace
PY
      starter=/opt/codingworkspace-starters/GizmoApp
      test -d "$starter/.git"
      test ! -w "$starter"
      test "$(git -c safe.directory="$starter" -C "$starter" rev-parse HEAD)" = "$EXPECTED_GIZMOAPP_REF"
      test "$(git -c safe.directory="$starter" -C "$starter" rev-parse --show-object-format)" = sha1
      wheelhouse=/opt/codingworkspace-dependency-wheelhouse
      test "$(stat -c %u:%g:%a "$wheelhouse")" = 0:0:555
      (cd "$wheelhouse" && sha256sum --check --strict SHA256SUMS)
      offline_env=$(mktemp -d /tmp/codingworkspace-wheelhouse-smoke.XXXXXX)
      git clone --quiet --no-local --no-hardlinks "$starter" "$offline_env/GizmoApp"
      (
        cd "$offline_env/GizmoApp"
        # Drop PYTHONSAFEPATH the way the platform does. The image sets it
        # image-wide, but CodingWorkspace starts the starter through
        # app_process_env(), whose APP_ENV_ALLOWED_VARS allow-list does not
        # include it. Leaving it set here makes the smoke test a configuration
        # no student ever runs: server/manage.py imports gizmoapp_server from
        # its own directory, which PYTHONSAFEPATH removes from sys.path.
        env -u PIP_EXTRA_INDEX_URL -u PYTHONSAFEPATH \
          ALLOW_NETWORK_INSTALL=1 \
          PIP_CONFIG_FILE=/dev/null \
          PIP_FIND_LINKS="file://$wheelhouse" \
          PIP_NO_INDEX=1 \
          ./scripts/install_checkout.sh
        .venv/bin/python -m pip check
        .venv/bin/python -c "import flask, gunicorn, openai"
        gizmo_pid=""
        stop_gizmo() {
          if [ -n "$gizmo_pid" ] && kill -0 "$gizmo_pid" 2>/dev/null; then
            kill -TERM "$gizmo_pid"
            wait "$gizmo_pid"
          fi
        }
        trap stop_gizmo EXIT
        env -u PYTHONSAFEPATH \
          GIZMOAPP_ENV=development \
          GIZMOAPP_PORT=18001 \
          GIZMOAPP_URL_PREFIX= \
          .venv/bin/gunicorn --workers 1 --bind 127.0.0.1:18001 \
          server.wsgi:app > "$offline_env/gunicorn.log" 2>&1 &
        gizmo_pid=$!
        ready=0
        for attempt in $(seq 1 60); do
          if curl --fail --silent --show-error \
            http://127.0.0.1:18001/healthz >/dev/null; then
            ready=1
            break
          fi
          if ! kill -0 "$gizmo_pid" 2>/dev/null; then
            cat "$offline_env/gunicorn.log" >&2
            exit 1
          fi
          sleep 0.25
        done
        if [ "$ready" != 1 ]; then
          cat "$offline_env/gunicorn.log" >&2
          exit 1
        fi
        curl --fail --silent --show-error http://127.0.0.1:18001/ >/dev/null
        kill -0 "$gizmo_pid"
        stop_gizmo
        gizmo_pid=""
        trap - EXIT
      )
      rm -rf -- "$offline_env"
      # Load CodingWorkspace settings under exactly the environment the image
      # injects through its Jupyter config. The application validates that
      # environment at startup and serves CW-JH-STARTUP-001 when it disagrees
      # with the image (the ac2622f3 rollout failed this way while the older
      # contract smoke stayed green), so the disagreement must fail here.
      JUPYTERHUB_SERVICE_PREFIX=/user/smoke/ \
      CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS=120 \
      python - <<"PY"
import os
import sys

sys.path.insert(0, "/opt/codingworkspace-jupyter/runtime")


class _Config:
    """Accept every traitlets-style assignment the Jupyter config makes."""

    def __getattr__(self, name):
        value = _Config()
        setattr(self, name, value)
        return value

    def __call__(self, *args, **kwargs):
        return self


config_path = "/opt/codingworkspace-jupyter/config/jupyter_server_config.py"
namespace = {"c": _Config(), "__name__": "jupyter_server_config", "__file__": config_path}
with open(config_path, encoding="utf-8") as handle:
    exec(compile(handle.read(), config_path, "exec"), namespace)
cw_env = dict(namespace["cw_env"])
assert cw_env["CODINGWORKSPACE_AUTH_MODE"] == "jupyterhub", cw_env
assert cw_env["CODINGWORKSPACE_ISOLATION_MODE"] == "bubblewrap", cw_env["CODINGWORKSPACE_ISOLATION_MODE"]
os.environ.update(cw_env)

from codingworkspace.config import load_settings
from codingworkspace.bubblewrap import bubblewrap_executable

settings = load_settings()
assert settings.auth_mode == "jupyterhub"
assert settings.isolation_mode == "bubblewrap"
assert bubblewrap_executable(settings) == "/usr/bin/bwrap", settings.bubblewrap_command
print("CodingWorkspace accepts the image-injected JupyterHub environment")
PY
      test ! -e /etc/opencode/opencode.json
      test -z "${OPENCODE_CONFIG:-}"
      test "${JUPYTERHUB_SINGLEUSER_APP:-}" = "jupyter_server.serverapp.ServerApp"
      test "${JUPYTER_RUNTIME_DIR:-}" = /tmp/codingworkspace-jupyter-runtime
      test "${PYTHONNOUSERSITE:-}" = 1
      test "${PYTHONSAFEPATH:-}" = 1
      test -d "$JUPYTER_RUNTIME_DIR"
      test "$(stat -c %u "$JUPYTER_RUNTIME_DIR")" = "$(id -u)"
      test "$(stat -c %g "$JUPYTER_RUNTIME_DIR")" = "$(id -g)"
      test "$(stat -c %a "$JUPYTER_RUNTIME_DIR")" = 700
    '

  local label_cw label_gizmo label_opencode expected_opencode
  local label_builder_ref label_builder_blob label_index label_layer label_runtime label_manifest
  local artifact_runtime artifact_manifest image_platform
  label_cw=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.source-revision" }}' "$IMAGE")
  label_gizmo=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.starter-revision" }}' "$IMAGE")
  label_opencode=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.opencode-version" }}' "$IMAGE")
  expected_opencode=$(sed -n 's/^OPENCODE_VERSION=//p' "$SCRIPT_DIR/../RUNTIME_PINS.env")
  label_builder_ref=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.builder-revision" }}' "$IMAGE")
  label_builder_blob=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.builder-blob" }}' "$IMAGE")
  label_index=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.index-url" }}' "$IMAGE")
  label_layer=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.layer-version" }}' "$IMAGE")
  label_runtime=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.runtime-id" }}' "$IMAGE")
  label_manifest=$(docker image inspect --format '{{ index .Config.Labels "org.codingworkspace.dependency-wheelhouse.manifest-sha256" }}' "$IMAGE")
  artifact_runtime=$(docker run --rm --entrypoint /bin/sh "$IMAGE" -c \
    "sed -n 's/^DEPENDENCY_RUNTIME_ID=//p' /etc/codingworkspace-dependency-wheelhouse.env")
  artifact_manifest=$(docker run --rm --entrypoint /bin/sh "$IMAGE" -c \
    "sed -n 's/^DEPENDENCY_WHEELHOUSE_MANIFEST_SHA256=//p' /etc/codingworkspace-dependency-wheelhouse.env")
  image_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$IMAGE")
  . "$SCRIPT_DIR/../DEPENDENCY_LAYER.env"
  test "$label_cw" = "$cw_ref"
  test "$label_gizmo" = "$gizmo_ref"
  test "$label_opencode" = "$expected_opencode"
  test "$label_builder_ref" = "$DEPENDENCY_BUILDER_REF"
  test "$label_builder_blob" = "$DEPENDENCY_BUILDER_BLOB"
  test "$label_index" = "$DEPENDENCY_WHEEL_INDEX_URL"
  test "$label_layer" = "$DEPENDENCY_WHEELHOUSE_LAYER_VERSION"
  test "$label_runtime" = "$artifact_runtime"
  test "$label_manifest" = "$artifact_manifest"
  test "$image_platform" = linux/amd64
  echo "Image contract smoke passed: $IMAGE"
}

namespace_probe() {
  # Call the product's readiness probe itself. This exercises its exact
  # --unshare-all/--share-net/--unshare-user/--disable-userns/cap-drop flags,
  # rather than a weaker hand-written namespace command that could pass while
  # CodingWorkspace /readyz fails.
  docker run --rm --entrypoint python "$IMAGE" -c '
from types import SimpleNamespace
from codingworkspace.bubblewrap import bubblewrap_status

status = bubblewrap_status(
    SimpleNamespace(bubblewrap_command="/usr/bin/bwrap"),
    force=True,
)
assert status["installed"], status
assert status["functional"], status
assert status["filesystemIsolation"], status
assert status["processIsolation"], status
assert not status["networkIsolation"], status
print(status)
'
  echo "Bubblewrap user/mount/PID namespace probe passed: $IMAGE"
}

if [ "$MODE" = contract ]; then
  contract "$@"
  exit 0
fi
if [ "$MODE" = namespace ]; then
  namespace_probe
  exit 0
fi
if [ "$MODE" != lifecycle ]; then
  usage
fi

CW_REF=${3:-}
GIZMOAPP_REF=${4:-}
require_ref "$CW_REF"
require_ref "$GIZMOAPP_REF"
contract "$@"
namespace_probe

suffix="${RANDOM}-$$"
fresh_volume="cw-smoke-fresh-$suffix"
bad_volume="cw-smoke-bad-$suffix"
link_volume="cw-smoke-link-$suffix"
special_volume="cw-smoke-special-$suffix"
containers=()
volumes=("$fresh_volume" "$bad_volume" "$link_volume" "$special_volume")

cleanup() {
  local item
  for item in "${containers[@]}"; do
    docker rm -f "$item" >/dev/null 2>&1 || true
  done
  for item in "${volumes[@]}"; do
    docker volume rm "$item" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

for volume in "${volumes[@]}"; do
  docker volume create "$volume" >/dev/null
done

NB_UID=$(docker run --rm --entrypoint id "$IMAGE" -u)
NB_GID=$(docker run --rm --entrypoint id "$IMAGE" -g)
[[ "$NB_UID" =~ ^[0-9]+$ ]] && [[ "$NB_GID" =~ ^[0-9]+$ ]]
for volume in "${volumes[@]}"; do
  # Named volumes can initially be owned by root on different Docker storage
  # drivers. Model the Hub fsGroup/init behavior explicitly before creating
  # mode-0700 student fixtures.
  docker run --rm --user 0 -v "$volume:/home/jovyan" --entrypoint /bin/bash "$IMAGE" -ceu \
    "chown -R $NB_UID:$NB_GID /home/jovyan; chmod 0700 /home/jovyan"
done

TOKEN="cw-smoke-$suffix-$(printf '%032d' 0)"
USER_NAME="cw-smoke-$suffix"
BASE_URL="/user/$USER_NAME/"

start_server() {
  local volume=$1
  local name=$2
  containers+=("$name")
  docker run -d --name "$name" \
    -v "$volume:/home/jovyan" \
    -e "JUPYTERHUB_USER=$USER_NAME" \
    -e "JUPYTERHUB_SERVICE_PREFIX=$BASE_URL" \
    -e "CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS=120" \
    "$IMAGE" start-notebook.py \
      --ServerApp.base_url="$BASE_URL" \
      --IdentityProvider.token="$TOKEN" \
      --ServerApp.open_browser=False >/dev/null
}

request_code() {
  local name=$1
  local path=$2
  shift 2
  docker exec "$name" curl -sS -o /tmp/cw-smoke-response -w '%{http_code}' \
    -H "Authorization: token $TOKEN" "$@" "http://127.0.0.1:8888$path"
}

wait_for_code() {
  local name=$1
  local path=$2
  local expected=$3
  local attempt code
  for attempt in $(seq 1 120); do
    code=$(request_code "$name" "$path" 2>/dev/null || true)
    if [ "$code" = "$expected" ]; then
      return 0
    fi
    if ! docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null | grep -qx true; then
      docker logs "$name" >&2 || true
      return 1
    fi
    sleep 1
  done
  docker logs "$name" >&2 || true
  echo "timed out waiting for $path -> $expected (last: ${code:-none})" >&2
  return 1
}

prepare_home() {
  local volume=$1
  local command=$2
  docker run --rm -v "$volume:/home/jovyan" --entrypoint /bin/bash "$IMAGE" -ceu "$command"
}

run_verified_prestop() {
  local name=$1
  local before_count after_count output started elapsed
  before_count=$(docker exec "$name" /opt/conda/bin/python -c '
from pathlib import Path
print(len(list(Path("/home/jovyan/cw/run/metadata-backups").glob("*-shutdown-*.sqlite3"))))
')
  started=$(date +%s)
  output=$(docker exec "$name" /usr/local/sbin/codingworkspace-prestop)
  elapsed=$(( $(date +%s) - started ))
  grep -q 'CW_PRESTOP v=1 status=ok' <<<"$output"
  grep -q 'checkpoint_quick_check=ok' <<<"$output"
  grep -Eq 'primary_quick_check=(ok|warning|skipped-budget)' <<<"$output"
  test "$elapsed" -lt 115

  after_count=$(docker exec "$name" /opt/conda/bin/python -c '
from pathlib import Path
print(len(list(Path("/home/jovyan/cw/run/metadata-backups").glob("*-shutdown-*.sqlite3"))))
')
  test "$after_count" -eq $((before_count + 1))
  docker exec "$name" /opt/conda/bin/python -c '
import sqlite3
from pathlib import Path

run_dir = Path("/home/jovyan/cw/run")
checkpoints = sorted((run_dir / "metadata-backups").glob("*-shutdown-*.sqlite3"))
assert checkpoints
for path in (run_dir / "CodingWorkspace.sqlite3", checkpoints[-1]):
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        assert [str(row[0]) for row in connection.execute("PRAGMA quick_check")] == ["ok"]
    finally:
        connection.close()
'
  # A second invocation has no exact child and is an idempotent success. It
  # must say that nothing was running and leave Jupyter itself alive.
  started=$(date +%s)
  output=$(docker exec "$name" /usr/local/sbin/codingworkspace-prestop)
  elapsed=$(( $(date +%s) - started ))
  grep -q 'CW_PRESTOP v=1 status=not-running component=runtime' <<<"$output"
  test "$elapsed" -lt 5
  test "$(docker inspect -f '{{.State.Running}}' "$name")" = true
}

# Fresh home, exact-empty legacy cleanup, authenticated proxy, denied direct
# backend access, denied Jupyter APIs, Python user-site shadow resistance,
# starter creation, and graceful SIGTERM.
prepare_home "$fresh_volume" '
  install -d -m 0700 /home/jovyan/cw/run /home/jovyan/cw/run/github-credentials /home/jovyan/cw/run/opencode-auth
  install -d -m 0700 /home/jovyan/.local/lib/python3.13/site-packages/codingworkspace
  printf "%s\n" \
    "from pathlib import Path" \
    "Path(\"/home/jovyan/cw-shadow-imported\").write_text(\"unsafe\")" \
    > /home/jovyan/.local/lib/python3.13/site-packages/codingworkspace/__init__.py
'
fresh_container="cw-smoke-fresh-$suffix"
start_server "$fresh_volume" "$fresh_container"
wait_for_code "$fresh_container" "${BASE_URL}codingworkspace/livez" 200
wait_for_code "$fresh_container" "${BASE_URL}codingworkspace/readyz" 200
docker exec "$fresh_container" test ! -e /home/jovyan/cw-shadow-imported

direct_code=$(docker exec "$fresh_container" curl -sS -o /tmp/cw-smoke-direct -w '%{http_code}' \
  "http://127.0.0.1:8768${BASE_URL}codingworkspace/api/bootstrap")
case "$direct_code" in 401|403) ;; *) echo "direct backend returned $direct_code, expected 401/403" >&2; exit 1;; esac

for route in api/contents api/kernels api/sessions api/terminals lab tree; do
  code=$(request_code "$fresh_container" "${BASE_URL}${route}" || true)
  case "$code" in 403|404) ;; *) echo "Jupyter route /$route returned $code, expected 403/404" >&2; exit 1;; esac
done

bootstrap_code=$(request_code "$fresh_container" "${BASE_URL}codingworkspace/api/bootstrap" \
  -H 'X-CodingWorkspace-Request: 1')
test "$bootstrap_code" = 200
create_code=$(request_code "$fresh_container" "${BASE_URL}codingworkspace/api/workspaces" \
  -X POST \
  -H 'Content-Type: application/json' \
  -H 'X-CodingWorkspace-Request: 1' \
  --data '{"assignmentSlug":"image-smoke","displayName":"Image smoke starter"}')
test "$create_code" = 201
docker exec "$fresh_container" test -d /home/jovyan/cw/workspaces
docker exec "$fresh_container" find /home/jovyan/cw/workspaces -type d -name .git -print -quit | grep -q .
docker exec "$fresh_container" test ! -e /home/jovyan/cw/run/github-credentials
docker exec "$fresh_container" test ! -e /home/jovyan/cw/run/opencode-auth

run_verified_prestop "$fresh_container"
docker stop --time 15 "$fresh_container" >/dev/null

# Retained-home restart must preserve the workspace and become ready again.
retained_container="cw-smoke-retained-$suffix"
start_server "$fresh_volume" "$retained_container"
wait_for_code "$retained_container" "${BASE_URL}codingworkspace/readyz" 200
docker exec "$retained_container" test ! -e /home/jovyan/cw-shadow-imported
docker exec "$retained_container" find /home/jovyan/cw/workspaces -type d -name .git -print -quit | grep -q .
run_verified_prestop "$retained_container"
docker stop --time 15 "$retained_container" >/dev/null

assert_safe_stale_failure() {
  local volume=$1
  local name=$2
  start_server "$volume" "$name"
  wait_for_code "$name" "${BASE_URL}codingworkspace/" 503
  docker exec "$name" grep -q 'CW-JH-STARTUP-001' /tmp/cw-smoke-response
  docker stop --time 30 "$name" >/dev/null
}

prepare_home "$bad_volume" 'install -d -m 0700 /home/jovyan/cw/run/github-credentials; printf stale > /home/jovyan/cw/run/github-credentials/token'
assert_safe_stale_failure "$bad_volume" "cw-smoke-bad-$suffix"

prepare_home "$link_volume" 'install -d -m 0700 /home/jovyan/cw/run; ln -s /tmp /home/jovyan/cw/run/opencode-auth'
assert_safe_stale_failure "$link_volume" "cw-smoke-link-$suffix"

prepare_home "$special_volume" 'install -d -m 0700 /home/jovyan/cw/run; mkfifo /home/jovyan/cw/run/github-credentials'
assert_safe_stale_failure "$special_volume" "cw-smoke-special-$suffix"

echo "Fresh, retained, stale-state, proxy, Jupyter-route, verified preStop checkpoint, SQLite integrity, and restart smoke passed."
