import unittest
from unittest.mock import patch

from tuxindrive.models import SyncJob


class SelectiveRuleTests(unittest.TestCase):
    def test_extension_size_and_age_rules_are_normalized(self):
        job = SyncJob(
            account_remote="cloud",
            local_path="/tmp/files",
            selective_extensions=[".PDF", "*.jpg", "bad/value", "pdf"],
            selective_max_size_mb=250,
            selective_max_age_days=90,
        )
        self.assertEqual(
            job.selective_args(),
            ["--include", "*.pdf", "--include", "*.jpg", "--max-size", "250M", "--max-age", "90d"],
        )
        self.assertTrue(job.selected_by_rules("folder/report.PDF", size=10 * 1024 * 1024))
        self.assertFalse(job.selected_by_rules("folder/archive.zip", size=1))
        self.assertFalse(job.selected_by_rules("folder/photo.jpg", size=251 * 1024 * 1024))
        with patch("tuxindrive.models.time.time", return_value=100 * 86400):
            self.assertFalse(job.selected_by_rules("old.pdf", modified_timestamp=1))

    def test_empty_rules_do_not_change_existing_jobs(self):
        job = SyncJob(account_remote="cloud", local_path="/tmp/files")
        self.assertEqual(job.selective_args(), [])


if __name__ == "__main__":
    unittest.main()
