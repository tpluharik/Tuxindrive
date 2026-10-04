import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from tuxindrive.models import SyncJob
from tuxindrive.selective_rules import preset_by_key, preview_local_rules


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

    def test_root_anchored_includes_do_not_match_nested_namesakes(self):
        job = SyncJob(
            account_remote="cloud", local_path="/tmp/files",
            include_patterns=["/sessions/**", "/session_index.jsonl"],
        )
        self.assertTrue(job.selected_by_rules("sessions/2026/chat.jsonl"))
        self.assertTrue(job.selected_by_rules("session_index.jsonl"))
        self.assertFalse(job.selected_by_rules("browser/sessions/private.toml"))
        self.assertFalse(job.selected_by_rules("auth.json"))

    def test_named_presets_and_local_preview_use_metadata_only(self):
        self.assertIn("pdf", preset_by_key("documents").extensions)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "report.pdf").write_bytes(b"report")
            (root / "archive.zip").write_bytes(b"archive")
            try:
                (root / "link.pdf").symlink_to(root / "report.pdf")
            except OSError:
                pass
            job = SyncJob("cloud", temporary, selective_extensions=["pdf"])
            result = preview_local_rules(job)
        self.assertEqual(result.examined_files, 2)
        self.assertEqual(result.selected_files, 1)
        self.assertEqual(result.rejected_files, 1)
        self.assertEqual(result.selected_bytes, 6)

    def test_preview_is_bounded_and_reports_truncation(self):
        with tempfile.TemporaryDirectory() as temporary:
            for index in range(3):
                Path(temporary, f"{index}.txt").write_text("x", encoding="utf-8")
            result = preview_local_rules(SyncJob("cloud", temporary), max_files=2)
        self.assertTrue(result.truncated)
        self.assertEqual(result.examined_files, 2)


if __name__ == "__main__":
    unittest.main()
