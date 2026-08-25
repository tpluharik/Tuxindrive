import tempfile
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tuxindrive.callbacks import FileChange
from tuxindrive.models import SyncJob
from tuxindrive.recovery import (
    AuditIssue, IntegrityAuditor, MassChangeGuard, RecoveryEntry, RecoveryManager, SafetyError,
)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.local = self.root / "local"
        self.local.mkdir()
        self.job = SyncJob(account_remote="cloud", local_path=str(self.local), initialized=True)
        self.manager = RecoveryManager(self.root / "history")

    def tearDown(self):
        self.temporary.cleanup()

    def test_deleted_file_can_be_restored(self):
        source = self.local / "folder" / "draft.txt"
        source.parent.mkdir()
        source.write_text("before", encoding="utf-8")
        entry = self.manager.archive_local(self.job, "folder/draft.txt", "remote deletion")
        source.unlink()
        restored = self.manager.restore(self.job, entry)
        self.assertEqual(restored.read_text(encoding="utf-8"), "before")
        self.assertEqual(len(self.manager.entries(self.job.id)), 1)

    def test_disabled_history_does_not_archive_incoming_changes(self):
        self.job.version_history = False
        source = self.local / "draft.txt"
        source.write_text("before", encoding="utf-8")
        archived = self.manager.archive_incoming_changes(
            self.job, [FileChange("draft.txt", "remote", deleted=True)],
        )
        self.assertEqual(archived, [])
        self.assertFalse((self.root / "history" / self.job.id).exists())

    def test_entries_ignore_malformed_or_missing_history_records(self):
        index = self.root / "history" / self.job.id / "index.jsonl"
        index.parent.mkdir(parents=True)
        index.write_text('{"missing":"fields"}\nnot-json\n', encoding="utf-8")
        self.assertEqual(self.manager.entries(self.job.id), [])

    def test_restore_rejects_foreign_job_and_unsafe_relative_path(self):
        stored = self.root / "stored"
        stored.write_bytes(b"history")
        now = datetime.now(timezone.utc).isoformat()
        foreign = RecoveryEntry("other", "file", str(stored), now, "test", 7)
        with self.assertRaisesRegex(SafetyError, "no longer available"):
            self.manager.restore(self.job, foreign)
        unsafe = RecoveryEntry(self.job.id, "../escape", str(stored), now, "test", 7)
        with self.assertRaisesRegex(SafetyError, "unsafe"):
            self.manager.restore(self.job, unsafe)

    def test_prune_removes_only_expired_versions(self):
        job_root = self.root / "history" / self.job.id
        old_file, new_file = job_root / "old", job_root / "new"
        job_root.mkdir(parents=True)
        old_file.write_bytes(b"old")
        new_file.write_bytes(b"new")
        old = RecoveryEntry(
            self.job.id, "old.txt", str(old_file),
            (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(), "test", 3,
        )
        new = RecoveryEntry(
            self.job.id, "new.txt", str(new_file),
            datetime.now(timezone.utc).isoformat(), "test", 3,
        )
        index = job_root / "index.jsonl"
        index.write_text("\n".join(json.dumps({field: getattr(item, field) for field in item.__dataclass_fields__}) for item in (old, new)) + "\n", encoding="utf-8")
        self.assertEqual(self.manager.prune(self.job), 1)
        self.assertFalse(old_file.exists())
        self.assertTrue(new_file.exists())
        self.assertEqual([entry.relative_path for entry in self.manager.entries(self.job.id)], ["new.txt"])

    def test_mass_change_and_ransomware_suffixes_pause_job(self):
        self.job.mass_change_limit = 3
        self.job.mass_change_percent = 3
        changes = [FileChange(f"file-{index}.txt", "local") for index in range(3)]
        self.assertTrue(MassChangeGuard.assess(self.job, changes, 100).blocked)
        encrypted = [FileChange(f"victim-{index}.locked", "local") for index in range(5)]
        self.assertTrue(MassChangeGuard.assess(self.job, encrypted, 100).blocked)

    def test_bulk_guard_requires_count_and_percentage_but_keeps_hard_signals(self):
        self.job.mass_change_limit = 500
        self.job.mass_change_percent = 80
        ordinary = [FileChange(f"file-{index}.txt", "local") for index in range(300)]
        self.assertFalse(MassChangeGuard.assess(self.job, ordinary, 390).blocked)
        large = [FileChange(f"file-{index}.txt", "local") for index in range(800)]
        self.assertTrue(MassChangeGuard.assess(self.job, large, 900).blocked)
        deleted = [FileChange(f"old-{index}.txt", "remote", deleted=True) for index in range(101)]
        self.assertTrue(MassChangeGuard.assess(self.job, deleted, 1000).blocked)

    def test_mass_change_log_parsing_respects_disabled_protection(self):
        log = self.root / "preview.log"
        log.write_text("NOTICE : folder/file.txt: Deleted\n", encoding="utf-8")
        self.job.ransomware_protection = False
        self.assertFalse(MassChangeGuard.assess_log(self.job, log, 1).blocked)

    @mock.patch("tuxindrive.recovery.subprocess.run")
    def test_integrity_audit_parses_actionable_differences(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="= same\n* changed\n+ local\n- cloud\n", stderr="")
        auditor = IntegrityAuditor("rclone", self.manager)
        issues = auditor.audit(self.job)
        self.assertEqual([(item.symbol, item.path) for item in issues], [("*", "changed"), ("+", "local"), ("-", "cloud")])
        self.assertEqual(issues[1].description, "Only on cloud/peer side")
        self.assertEqual(issues[2].description, "Only on local side")

    def test_repair_downloads_cloud_only_and_changed_files(self):
        auditor = IntegrityAuditor("rclone", self.manager)
        commands = []

        def run(command):
            commands.append(command)
            if command[1] == "copyto" and not str(command[2]).startswith(str(self.local)):
                Path(command[3]).write_bytes(b"from-cloud")

        auditor._run = run
        repaired = auditor.repair(
            self.job,
            [AuditIssue("+", "cloud-only.txt"), AuditIssue("*", "changed.txt")],
            "remote",
        )

        self.assertEqual(repaired, 2)
        self.assertEqual((self.local / "cloud-only.txt").read_bytes(), b"from-cloud")
        self.assertEqual((self.local / "changed.txt").read_bytes(), b"from-cloud")
        self.assertTrue(all(command[1] == "copyto" for command in commands))

    def test_repair_removes_local_only_when_cloud_wins(self):
        local_only = self.local / "local-only.txt"
        local_only.write_bytes(b"local")
        auditor = IntegrityAuditor("rclone", self.manager)
        auditor._run = mock.Mock()

        repaired = auditor.repair(self.job, [AuditIssue("-", "local-only.txt")], "remote")

        self.assertEqual(repaired, 1)
        self.assertFalse(local_only.exists())
        auditor._run.assert_not_called()
        self.assertTrue(self.manager.entries(self.job.id))

    def test_repair_uploads_local_only_and_changed_files(self):
        (self.local / "local-only.txt").write_bytes(b"local")
        (self.local / "changed.txt").write_bytes(b"new")
        auditor = IntegrityAuditor("rclone", self.manager)
        auditor._run = mock.Mock()

        repaired = auditor.repair(
            self.job,
            [AuditIssue("-", "local-only.txt"), AuditIssue("*", "changed.txt")],
            "local",
        )

        self.assertEqual(repaired, 2)
        sources = [command[2] for command in (call.args[0] for call in auditor._run.call_args_list)]
        self.assertEqual(sources, [str(self.local / "local-only.txt"), str(self.local / "changed.txt")])

    def test_repair_removes_cloud_only_when_local_wins_after_backup(self):
        auditor = IntegrityAuditor("rclone", self.manager)
        commands = []

        def run(command):
            commands.append(command)
            if command[1] == "copyto":
                Path(command[3]).write_bytes(b"remote-backup")

        auditor._run = run
        repaired = auditor.repair(self.job, [AuditIssue("+", "cloud-only.txt")], "local")

        self.assertEqual(repaired, 1)
        self.assertEqual([command[1] for command in commands], ["copyto", "deletefile"])
        backup = self.manager.root / self.job.id / "remote-repair" / "cloud-only.txt"
        self.assertEqual(backup.read_bytes(), b"remote-backup")

    def test_keep_both_preserves_local_and_installs_named_remote_conflict(self):
        current = self.local / "report.txt"
        current.write_bytes(b"local")
        auditor = IntegrityAuditor("rclone", self.manager)

        def run(command):
            if command[1] == "copyto":
                Path(command[3]).write_bytes(b"remote")

        auditor._run = run
        self.assertEqual(
            auditor.repair(self.job, [AuditIssue("*", "report.txt")], "keep_both"),
            1,
        )
        self.assertEqual(current.read_bytes(), b"local")
        conflicts = list(self.local.glob("report.tuxindrive-cloud-conflict-*.txt"))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].read_bytes(), b"remote")

    def test_keep_both_can_install_nested_remote_only_file(self):
        auditor = IntegrityAuditor("rclone", self.manager)

        def run(command):
            if command[1] == "copyto":
                Path(command[3]).write_bytes(b"remote-only")

        auditor._run = run
        self.assertEqual(
            auditor.repair(
                self.job, [AuditIssue("+", "nested/cloud-only.txt")], "keep_both"
            ),
            1,
        )
        self.assertEqual(
            (self.local / "nested" / "cloud-only.txt").read_bytes(), b"remote-only"
        )


if __name__ == "__main__":
    unittest.main()
