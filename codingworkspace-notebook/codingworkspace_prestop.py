#!/opt/conda/bin/python
"""Safely drain the one managed CodingWorkspace child before pod termination.

Kubernetes runs this program as the notebook user from a ``preStop`` hook.
It deliberately refuses fuzzy process matches: signalling the wrong same-UID
process is worse than emitting a visible failed-hook alert and letting the pod's
ordinary termination policy take over.
"""

from __future__ import annotations

import os
import re
import select
import signal
import sqlite3
import stat
import sys
import time
from dataclasses import dataclass


EXPECTED_COMMAND = (
    "/opt/conda/bin/python",
    "-I",
    "-P",
    "-m",
    "codingworkspace.server",
    "serve",
)
EXPECTED_CWD = "/opt/codingworkspace-jupyter/empty-root"
EXPECTED_PYTHON = "/opt/conda/bin/python"
EXPECTED_RUN_DIR = "/home/jovyan/cw/run"
EXPECTED_STATE_DB = f"{EXPECTED_RUN_DIR}/CodingWorkspace.sqlite3"
EXPECTED_BACKUP_DIR = f"{EXPECTED_RUN_DIR}/metadata-backups"
TERMINATION_GRACE_ENV = "CODINGWORKSPACE_KUBERNETES_TERMINATION_GRACE_SECONDS"
EXPECTED_CHILD_ENVIRONMENT = {
    "CODINGWORKSPACE_AUTH_MODE": "jupyterhub",
    "CODINGWORKSPACE_CONFIG_FILE": "/opt/codingworkspace-jupyter/runtime/CodingWorkspace.env",
    "CODINGWORKSPACE_RUN_DIR": EXPECTED_RUN_DIR,
    "CODINGWORKSPACE_STATE_DB": EXPECTED_STATE_DB,
    "CODINGWORKSPACE_SQLITE_JOURNAL_MODE": "DELETE",
    "CODINGWORKSPACE_SQLITE_SYNCHRONOUS": "FULL",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
}
EXPECTED_PARENT_ENVIRONMENT = {
    "JUPYTER_CONFIG_DIR": "/opt/codingworkspace-jupyter/config",
    "JUPYTER_RUNTIME_DIR": "/tmp/codingworkspace-jupyter-runtime",
    "JUPYTERHUB_SINGLEUSER_APP": "jupyter_server.serverapp.ServerApp",
    "PYTHONNOUSERSITE": "1",
    "PYTHONSAFEPATH": "1",
}
# The Hub profile must inject its actual terminationGracePeriodSeconds through
# TERMINATION_GRACE_ENV. Every internal deadline is derived from that assertion;
# there is deliberately no image-side default which could silently diverge.
KUBELET_POST_HOOK_RESERVE_SECONDS = 6.0
PRESTOP_DISCOVERY_RESERVE_SECONDS = 2.0
PRESTOP_PROCESS_EXIT_RESERVE_SECONDS = 2.0
PRESTOP_REPLACEMENT_QUIET_SECONDS = 2.0
PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS = 15.0
MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS = 30
MAX_CODINGWORKSPACE_SHUTDOWN_SECONDS = 90
PRIMARY_QUICK_CHECK_MIN_SECONDS = 2.0
PRIMARY_QUICK_CHECK_MAX_SECONDS = 5.0
PRIMARY_QUICK_CHECK_RETURN_RESERVE_SECONDS = 1.0
MAX_PROC_FILE_BYTES = 1024 * 1024
SHUTDOWN_CHECKPOINT_RE = re.compile(
    r"^[0-9]{8}T[0-9]{6}\.[0-9]{6}Z-shutdown-[0-9a-f]{8}\.sqlite3$"
)


class PreStopFailure(RuntimeError):
    """A credential-safe preStop failure with a stable alert code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Candidate:
    pid: int
    parent_pid: int
    start_time: str


@dataclass(frozen=True)
class ShutdownBudget:
    termination_grace_seconds: int
    hook_seconds: float
    child_shutdown_seconds: int


def emit_alert(
    code: str, *, severity: str = "error", component: str = "runtime"
) -> None:
    print(
        f"CW_ALERT v=1 severity={severity} code={code} "
        f"component={component} phase=prestop",
        file=sys.stderr,
        flush=True,
    )


def load_shutdown_budget() -> ShutdownBudget:
    raw_value = os.environ.get(TERMINATION_GRACE_ENV, "")
    if (
        raw_value != raw_value.strip()
        or not raw_value.isascii()
        or not raw_value.isdecimal()
        or len(raw_value) > 4
    ):
        raise PreStopFailure("prestop_termination_grace_invalid")
    termination_grace_seconds = int(raw_value)
    if raw_value != str(termination_grace_seconds):
        raise PreStopFailure("prestop_termination_grace_invalid")
    minimum = int(
        KUBELET_POST_HOOK_RESERVE_SECONDS
        + PRESTOP_DISCOVERY_RESERVE_SECONDS
        + PRESTOP_PROCESS_EXIT_RESERVE_SECONDS
        + PRESTOP_REPLACEMENT_QUIET_SECONDS
        + PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS
        + MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS
    )
    if termination_grace_seconds < minimum or termination_grace_seconds > 3600:
        raise PreStopFailure("prestop_termination_grace_unsafe")
    child_shutdown_seconds = min(
        MAX_CODINGWORKSPACE_SHUTDOWN_SECONDS,
        int(
            termination_grace_seconds
            - KUBELET_POST_HOOK_RESERVE_SECONDS
            - PRESTOP_DISCOVERY_RESERVE_SECONDS
            - PRESTOP_PROCESS_EXIT_RESERVE_SECONDS
            - PRESTOP_REPLACEMENT_QUIET_SECONDS
            - PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS
        ),
    )
    if child_shutdown_seconds < MIN_CODINGWORKSPACE_SHUTDOWN_SECONDS:
        raise PreStopFailure("prestop_termination_grace_unsafe")
    return ShutdownBudget(
        termination_grace_seconds=termination_grace_seconds,
        hook_seconds=(
            termination_grace_seconds - KUBELET_POST_HOOK_RESERVE_SECONDS
        ),
        child_shutdown_seconds=child_shutdown_seconds,
    )


def require_time_remaining(
    deadline: float, code: str = "prestop_hook_deadline_exceeded"
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise PreStopFailure(code)
    return remaining


def deadline_signal_handler(_signum: int, _frame: object) -> None:
    raise PreStopFailure("prestop_hook_deadline_exceeded")


def read_proc_file(path: str) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        data = os.read(descriptor, MAX_PROC_FILE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_PROC_FILE_BYTES:
        raise OSError("oversized proc file")
    return data


def parse_environment(data: bytes) -> dict[str, str]:
    environment: dict[str, str] = {}
    for item in data.rstrip(b"\0").split(b"\0") if data else ():
        key, separator, value = item.partition(b"=")
        if not separator:
            continue
        name = key.decode("utf-8", "strict")
        if name in environment:
            raise OSError("duplicate environment key")
        environment[name] = value.decode("utf-8", "strict")
    return environment


def parse_status(data: bytes) -> tuple[int, tuple[int, int, int, int]]:
    parent_pid: int | None = None
    user_ids: tuple[int, int, int, int] | None = None
    for raw_line in data.splitlines():
        if raw_line.startswith(b"PPid:"):
            parent_pid = int(raw_line.split()[1])
        elif raw_line.startswith(b"Uid:"):
            values = tuple(int(value) for value in raw_line.split()[1:5])
            if len(values) == 4:
                user_ids = values  # type: ignore[assignment]
    if parent_pid is None or user_ids is None:
        raise OSError("incomplete process status")
    return parent_pid, user_ids


def process_start_time(pid: int) -> str:
    # The executable name in /proc/<pid>/stat is parenthesized and may contain
    # spaces or parentheses. Split after its final ')' before selecting field 22.
    data = read_proc_file(f"/proc/{pid}/stat").decode("ascii", "strict")
    suffix = data[data.rfind(")") + 2 :].split()
    if len(suffix) < 20:
        raise OSError("incomplete process stat")
    return suffix[19]


def same_executable(pid: int) -> bool:
    try:
        return os.path.samefile(f"/proc/{pid}/exe", EXPECTED_PYTHON)
    except (FileNotFoundError, OSError):
        return False


def exact_environment(environment: dict[str, str], required: dict[str, str]) -> bool:
    return all(environment.get(name) == value for name, value in required.items())


def exact_budget_environment(
    environment: dict[str, str], budget: ShutdownBudget, *, child: bool
) -> bool:
    if (
        environment.get(TERMINATION_GRACE_ENV)
        != str(budget.termination_grace_seconds)
    ):
        return False
    return not child or environment.get(
        "CODINGWORKSPACE_SHUTDOWN_TIMEOUT_SECONDS"
    ) == str(budget.child_shutdown_seconds)


def raw_process_match(pid: int, expected_uid: int) -> bool:
    try:
        if os.stat(f"/proc/{pid}", follow_symlinks=False).st_uid != expected_uid:
            return False
        command = tuple(
            part.decode("utf-8", "strict")
            for part in read_proc_file(f"/proc/{pid}/cmdline").rstrip(b"\0").split(b"\0")
        )
        return command == EXPECTED_COMMAND and same_executable(pid)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, UnicodeError):
        return False


def identify_candidate(
    pid: int, expected_uid: int, budget: ShutdownBudget
) -> Candidate | None:
    try:
        if not raw_process_match(pid, expected_uid):
            return None
        if os.readlink(f"/proc/{pid}/cwd") != EXPECTED_CWD:
            return None
        parent_pid, user_ids = parse_status(read_proc_file(f"/proc/{pid}/status"))
        if any(user_id != expected_uid for user_id in user_ids):
            return None
        environment = parse_environment(read_proc_file(f"/proc/{pid}/environ"))
        if not exact_environment(environment, EXPECTED_CHILD_ENVIRONMENT):
            return None
        if not exact_budget_environment(environment, budget, child=True):
            return None
        proxy_token = environment.get("CODINGWORKSPACE_PROXY_AUTH_TOKEN", "")
        if len(proxy_token) < 32 or not environment.get("JUPYTERHUB_USER", "").strip():
            return None

        if os.stat(f"/proc/{parent_pid}", follow_symlinks=False).st_uid != expected_uid:
            return None
        _, parent_user_ids = parse_status(read_proc_file(f"/proc/{parent_pid}/status"))
        if any(user_id != expected_uid for user_id in parent_user_ids):
            return None
        parent_environment = parse_environment(
            read_proc_file(f"/proc/{parent_pid}/environ")
        )
        if not exact_environment(parent_environment, EXPECTED_PARENT_ENVIRONMENT):
            return None
        if not exact_budget_environment(parent_environment, budget, child=False):
            return None
        if os.readlink(f"/proc/{parent_pid}/cwd") != EXPECTED_CWD:
            return None
        return Candidate(
            pid=pid,
            parent_pid=parent_pid,
            start_time=process_start_time(pid),
        )
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError, UnicodeError, ValueError):
        return None


def find_raw_matches(expected_uid: int, deadline: float) -> list[int]:
    matches: list[int] = []
    with os.scandir("/proc") as entries:
        for entry in entries:
            require_time_remaining(deadline)
            if not entry.name.isascii() or not entry.name.isdecimal():
                continue
            pid = int(entry.name)
            if pid in {os.getpid(), os.getppid()}:
                continue
            if raw_process_match(pid, expected_uid):
                matches.append(pid)
    return sorted(matches)


def open_directory_no_follow(path: str) -> int:
    if not path.startswith("/"):
        raise PreStopFailure("prestop_storage_path_invalid")
    descriptor = os.open("/", os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY)
    try:
        for component in (item for item in path.split("/") if item):
            next_descriptor = os.open(
                component,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def snapshot_shutdown_checkpoints(expected_uid: int, deadline: float) -> set[str]:
    require_time_remaining(deadline)
    try:
        backup_descriptor = open_directory_no_follow(EXPECTED_BACKUP_DIR)
    except FileNotFoundError:
        return set()
    try:
        details = os.fstat(backup_descriptor)
        if (
            details.st_uid != expected_uid
            or not stat.S_ISDIR(details.st_mode)
            or details.st_mode & 0o077
        ):
            raise PreStopFailure("prestop_backup_directory_unsafe")
        checkpoints: set[str] = set()
        for name in os.listdir(backup_descriptor):
            require_time_remaining(deadline)
            if SHUTDOWN_CHECKPOINT_RE.fullmatch(name):
                checkpoints.add(name)
        return checkpoints
    finally:
        os.close(backup_descriptor)


def open_private_regular_file(
    directory_descriptor: int, name: str, expected_uid: int
) -> int:
    descriptor = os.open(
        name,
        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
        dir_fd=directory_descriptor,
    )
    details = os.fstat(descriptor)
    if (
        details.st_uid != expected_uid
        or not stat.S_ISREG(details.st_mode)
        or details.st_nlink != 1
        or details.st_mode & 0o077
    ):
        os.close(descriptor)
        raise PreStopFailure("prestop_sqlite_file_unsafe")
    return descriptor


def sqlite_quick_check(
    descriptor: int,
    deadline: float,
    *,
    failure_code: str,
    timeout_code: str,
) -> None:
    # Holding the no-follow descriptor fixes the inode while SQLite opens the
    # read-only /proc/self/fd view. ``immutable`` prevents journal creation.
    remaining = require_time_remaining(deadline, timeout_code)
    try:
        connection = sqlite3.connect(
            f"file:/proc/self/fd/{descriptor}?mode=ro&immutable=1",
            uri=True,
            timeout=max(0.001, min(5.0, remaining)),
        )
    except sqlite3.Error:
        require_time_remaining(deadline, timeout_code)
        raise PreStopFailure(failure_code) from None
    try:
        # SQLite invokes this during the potentially expensive full-database
        # quick check. Returning nonzero interrupts the VM at the hard hook
        # deadline instead of consuming Kubernetes' remaining grace period.
        connection.set_progress_handler(
            lambda: int(time.monotonic() >= deadline),
            100,
        )
        try:
            connection.execute("PRAGMA query_only = ON")
            findings = [
                str(row[0]) for row in connection.execute("PRAGMA quick_check")
            ]
        except sqlite3.Error:
            require_time_remaining(deadline, timeout_code)
            raise PreStopFailure(failure_code) from None
    finally:
        connection.set_progress_handler(None, 0)
        connection.close()
    require_time_remaining(deadline, timeout_code)
    if findings != ["ok"]:
        raise PreStopFailure(failure_code)


def verify_shutdown_storage(
    before: set[str], expected_uid: int, deadline: float
) -> str:
    require_time_remaining(deadline)
    backup_descriptor = open_directory_no_follow(EXPECTED_BACKUP_DIR)
    try:
        details = os.fstat(backup_descriptor)
        if (
            details.st_uid != expected_uid
            or not stat.S_ISDIR(details.st_mode)
            or details.st_mode & 0o077
        ):
            raise PreStopFailure("prestop_backup_directory_unsafe")
        new_checkpoints: list[str] = []
        for name in os.listdir(backup_descriptor):
            require_time_remaining(deadline)
            if SHUTDOWN_CHECKPOINT_RE.fullmatch(name) and name not in before:
                new_checkpoints.append(name)
        new_checkpoints.sort()
        if not new_checkpoints:
            raise PreStopFailure("prestop_shutdown_checkpoint_missing")
        if len(new_checkpoints) != 1:
            raise PreStopFailure("prestop_shutdown_checkpoint_ambiguous")
        checkpoint_descriptor = open_private_regular_file(
            backup_descriptor, new_checkpoints[0], expected_uid
        )
        try:
            # The newly and atomically published recovery checkpoint is the
            # shutdown contract. Its complete quick_check is mandatory and may
            # use the reserved remainder of the hook budget.
            sqlite_quick_check(
                checkpoint_descriptor,
                deadline,
                failure_code="prestop_checkpoint_sqlite_quick_check_failed",
                timeout_code="prestop_checkpoint_integrity_deadline_exceeded",
            )
        finally:
            os.close(checkpoint_descriptor)
    finally:
        os.close(backup_descriptor)

    return new_checkpoints[0]


def verify_primary_storage_best_effort(
    expected_uid: int, hook_deadline: float
) -> str:
    """Bound the redundant primary check without invalidating a good recovery point.

    CodingWorkspace closes the primary before it exits and validates the
    shutdown checkpoint before atomic publication. The helper independently
    validates that checkpoint above. Re-checking the primary is useful
    telemetry, but it must not consume the grace period or turn a verified
    recovery point into a false failed-hook alert on a large EFS database.
    """

    require_time_remaining(hook_deadline)
    primary_started = time.monotonic()
    primary_deadline = min(
        primary_started + PRIMARY_QUICK_CHECK_MAX_SECONDS,
        hook_deadline - PRIMARY_QUICK_CHECK_RETURN_RESERVE_SECONDS,
    )
    available = primary_deadline - primary_started
    if available < PRIMARY_QUICK_CHECK_MIN_SECONDS:
        return "skipped-budget"

    try:
        run_descriptor = open_directory_no_follow(EXPECTED_RUN_DIR)
        try:
            state_descriptor = open_private_regular_file(
                run_descriptor, os.path.basename(EXPECTED_STATE_DB), expected_uid
            )
            try:
                sqlite_quick_check(
                    state_descriptor,
                    primary_deadline,
                    failure_code="prestop_primary_sqlite_quick_check_failed",
                    timeout_code="prestop_primary_sqlite_quick_check_timeout",
                )
            finally:
                os.close(state_descriptor)
        finally:
            os.close(run_descriptor)
    except PreStopFailure as exc:
        # Never swallow the absolute hook timer. Local primary timeout and
        # integrity/path failures are warnings because the independently
        # verified shutdown checkpoint remains a valid recovery point.
        if exc.code == "prestop_hook_deadline_exceeded":
            raise
        emit_alert(exc.code, severity="warning", component="storage")
        return "warning"
    except (OSError, sqlite3.Error) as exc:
        emit_alert(
            f"prestop_primary_sqlite_check_{exc.__class__.__name__.lower()}",
            severity="warning",
            component="storage",
        )
        return "warning"
    return "ok"


def run_prestop(deadline: float, budget: ShutdownBudget) -> int:
    expected_uid = os.geteuid()
    if expected_uid == 0:
        raise PreStopFailure("prestop_refused_root")
    raw_matches = find_raw_matches(expected_uid, deadline)
    if not raw_matches:
        print(
            "CW_PRESTOP v=1 status=not-running component=runtime",
            flush=True,
        )
        return 0
    if len(raw_matches) != 1:
        raise PreStopFailure("prestop_target_ambiguous")
    candidate = identify_candidate(raw_matches[0], expected_uid, budget)
    if candidate is None:
        raise PreStopFailure("prestop_target_changed")

    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        raise PreStopFailure("prestop_pidfd_unavailable")
    pid_descriptor = os.pidfd_open(candidate.pid, 0)
    try:
        # Close the scan/open race before signalling. A pidfd prevents later PID
        # reuse from redirecting the signal to an unrelated same-UID process.
        verified = identify_candidate(candidate.pid, expected_uid, budget)
        rescanned_matches = find_raw_matches(expected_uid, deadline)
        if len(rescanned_matches) > 1:
            raise PreStopFailure("prestop_target_ambiguous")
        if rescanned_matches != [candidate.pid] or verified != candidate:
            raise PreStopFailure("prestop_target_changed")
        checkpoints_before = snapshot_shutdown_checkpoints(expected_uid, deadline)
        signal.pidfd_send_signal(pid_descriptor, signal.SIGTERM)

        poller = select.poll()
        poller.register(pid_descriptor, select.POLLIN)
        # Stop waiting early enough to preserve the replacement-quiet interval
        # and a mandatory full quick_check of the new recovery checkpoint.
        latest_safe_exit = (
            deadline
            - PRESTOP_REPLACEMENT_QUIET_SECONDS
            - PRESTOP_CHECKPOINT_INTEGRITY_RESERVE_SECONDS
        )
        declared_exit = (
            time.monotonic()
            + budget.child_shutdown_seconds
            + PRESTOP_PROCESS_EXIT_RESERVE_SECONDS
        )
        wait_seconds = min(
            latest_safe_exit, declared_exit
        ) - time.monotonic()
        if wait_seconds <= 0:
            raise PreStopFailure("prestop_shutdown_budget_exhausted")
        if not poller.poll(max(1, int(wait_seconds * 1000))):
            raise PreStopFailure("prestop_shutdown_timeout")
    finally:
        os.close(pid_descriptor)

    # A clean CodingWorkspace SIGTERM returns zero, so simpervisor does not
    # restart it. A nonzero child exit does restart; detect that replacement
    # before declaring the hook safe.
    quiet_deadline = min(
        time.monotonic() + PRESTOP_REPLACEMENT_QUIET_SECONDS,
        deadline,
    )
    while time.monotonic() < quiet_deadline:
        if find_raw_matches(expected_uid, deadline):
            raise PreStopFailure("prestop_target_restarted")
        time.sleep(min(0.1, require_time_remaining(deadline)))
    require_time_remaining(deadline)

    checkpoint = verify_shutdown_storage(checkpoints_before, expected_uid, deadline)
    primary_status = verify_primary_storage_best_effort(expected_uid, deadline)
    print(
        "CW_PRESTOP v=1 status=ok component=runtime "
        f"checkpoint={checkpoint} checkpoint_quick_check=ok "
        f"primary_quick_check={primary_status}",
        flush=True,
    )
    return 0


def main() -> int:
    if not hasattr(signal, "setitimer"):
        raise PreStopFailure("prestop_deadline_timer_unavailable")
    budget = load_shutdown_budget()
    deadline = time.monotonic() + budget.hook_seconds
    previous_handler = signal.signal(signal.SIGALRM, deadline_signal_handler)
    signal.setitimer(signal.ITIMER_REAL, budget.hook_seconds)
    try:
        return run_prestop(deadline, budget)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreStopFailure as exc:
        emit_alert(exc.code)
        raise SystemExit(1) from None
    except Exception as exc:
        emit_alert(f"prestop_unexpected_{exc.__class__.__name__.lower()}")
        raise SystemExit(1) from None
