import unittest

from tuxindrive.models import AppConfig


LEGACY_CONFIGS = {
    "0.26.0": {"settings": {"global_bandwidth_limit": "off"}},
    "0.26.6": {
        "settings": {"show_network_usage": False},
        "accounts": [{"provider": "dropbox", "remote": "dropbox", "display_name": "Dropbox"}],
    },
    "0.26.21": {
        "settings": {"automatic_bandwidth_control": True, "bandwidth_headroom_percent": 25},
        "unknown_future_field": "ignored",
    },
    "0.26.29": {
        "settings": {"search_content_indexing": True},
        "folder_groups": [{"id": "work", "name": "Work"}],
    },
}


class UpgradeMatrixTests(unittest.TestCase):
    def test_supported_historical_configs_migrate_and_round_trip(self):
        for version, source in LEGACY_CONFIGS.items():
            with self.subTest(version=version):
                migrated = AppConfig.from_dict(source)
                restored = AppConfig.from_dict(migrated.to_dict())
                self.assertEqual(restored.to_dict(), migrated.to_dict())
                self.assertGreaterEqual(migrated.settings.bandwidth_headroom_percent, 0)

    def test_new_privacy_feature_defaults_off_for_legacy_config(self):
        migrated = AppConfig.from_dict(LEGACY_CONFIGS["0.26.0"])
        self.assertFalse(migrated.settings.search_content_indexing)
