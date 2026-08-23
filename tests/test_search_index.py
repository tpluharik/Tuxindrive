import os
import tempfile
import unittest
from pathlib import Path

from tuxindrive.models import SyncJob, SyncMode
from tuxindrive.search_index import FolderSearchIndex


class FolderSearchIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "sync"
        self.root.mkdir()
        self.index = FolderSearchIndex(Path(self.temporary.name) / "private" / "search.sqlite3")
        self.job = SyncJob(
            account_remote="test",
            local_path=str(self.root),
            name="Work files",
            id="job-one",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_indexes_names_and_paths_without_reading_contents(self):
        folder = self.root / "Reports"
        folder.mkdir()
        secret = folder / "Q4 Budget.txt"
        secret.write_text("this content must not enter the index", encoding="utf-8")

        stats = self.index.refresh([self.job])

        self.assertEqual(stats.indexed, 2)
        result = self.index.search("q4 budget")[0]
        self.assertEqual(result.relative_path, "Reports/Q4 Budget.txt")
        self.assertEqual(result.job_name, "Work files")
        self.assertEqual(result.local_path, secret)
        self.assertEqual(self.index.search("content must not"), [])

    def test_search_is_unicode_casefolded_and_supports_multiple_tokens(self):
        (self.root / "PŘEHLED faktur 2026.pdf").touch()
        self.index.refresh([self.job])
        self.assertEqual(
            self.index.search("přehled 2026")[0].name,
            "PŘEHLED faktur 2026.pdf",
        )
        self.assertEqual(self.index.search("přehled missing"), [])

    def test_literal_wildcard_characters_are_not_sql_patterns(self):
        (self.root / "100% complete.txt").touch()
        (self.root / "1000 complete.txt").touch()
        self.index.refresh([self.job])
        self.assertEqual([item.name for item in self.index.search("100%")], ["100% complete.txt"])

    def test_stale_entries_are_removed_after_complete_refresh(self):
        old = self.root / "old.txt"
        old.touch()
        self.index.refresh([self.job])
        old.unlink()
        (self.root / "new.txt").touch()

        stats = self.index.refresh([self.job])

        self.assertEqual(stats.removed, 1)
        self.assertEqual(self.index.search("old"), [])
        self.assertEqual(self.index.search("new")[0].name, "new.txt")

    def test_symlinks_and_excluded_paths_are_skipped(self):
        outside = Path(self.temporary.name) / "outside.txt"
        outside.touch()
        try:
            (self.root / "outside-link").symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        (self.root / "download.part").touch()
        (self.root / "visible.txt").touch()

        self.index.refresh([self.job])

        self.assertEqual([item.name for item in self.index.search("visible")], ["visible.txt"])
        self.assertEqual(self.index.search("outside"), [])
        self.assertEqual(self.index.search("download"), [])

    def test_symlink_root_is_not_indexed(self):
        real = Path(self.temporary.name) / "real-root"
        real.mkdir()
        (real / "outside.txt").touch()
        linked = Path(self.temporary.name) / "linked-root"
        try:
            linked.symlink_to(real, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        linked_job = SyncJob("test", str(linked), id="linked-job")
        stats = self.index.refresh([linked_job])
        self.assertEqual(stats.skipped_jobs, 1)
        self.assertEqual(self.index.count(), 0)

    def test_paused_jobs_remain_searchable(self):
        (self.root / "paused.txt").touch()
        self.job.enabled = False
        self.index.refresh([self.job])
        self.assertEqual(self.index.search("paused")[0].name, "paused.txt")

    def test_missing_and_files_on_demand_jobs_are_removed_or_skipped(self):
        (self.root / "local.txt").touch()
        self.index.refresh([self.job])
        self.job.mode = SyncMode.VIRTUAL_DRIVE

        stats = self.index.refresh([self.job])

        self.assertEqual(stats.skipped_jobs, 1)
        self.assertEqual(stats.removed, 1)
        self.assertEqual(self.index.count(), 0)

    def test_unconfigured_jobs_are_pruned(self):
        (self.root / "local.txt").touch()
        self.index.refresh([self.job])
        self.assertEqual(self.index.refresh([]).removed, 1)

    def test_safety_limit_keeps_existing_entries_not_seen_by_partial_walk(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            (self.root / name).touch()
        self.index.refresh([self.job])
        limited = FolderSearchIndex(self.index.path, max_entries_per_job=1)

        stats = limited.refresh([self.job])

        self.assertEqual(stats.limited_jobs, 1)
        self.assertEqual(limited.count(), 3)

    @unittest.skipIf(os.name == "nt", "POSIX mode assertion")
    def test_database_and_parent_are_private(self):
        self.assertEqual(self.index.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.index.path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
