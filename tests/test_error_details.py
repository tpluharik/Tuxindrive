import tempfile
import unittest
from pathlib import Path

from tuxindrive.error_details import details_for_job, redact_error_text
from tuxindrive.models import SyncJob


class ErrorDetailsTests(unittest.TestCase):
    def test_details_use_bounded_job_log_without_conflict_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "logs"
            root.mkdir()
            log = root / "job.log"
            log.write_text(
                "INFO : starting\n"
                "ERROR : Documents/report.pdf: Failed to copy: access denied\n",
                encoding="utf-8",
            )
            job = SyncJob("cloud", "/home/user/cloud")
            job.last_error = "Synchronization failed (rclone exit 1)"
            job.last_error_at = "2026-08-25T12:00:00+00:00"
            job.last_error_log = str(log)

            details = details_for_job(job, root)

        self.assertEqual(details.source, "Documents/report.pdf")
        self.assertIn("access denied", details.excerpt)
        self.assertEqual(details.occurred_at, "2026-08-25T12:00:00+00:00")

    def test_log_outside_private_log_root_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "logs"
            root.mkdir()
            outside = base / "outside.log"
            outside.write_text("ERROR : private.txt: Failed token=exposed\n", encoding="utf-8")
            job = SyncJob("cloud", "/tmp/cloud", last_error="Failed")
            job.last_error_log = str(outside)

            details = details_for_job(job, root)

        self.assertNotIn("private.txt", details.excerpt)
        self.assertEqual(details.excerpt, "No additional error lines are available.")

    def test_rendered_diagnostics_redact_credentials(self) -> None:
        value = (
            "Authorization: Bearer header-secret authorization=Bearer-abc token=secret "
            "https://user:pass@example.test/file?access_token=query-secret"
        )
        redacted = redact_error_text(value)
        self.assertNotIn("header-secret", redacted)
        self.assertNotIn("Bearer-abc", redacted)
        self.assertNotIn("query-secret", redacted)
        self.assertNotIn("user:pass", redacted)
        self.assertIn("[redacted]", redacted)

    def test_reason_and_reported_source_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = SyncJob("cloud", "/tmp/cloud", last_error="Failed token=reason-secret")
            job.last_error_source = "https://user:pass@example.test/private.txt"

            details = details_for_job(job, root)

        self.assertNotIn("reason-secret", details.reason)
        self.assertNotIn("user:pass", details.source)


if __name__ == "__main__":
    unittest.main()
