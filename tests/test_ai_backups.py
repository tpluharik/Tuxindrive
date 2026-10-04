import tempfile
import unittest
from pathlib import Path

from tuxindrive.ai_backups import (
    CODEX_CHAT_ONLY_INCLUDES,
    SECRET_EXCLUDES,
    build_backup_jobs,
    connector_by_key,
    connectors,
    safe_remote_component,
)
from tuxindrive.models import Account, AppConfig, Provider, SyncJob, SyncMode


class AIBackupTests(unittest.TestCase):
    def test_detects_supported_tools_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            (home / ".claude-target").mkdir()
            (home / ".claude").symlink_to(home / ".claude-target", target_is_directory=True)
            found = {item.key: item for item in connectors(home=home, system="Linux", environment={})}
            self.assertTrue(found["codex"].detected)
            self.assertFalse(found["claude"].detected)
            self.assertEqual(found["codex"].available_paths, ((home / ".codex").resolve(),))

    def test_codex_home_override_is_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "private-codex"
            root.mkdir()
            codex = connector_by_key(
                "codex", home=Path(directory), system="Linux",
                environment={"CODEX_HOME": str(root)},
            )
            self.assertEqual(codex.available_paths, (root.resolve(),))

    def test_backup_job_is_scheduled_one_way_and_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            codex = connector_by_key("codex", home=home, system="Linux", environment={})
            jobs = build_backup_jobs(
                [codex], account_remote="drive", remote_base="AI Backups/Personal",
                interval_minutes=30, hostname="work laptop",
            )
            self.assertEqual(len(jobs), 1)
            job = jobs[0]
            self.assertEqual(job.mode, SyncMode.UPLOAD_ONLY)
            self.assertEqual(job.interval_minutes, 30)
            self.assertFalse(job.realtime_sync)
            self.assertTrue(job.version_history)
            self.assertEqual(job.version_retention_days, 7)
            self.assertEqual(job.ai_connector, "codex")
            self.assertEqual(job.remote_path, "AI-Backups/Personal/work-laptop/codex")
            self.assertIn("auth.json", job.exclude_patterns)
            self.assertIn("config.toml", job.exclude_patterns)
            self.assertIn("node_repl/active_execs/**", job.exclude_patterns)
            self.assertIn(".tmp/**", job.exclude_patterns)
            self.assertIn("**/node_modules/**", job.exclude_patterns)
            self.assertIn("**/build/**", job.exclude_patterns)
            self.assertTrue(set(SECRET_EXCLUDES).issubset(job.exclude_patterns))

    def test_google_ai_backup_uses_explicit_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            codex = connector_by_key("codex", home=home, system="Linux", environment={})
            scope = "drive,team_drive=,root_folder_id=root,shared_with_me=false"
            job = build_backup_jobs(
                [codex], account_remote="drive", remote_scope=scope,
            )[0]
            self.assertEqual(job.remote_scope, scope)
            self.assertTrue(job.remote_spec.startswith(f"{scope}:"))

    def test_codex_chat_only_backup_excludes_non_chat_state(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            codex = connector_by_key("codex", home=home, system="Linux", environment={})
            job = build_backup_jobs(
                [codex], account_remote="drive", codex_chats_only=True,
            )[0]
            self.assertEqual(job.ai_backup_content, "chats")
            self.assertEqual(job.include_patterns, list(CODEX_CHAT_ONLY_INCLUDES))

            restored = AppConfig.from_dict(AppConfig(jobs=[job]).to_dict()).jobs[0]
            self.assertEqual(restored.ai_backup_content, "chats")

    def test_missing_tools_and_invalid_account_create_no_unsafe_job(self):
        with tempfile.TemporaryDirectory() as directory:
            codex = connector_by_key(
                "codex", home=Path(directory), system="Linux", environment={}
            )
            self.assertEqual(build_backup_jobs([codex], account_remote="drive"), [])
            with self.assertRaisesRegex(ValueError, "cloud account"):
                build_backup_jobs([codex], account_remote="")

    def test_connector_marker_round_trips_in_configuration(self):
        job = SyncJob(
            "drive", "/tmp/codex", ai_connector="codex", manual_only=True
        )
        restored = AppConfig.from_dict(AppConfig(jobs=[job]).to_dict()).jobs[0]
        self.assertTrue(restored.is_ai_backup)
        self.assertEqual(restored.ai_connector, "codex")
        self.assertTrue(restored.manual_only)
        self.assertFalse(restored.allows_automatic_runs)

    def test_manual_backup_is_not_scheduled_but_remains_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".codex").mkdir()
            codex = connector_by_key("codex", home=home, system="Linux", environment={})
            job = build_backup_jobs(
                [codex], account_remote="drive", manual_only=True,
                hostname="workstation",
            )[0]
            self.assertTrue(job.enabled)
            self.assertTrue(job.manual_only)
            self.assertFalse(job.allows_automatic_runs)
            self.assertEqual(job.name, "Codex manual backup")
            self.assertEqual(job.last_status, "Manual backup ready — use Sync now")

        ordinary = SyncJob("drive", "/tmp/files", manual_only=True)
        self.assertTrue(ordinary.allows_automatic_runs)

    def test_existing_ninety_day_ai_backup_migrates_to_seven_days(self):
        job = SyncJob(
            "drive", "/tmp/codex", ai_connector="codex",
            version_retention_days=90,
        )
        restored = AppConfig.from_dict(AppConfig(jobs=[job]).to_dict()).jobs[0]
        self.assertEqual(restored.version_retention_days, 7)

    def test_existing_codex_backup_gains_transient_runtime_excludes(self):
        job = SyncJob(
            "drive", "/tmp/codex", ai_connector="codex",
            exclude_patterns=["auth.json"],
        )
        restored = AppConfig.from_dict(AppConfig(jobs=[job]).to_dict()).jobs[0]
        self.assertIn("auth.json", restored.exclude_patterns)
        self.assertIn("node_repl/active_execs/**", restored.exclude_patterns)
        self.assertIn(".tmp/**", restored.exclude_patterns)

        legacy = AppConfig(jobs=[job]).to_dict()["jobs"][0]
        legacy.pop("exclude_patterns")
        restored_legacy = SyncJob.from_dict(legacy)
        self.assertIn("*.part", restored_legacy.exclude_patterns)
        self.assertIn("node_repl/active_execs/**", restored_legacy.exclude_patterns)

    def test_legacy_google_ai_backup_is_pinned_to_my_drive(self):
        account = Account("drive", Provider.GOOGLE_DRIVE, "Google Drive")
        job = SyncJob("drive", "/tmp/codex", ai_connector="codex")
        restored = AppConfig.from_dict(AppConfig(accounts=[account], jobs=[job]).to_dict())
        migrated = restored.jobs[0]
        self.assertEqual(
            migrated.remote_scope,
            "drive,team_drive=,root_folder_id=root,shared_with_me=false",
        )
        self.assertEqual(migrated.cloud_location_name, "My Drive")

    def test_explicit_google_ai_scope_is_preserved(self):
        account = Account("drive", Provider.GOOGLE_DRIVE, "Google Drive")
        job = SyncJob(
            "drive", "/tmp/codex", ai_connector="codex",
            remote_scope="drive,team_drive=shared-1,root_folder_id=",
        )
        restored = AppConfig.from_dict(AppConfig(accounts=[account], jobs=[job]).to_dict())
        self.assertEqual(restored.jobs[0].remote_scope, job.remote_scope)

    def test_remote_component_is_bounded_and_cannot_traverse(self):
        self.assertEqual(safe_remote_component("../../work laptop", "computer"), "work-laptop")
        self.assertLessEqual(len(safe_remote_component("x" * 200, "computer")), 80)


if __name__ == "__main__":
    unittest.main()
