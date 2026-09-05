#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import codingworkspace_prestop as prestop


class ShutdownOutcomeSummaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary.name)
        self.saved_run_dir = prestop.EXPECTED_RUN_DIR
        prestop.EXPECTED_RUN_DIR = str(self.run_dir)
        self.path = self.run_dir / prestop.SHUTDOWN_OUTCOME_FILE
        self.uid = os.geteuid()

    def tearDown(self) -> None:
        prestop.EXPECTED_RUN_DIR = self.saved_run_dir
        self.temporary.cleanup()

    def write(self, value: object) -> None:
        self.path.write_text(json.dumps(value), encoding="utf-8")
        self.path.chmod(0o600)

    def test_absent_file_is_one_token(self) -> None:
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid, time.time() - 5), "shutdown_outcome=absent")

    def test_degraded_outcome_is_quoted_field_by_field(self) -> None:
        self.write(
            {
                "checkpointState": "degraded",
                "checkpointSkipReason": None,
                "databaseClosed": False,
                "inFlight": {"mutatingRequests": 1, "httpRequests": 1},
            }
        )
        self.assertEqual(
            prestop.summarize_shutdown_outcome(self.uid, time.time() - 5),
            "shutdown_outcome=degraded shutdown_skip_reason=none "
            "shutdown_in_flight_mutations=1 shutdown_db_closed=false",
        )

    def test_skipped_outcome_carries_its_reason(self) -> None:
        self.write({"checkpointState": "skipped", "checkpointSkipReason": "sqlite-backup-timeout", "databaseClosed": True})
        summary = prestop.summarize_shutdown_outcome(self.uid, time.time() - 5)
        self.assertIn("shutdown_outcome=skipped", summary)
        self.assertIn("shutdown_skip_reason=sqlite-backup-timeout", summary)
        self.assertIn("shutdown_in_flight_mutations=none", summary)

    def test_stale_file_from_a_previous_stop_is_not_quoted(self) -> None:
        self.write({"checkpointState": "complete"})
        old = time.time() - 600
        os.utime(self.path, (old, old))
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid, time.time()), "shutdown_outcome=stale")

    def test_invalid_symlinked_or_foreign_files_collapse_to_a_token(self) -> None:
        self.path.write_text("not json", encoding="utf-8")
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid, time.time() - 5), "shutdown_outcome=invalid")
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid, time.time() - 5), "shutdown_outcome=invalid")
        self.path.unlink()
        target = self.run_dir / "elsewhere.json"
        target.write_text("{}", encoding="utf-8")
        self.path.symlink_to(target)
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid, time.time() - 5), "shutdown_outcome=absent")
        self.path.unlink()
        self.write({"checkpointState": "complete"})
        self.assertEqual(prestop.summarize_shutdown_outcome(self.uid + 1, time.time() - 5), "shutdown_outcome=unreadable")

    def test_values_are_sanitized_for_the_log_line(self) -> None:
        self.write({"checkpointState": "weird state\nwith newline", "inFlight": {"mutatingRequests": "3 4"}})
        summary = prestop.summarize_shutdown_outcome(self.uid, time.time() - 5)
        self.assertEqual(summary.count("\n"), 0)
        self.assertIn("shutdown_outcome=weird_state_with_newline", summary)
        self.assertIn("shutdown_in_flight_mutations=3_4", summary)

    def test_failure_details_ride_on_the_alert_line(self) -> None:
        import contextlib
        import io

        failure = prestop.PreStopFailure("prestop_shutdown_checkpoint_missing", details="shutdown_outcome=skipped")
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            prestop.emit_alert(failure.code, details=failure.details)
        self.assertIn(
            "code=prestop_shutdown_checkpoint_missing component=runtime phase=prestop shutdown_outcome=skipped",
            error.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
