from tests import signal_safety as _signal_safety  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxindrive.config import ConfigStore
from tuxindrive.migration import (
    LEGACY_PROFILE_PATH,
    PROFILE_PATH,
    MigrationError,
    ProfileManager,
    decrypt_profile,
    encrypt_profile,
)
from tuxindrive.models import Account, AppConfig, Provider, SyncJob


class FakeRclone:
    def __init__(self, root: Path):
        self.root = root
        self.config = root / "rclone.conf"
        self.config.write_text("[google]\ntype = drive\ntoken = secret\n", encoding="utf-8")

    def config_file(self):
        return self.config

    def _path(self, spec):
        remote, path = str(spec).split(":", 1)
        return self.root / "cloud" / remote / path

    def copy_to(self, source, destination):
        source_path = Path(source) if ":" not in str(source) else self._path(source)
        destination_path = Path(destination) if ":" not in str(destination) else self._path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        destination_path.write_bytes(source_path.read_bytes())

    def object_exists(self, spec):
        return self._path(spec).is_file()


class MigrationTests(unittest.TestCase):
    def test_pre_rebrand_encrypted_profile_format_remains_readable(self):
        with patch("tuxindrive.migration.FORMAT", "tuxdrive-encrypted-profile"):
            legacy = encrypt_profile({"legacy": True}, "a-secure-password")
        self.assertEqual(decrypt_profile(legacy, "a-secure-password"), {"legacy": True})

    def test_encryption_round_trip_and_wrong_password(self):
        data = encrypt_profile({"answer": 42}, "a-secure-password")
        self.assertEqual(decrypt_profile(data, "a-secure-password"), {"answer": 42})
        self.assertNotIn(b"answer", data)
        with self.assertRaises(MigrationError):
            decrypt_profile(data, "wrong-password")

    def test_tampering_is_rejected(self):
        data = json.loads(encrypt_profile({"safe": True}, "a-secure-password"))
        data["ciphertext"] = data["ciphertext"][:-2] + "AA"
        with self.assertRaises(MigrationError):
            decrypt_profile(json.dumps(data).encode(), "a-secure-password")

    def test_profile_upload_inspect_and_restore_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ConfigStore(root / "config.json")
            manager = ProfileManager(store, FakeRclone(root), root / "peer")
            config = AppConfig(
                accounts=[Account("google", Provider.GOOGLE_DRIVE, "Personal")],
                jobs=[SyncJob(account_remote="google", local_path="/tmp/Drive", remote_path="Projects")],
            )
            summary = manager.upload("google", config, "a-secure-password")
            self.assertTrue(manager.available("google"))
            self.assertEqual((summary.accounts, summary.jobs), (1, 1))
            restored = manager.restore(manager.download("google"), "a-secure-password")
            self.assertEqual(restored.jobs[0].remote_path, "Projects")
            self.assertEqual(store.load().accounts[0].display_name, "Personal")

    def test_profile_uses_visible_drive_path_and_reads_hidden_legacy_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rclone = FakeRclone(root)
            manager = ProfileManager(ConfigStore(root / "config.json"), rclone)
            data = manager.create_bytes(AppConfig(), "a-secure-password")
            visible = rclone._path(manager.remote_spec("google"))
            self.assertEqual(visible.relative_to(root / "cloud" / "google").as_posix(), PROFILE_PATH)
            legacy = rclone._path(manager.remote_spec("google", LEGACY_PROFILE_PATH))
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(data)
            self.assertTrue(manager.available("google"))
            self.assertEqual(manager.download("google"), data)
            self.assertEqual(visible.read_bytes(), data)

    def test_credentials_are_opt_in_and_restore_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            peer = root / "peer"
            peer.mkdir()
            (peer / "identity").write_text("private-key", encoding="utf-8")
            rclone = FakeRclone(root)
            store = ConfigStore(root / "config.json")
            manager = ProfileManager(store, rclone, peer)
            plain = manager.create_bytes(AppConfig(), "a-secure-password", False)
            self.assertNotIn("secrets", decrypt_profile(plain, "a-secure-password"))
            with patch("tuxindrive.migration.configuration_password", return_value="rclone-unlock-key"):
                protected = manager.create_bytes(AppConfig(), "a-secure-password", True)
            self.assertEqual(
                decrypt_profile(protected, "a-secure-password")["secrets"]["rclone_config_password"],
                "rclone-unlock-key",
            )
            rclone.config.write_text("changed", encoding="utf-8")
            (peer / "identity").unlink()
            with patch("tuxindrive.migration.store_configuration_password") as store_password:
                manager.restore(protected, "a-secure-password", restore_credentials=True)
            store_password.assert_called_once_with("rclone-unlock-key")
            self.assertIn("token = secret", rclone.config.read_text(encoding="utf-8"))
            self.assertEqual((peer / "identity").read_text(encoding="utf-8"), "private-key")
            self.assertEqual(rclone.config.stat().st_mode & 0o777, 0o600)

    def test_mobile_profile_contains_unlock_key_but_omits_peer_private_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            peer = root / "peer"
            peer.mkdir()
            (peer / "identity").write_text("private-key", encoding="utf-8")
            manager = ProfileManager(ConfigStore(root / "config.json"), FakeRclone(root), peer)
            with patch("tuxindrive.migration.configuration_password", return_value="mobile-unlock-key"):
                data = manager.create_mobile_bytes(AppConfig(), "a-secure-password")
            payload = decrypt_profile(data, "a-secure-password")
            self.assertTrue(payload["metadata"]["mobile_transfer"])
            self.assertEqual(payload["secrets"]["rclone_config_password"], "mobile-unlock-key")
            self.assertEqual(payload["secrets"]["peer_files"], {})

    def test_old_credential_profile_without_unlock_key_is_not_partially_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ConfigStore(root / "config.json")
            rclone = FakeRclone(root)
            manager = ProfileManager(store, rclone, root / "peer")
            data = encrypt_profile(
                {
                    "config": AppConfig().to_dict(),
                    "secrets": {"rclone_config": "Y29uZmln"},
                },
                "a-secure-password",
            )
            with self.assertRaisesRegex(MigrationError, "unlock key"):
                manager.restore(data, "a-secure-password", restore_credentials=True)
            self.assertEqual(rclone.config.read_text(encoding="utf-8"), "[google]\ntype = drive\ntoken = secret\n")

    def test_remote_name_and_short_password_are_rejected(self):
        with self.assertRaises(MigrationError):
            ProfileManager.remote_spec("bad:remote")
        with self.assertRaises(MigrationError):
            encrypt_profile({}, "short")


if __name__ == "__main__":
    unittest.main()
