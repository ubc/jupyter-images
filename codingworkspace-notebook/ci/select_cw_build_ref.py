#!/usr/bin/env python3
"""Select a tracked or explicitly non-promoting CodingWorkspace build commit."""

from __future__ import annotations

import argparse
import re


FULL_LOWER_SHA = re.compile(r"[0-9a-f]{40}")


def select_build_ref(
    tracked_ref: str,
    candidate_sha: str,
    event_name: str,
    promote_codingworkspace: bool,
) -> str:
    if not FULL_LOWER_SHA.fullmatch(tracked_ref):
        raise ValueError("tracked CW_REF must be one lowercase full Git SHA")
    if not candidate_sha:
        return tracked_ref
    if not FULL_LOWER_SHA.fullmatch(candidate_sha):
        raise ValueError("candidate SHA must be exactly 40 lowercase hexadecimal characters")
    if event_name != "workflow_dispatch":
        raise ValueError("a candidate SHA is accepted only for workflow_dispatch")
    if promote_codingworkspace:
        raise ValueError("a candidate SHA can never be combined with promotion")
    return candidate_sha


def parse_bool(value: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracked-ref", required=True)
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--event-name", required=True)
    parser.add_argument(
        "--promote-codingworkspace", required=True, type=parse_bool
    )
    args = parser.parse_args()
    try:
        selected = select_build_ref(
            args.tracked_ref,
            args.candidate_sha,
            args.event_name,
            args.promote_codingworkspace,
        )
    except ValueError as error:
        parser.error(str(error))
    print(selected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
