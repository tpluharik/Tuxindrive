"""Credential-hang and ordered backup-filter regressions; synthetic data only."""

from tests import signal_safety as _signal_safety  # noqa: F401

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tuxindrive.callbacks import ChangeMonitor, FileChange
from tuxindrive.engine import SyncEngine
from tuxindrive.models import SyncJob, SyncMode
from tuxindrive.rclone import RcloneClient, RcloneError


class BackupRegressionTests(unittest.TestCase):
    def test_exclusions_precede_chat_allowlist_and_end_with_default_deny(self):
        job = SyncJob("cloud", "/synthetic", include_patterns=["/sessions/**"],
                      exclude_patterns=["**/auth.json", "**/*.lock"])
        self.assertEqual(job.filter_args(), [
            "--filter", "- **/auth.json", "--filter", "- **/*.lock",
            "--filter", "+ /sessions/**", "--filter", "- **",
        ])
        self.assertNotIn("--include", job.filter_args())
        self.assertNotIn("--exclude", job.filter_args())

    def test_full_backups_do_not_acquire_an_implicit_default_deny(self):
        job = SyncJob("cloud", "/synthetic", exclude_patterns=["auth.json"])
        self.assertEqual(job.filter_args(), ["--filter", "- auth.json"])

    def test_local_manifest_exclusions_cover_nested_and_root_files(self):
        job = SyncJob("cloud", "/synthetic", exclude_patterns=["**/auth.json", "/sessions/private/**"])
        self.assertTrue(job.excluded_by_rules("auth.json"))
        self.assertTrue(job.excluded_by_rules("sessions/auth.json"))
        self.assertTrue(job.excluded_by_rules("sessions/private/chat.jsonl"))
        self.assertFalse(job.excluded_by_rules("archive/sessions/private/chat.jsonl"))

    def test_incremental_manifest_is_preselected_and_has_no_incompatible_filters(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            root = Path(temporary) / "source"
            (root / "sessions").mkdir(parents=True)
            for name in ("one.jsonl", "two.jsonl", "auth.json", "temporary.lock"):
                (root / "sessions" / name).write_text("synthetic", encoding="utf-8")
            job = SyncJob("cloud", str(root), include_patterns=["/sessions/**"],
                          exclude_patterns=["**/auth.json", "**/*.lock"],
                          selective_max_size_mb=1, selective_max_age_days=1)
            observed = []
            process = MagicMock()
            process.wait.return_value = 0

            def spawn(command, **_kwargs):
                manifest = Path(command[command.index("--files-from-raw") + 1])
                observed.append((command, manifest.read_text(encoding="utf-8")))
                return process

            with patch("tuxindrive.engine.subprocess.Popen", side_effect=spawn):
                count = SyncEngine("rclone")._apply_incremental_batch(job, [
                    FileChange("sessions/" + name, "local")
                    for name in ("one.jsonl", "two.jsonl", "auth.json", "temporary.lock")
                ], Path(temporary) / "job.log")
            self.assertEqual(count, 2)
            self.assertEqual(observed[0][1], "sessions/one.jsonl\nsessions/two.jsonl\n")
            for flag in ("--include", "--exclude", "--filter", "--max-size", "--max-age"):
                self.assertNotIn(flag, observed[0][0])

    def test_excluded_remote_deletion_never_touches_local_files(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            root = Path(temporary) / "source"
            root.mkdir()
            protected = root / "auth.json"
            protected.write_text("synthetic", encoding="utf-8")
            job = SyncJob("cloud", str(root), exclude_patterns=["auth.json"])
            with patch("tuxindrive.engine.subprocess.Popen") as spawn:
                count = SyncEngine("rclone")._apply_incremental_batch(
                    job, [FileChange("auth.json", "remote", deleted=True)], Path(temporary) / "job.log")
            self.assertEqual(count, 0)
            self.assertTrue(protected.exists())
            spawn.assert_not_called()

    def test_targeted_monitor_manifest_retains_bandwidth_but_not_filters(self):
        job = SyncJob("cloud", "/synthetic", include_patterns=["/sessions/**"], selective_max_age_days=1)
        monitor = ChangeMonitor(job, lambda: "rclone", lambda *_: True, lambda *_: None,
                                rclone_args=lambda: [*job.filter_args(), "--bwlimit", "2M"])
        self.assertEqual(monitor._manifest_args(), ["--bwlimit", "2M"])

    def test_control_operation_uses_group_aware_timeout(self):
        client = RcloneClient("rclone")
        with patch.object(client, "available", return_value=True), patch(
            "tuxindrive.rclone.run_process", side_effect=subprocess.TimeoutExpired("rclone", 1)
        ) as run:
            with self.assertRaisesRegex(RcloneError, "timed out"):
                client._run(["listremotes"], timeout=1)
        self.assertEqual(run.call_args.kwargs["timeout"], 1)

    def test_real_rclone_chat_backup_never_copies_excluded_files(self):
        executable = os.environ.get("TUXINDRIVE_TEST_RCLONE") or shutil.which("rclone")
        if not executable:
            self.skipTest("rclone executable is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            source, destination = Path(temporary) / "source", Path(temporary) / "backup"
            (source / "sessions").mkdir(parents=True)
            for relative in ("sessions/chat.jsonl", "sessions/auth.json", "sessions/temporary.lock", "unrelated.txt"):
                (source / relative).write_text("synthetic", encoding="utf-8")
            job = SyncJob("synthetic", str(source), mode=SyncMode.UPLOAD_ONLY,
                          version_history=False, include_patterns=["/sessions/**"],
                          exclude_patterns=["**/auth.json", "**/*.lock"])
            command = SyncEngine(executable).command_for_job(job)
            command[3] = str(destination)
            result = subprocess.run([*command, "--config", os.devnull], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("Using --filter is recommended", result.stderr)
            self.assertEqual([path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()],
                             ["sessions/chat.jsonl"])
