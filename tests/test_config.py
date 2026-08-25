import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxindrive.config import ConfigStore, branded_root, cache_home, config_home, data_home
from tuxindrive.models import Account, AppConfig, ConflictPolicy, FolderGroup, PeerShare, Provider, SyncJob, SyncMode


class ConfigStoreTests(unittest.TestCase):
    def test_native_desktop_directories_are_used_outside_linux(self):
        with patch("tuxindrive.config.platform.system", return_value="Windows"), patch.dict(
            os.environ, {"APPDATA": "C:/Users/test/AppData/Roaming", "LOCALAPPDATA": "C:/Users/test/AppData/Local"}
        ):
            self.assertEqual(config_home(), Path("C:/Users/test/AppData/Roaming"))
            self.assertEqual(cache_home(), Path("C:/Users/test/AppData/Local/Cache"))
            self.assertEqual(data_home(), Path("C:/Users/test/AppData/Local"))
        with patch("tuxindrive.config.platform.system", return_value="Darwin"), patch(
            "tuxindrive.config.Path.home", return_value=Path("/Users/test")
        ):
            self.assertEqual(config_home(), Path("/Users/test/Library/Application Support"))
            self.assertEqual(cache_home(), Path("/Users/test/Library/Caches"))

    def test_existing_legacy_directory_is_used_without_copying_or_losing_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            legacy = root / "tuxdrive"
            legacy.mkdir()
            (legacy / "config.json").write_text("{}\n", encoding="utf-8")
            self.assertEqual(branded_root(root), legacy)
            self.assertFalse((root / "tuxindrive").exists())
            (root / "tuxindrive").mkdir()
            self.assertEqual(branded_root(root), root / "tuxindrive")

    def test_round_trip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "config.json"
            store = ConfigStore(path)
            value = AppConfig(
                accounts=[Account("google-main", Provider.GOOGLE_DRIVE, "Work Drive")],
                jobs=[
                    SyncJob(
                        account_remote="google-main",
                        local_path="/tmp/cloud",
                        remote_path="Projects",
                        remote_scope="google-main,team_drive=drive-1,root_folder_id=",
                        cloud_location_name="Shared Drive · Projects",
                        acknowledge_google_abuse=True,
                        mode=SyncMode.TWO_WAY,
                        conflict_policy=ConflictPolicy.KEEP_BOTH,
                    )
                ],
                peer_shares=[PeerShare("Direct", "/tmp/direct", "192.0.2.4", 22022, "ssh-ed25519 AAAA")],
                folder_groups=[FolderGroup("Customers", id="customers", collapsed=True)],
            )
            value.jobs[0].group_id = "customers"
            value.jobs[0].last_error_at = "2026-08-25T12:00:00+00:00"
            value.jobs[0].last_error_source = "Projects/report.pdf"
            value.jobs[0].last_error_log = "/tmp/job.log"
            store.save(value)
            loaded = store.load()
            self.assertEqual(loaded.accounts[0].provider, Provider.GOOGLE_DRIVE)
            self.assertEqual(
                loaded.jobs[0].remote_spec,
                "google-main,team_drive=drive-1,root_folder_id=:Projects",
            )
            self.assertEqual(loaded.jobs[0].cloud_location_name, "Shared Drive · Projects")
            self.assertTrue(loaded.jobs[0].acknowledge_google_abuse)
            self.assertEqual(loaded.peer_shares[0].advertised_host, "192.0.2.4")
            self.assertEqual(loaded.folder_groups[0].name, "Customers")
            self.assertTrue(loaded.folder_groups[0].collapsed)
            self.assertEqual(loaded.jobs[0].group_id, "customers")
            self.assertEqual(loaded.jobs[0].last_error_source, "Projects/report.pdf")
            self.assertEqual(loaded.jobs[0].last_error_log, "/tmp/job.log")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertFalse(FolderGroup.from_dict({"name": "Legacy group", "id": "legacy"}).collapsed)
            self.assertFalse(FolderGroup.from_dict({"name": "Invalid", "collapsed": "false"}).collapsed)

    def test_profile_settings_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ConfigStore(Path(temporary) / "config.json")
            value = AppConfig()
            value.settings.profile_remote = "google-main"
            value.settings.profile_last_backup = "2026-08-10T12:00:00+00:00"
            value.settings.language = "fr"
            value.settings.visual_theme = "midnight_sync"
            store.save(value)
            loaded = store.load()
        self.assertEqual(loaded.settings.profile_remote, "google-main")
        self.assertEqual(loaded.settings.profile_last_backup, "2026-08-10T12:00:00+00:00")
        self.assertEqual(loaded.settings.language, "fr")
        self.assertEqual(loaded.settings.visual_theme, "midnight_sync")

    def test_invalid_config_is_quarantined(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                ConfigStore(path).load()
            self.assertTrue(path.with_suffix(".json.invalid").exists())

    def test_unchanged_save_does_not_replace_or_touch_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            store = ConfigStore(path)
            config = AppConfig()
            store.save(config)
            first = path.stat()
            store.save(config)
            second = path.stat()
            path.chmod(0o644)
            store.save(config)
            repaired_mode = path.stat().st_mode & 0o777
        self.assertEqual(first.st_ino, second.st_ino)
        self.assertEqual(first.st_mtime_ns, second.st_mtime_ns)
        self.assertEqual(repaired_mode, 0o600)

    def test_cache_limits_from_manual_config_are_bounded(self):
        config = AppConfig.from_dict({"settings": {
            "streaming_cache_max_gib": -10,
            "streaming_cache_min_free_gib": "not-a-number",
        }})
        self.assertEqual(config.settings.streaming_cache_max_gib, 1)
        self.assertEqual(config.settings.streaming_cache_min_free_gib, 5)

    def test_network_usage_feature_flag_defaults_on_and_round_trips(self):
        self.assertTrue(AppConfig.from_dict({}).settings.show_network_usage)
        config = AppConfig.from_dict({"settings": {"show_network_usage": False}})
        self.assertFalse(config.settings.show_network_usage)
        self.assertFalse(config.to_dict()["settings"]["show_network_usage"])

    def test_live_activity_feature_flag_defaults_on_and_round_trips(self):
        self.assertTrue(AppConfig.from_dict({}).settings.show_live_activity_log)
        config = AppConfig.from_dict({"settings": {"show_live_activity_log": False}})
        self.assertFalse(config.settings.show_live_activity_log)
        self.assertFalse(config.to_dict()["settings"]["show_live_activity_log"])

    def test_global_bandwidth_limit_defaults_safely_and_is_validated(self):
        self.assertEqual(AppConfig.from_dict({}).settings.global_bandwidth_limit, "10M")
        self.assertTrue(AppConfig.from_dict({}).settings.automatic_bandwidth_control)
        self.assertEqual(AppConfig.from_dict({}).settings.bandwidth_headroom_percent, 20)
        configured = AppConfig.from_dict({"settings": {"global_bandwidth_limit": "2M:8M"}})
        self.assertEqual(configured.settings.global_bandwidth_limit, "2M:8M")
        protected = AppConfig.from_dict({"settings": {"bandwidth_headroom_percent": 999}})
        self.assertEqual(protected.settings.bandwidth_headroom_percent, 80)
        invalid = AppConfig.from_dict({"settings": {"global_bandwidth_limit": "fast"}})
        self.assertEqual(invalid.settings.global_bandwidth_limit, "10M")

    def test_former_mass_change_defaults_are_migrated_without_overwriting_custom_values(self):
        migrated = SyncJob.from_dict({
            "account_remote": "cloud",
            "local_path": "/tmp/cloud",
            "mass_change_limit": 200,
            "mass_change_percent": 25,
        })
        self.assertEqual((migrated.mass_change_limit, migrated.mass_change_percent), (500, 80))
        custom = SyncJob.from_dict({
            "account_remote": "cloud",
            "local_path": "/tmp/cloud",
            "mass_change_limit": 120,
            "mass_change_percent": 60,
        })
        self.assertEqual((custom.mass_change_limit, custom.mass_change_percent), (120, 60))

    def test_streaming_refresh_mode_is_validated(self):
        self.assertEqual(AppConfig.from_dict({}).settings.streaming_refresh_mode, "realtime")
        config = AppConfig.from_dict({"settings": {"streaming_refresh_mode": "balanced"}})
        self.assertEqual(config.settings.streaming_refresh_mode, "balanced")
        invalid = AppConfig.from_dict({"settings": {"streaming_refresh_mode": "unsafe"}})
        self.assertEqual(invalid.settings.streaming_refresh_mode, "realtime")


if __name__ == "__main__":
    unittest.main()
