"""Seed and check exact-empty legacy directories in a disposable smoke home.

This is a Docker test fixture, never a retained student-home cleanup utility.
"""
import os
from pathlib import Path
import stat
import subprocess


LEGACY_NAMES = ("github-credentials", "opencode-auth")


def verify_legacy_fixture(home: Path) -> None:
    run_dir = home / "cw" / "run"
    parent = run_dir.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid():
        raise ValueError("Smoke run directory must be a directory owned by the image user")
    groups = {os.getegid(), *os.getgroups()}
    for name in LEGACY_NAMES:
        target = run_dir / name
        info = target.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or info.st_gid not in groups
            or stat.S_IMODE(info.st_mode) != 0o700
            or info.st_nlink != 2
        ):
            raise ValueError(
                f"Invalid smoke legacy fixture {name}: expected an owned directory, "
                f"a current group, exact mode 0700 and 2 links; observed "
                f"uid={info.st_uid} gid={info.st_gid} "
                f"mode={stat.S_IMODE(info.st_mode):04o} links={info.st_nlink} "
                f"euid={os.geteuid()} groups={sorted(groups)}"
            )
        if any(target.iterdir()):
            raise ValueError(f"Smoke legacy fixture {name} must be empty")


def prepare_legacy_fixture(home: Path) -> None:
    run_dir = home / "cw" / "run"
    targets = [run_dir / name for name in LEGACY_NAMES]
    if any(os.path.lexists(target) for target in targets):
        raise ValueError("Smoke legacy fixture requires absent target paths; refusing existing state")
    # The Jupyter base sets setgid on its home. GNU install -m 0700 preserves
    # inherited setgid, producing 02700 and correctly failing CW's exact-mode
    # check. The additional zero explicitly clears special bits in this fixture.
    subprocess.run(
        ["install", "-d", "-m", "00700", str(run_dir), *(str(path) for path in targets)],
        check=True,
    )
    verify_legacy_fixture(home)


if __name__ == "__main__":
    prepare_legacy_fixture(Path("/home/jovyan"))
    print("CW_LIFECYCLE_LEGACY_FIXTURE v=1 status=passed mode=0700 links=2 entries=0")
