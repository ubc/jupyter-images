#!/usr/bin/env python3

from __future__ import annotations

import unittest

from select_cw_build_ref import select_build_ref


TRACKED = "1" * 40
CANDIDATE = "abcdef0123456789abcdef0123456789abcdef01"


class SelectCodingWorkspaceBuildRefTests(unittest.TestCase):
    def test_default_flow_uses_the_tracker_owned_pin(self) -> None:
        self.assertEqual(
            select_build_ref(TRACKED, "", "push", False),
            TRACKED,
        )
        self.assertEqual(
            select_build_ref(TRACKED, "", "workflow_dispatch", True),
            TRACKED,
        )

    def test_manual_non_promoting_candidate_uses_exact_sha(self) -> None:
        self.assertEqual(
            select_build_ref(CANDIDATE, CANDIDATE, "workflow_dispatch", False),
            CANDIDATE,
        )

    def test_candidate_cannot_request_promotion(self) -> None:
        with self.assertRaisesRegex(ValueError, "never be combined with promotion"):
            select_build_ref(TRACKED, CANDIDATE, "workflow_dispatch", True)

    def test_candidate_is_workflow_dispatch_only(self) -> None:
        for event_name in ("push", "pull_request", "schedule"):
            with self.subTest(event_name=event_name):
                with self.assertRaisesRegex(ValueError, "only for workflow_dispatch"):
                    select_build_ref(TRACKED, CANDIDATE, event_name, False)

    def test_candidate_requires_exact_lowercase_full_sha(self) -> None:
        invalid = (
            "a" * 39,
            "a" * 41,
            "A" * 40,
            "g" * 40,
            f" {CANDIDATE}",
            f"{CANDIDATE}\n",
            "refs/heads/main",
        )
        for candidate in invalid:
            with self.subTest(candidate=repr(candidate)):
                with self.assertRaisesRegex(ValueError, "exactly 40 lowercase"):
                    select_build_ref(TRACKED, candidate, "workflow_dispatch", False)

    def test_tracked_pin_is_always_validated(self) -> None:
        for tracked in ("", "A" * 40, "main", "0" * 39):
            with self.subTest(tracked=tracked):
                with self.assertRaisesRegex(ValueError, "tracked CW_REF"):
                    select_build_ref(tracked, "", "push", False)


if __name__ == "__main__":
    unittest.main()
