import json
import subprocess
import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxindrive.models import Provider
from tuxindrive.rclone import RcloneClient, RcloneError, google_scoped_remote


class RcloneClientTests(unittest.TestCase):
    def test_plain_config_is_encrypted_with_secret_service_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "rclone" / "rclone.conf"
            config.parent.mkdir(); config.write_text("[cloud]\ntype = drive\n", encoding="utf-8")
            helper = root / "helper"; helper.write_text("#!/bin/sh\n", encoding="utf-8"); helper.chmod(0o700)
            client = RcloneClient("/usr/bin/rclone")
            completed = subprocess.CompletedProcess([], 0, stdout="secret", stderr="")
            with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root), "TUXINDRIVE_PASSWORD_HELPER": str(helper)}, clear=False), patch("tuxindrive.rclone.subprocess.run", return_value=completed) as run:
                client._ensure_config_security()
                self.assertEqual(os.environ.get("RCLONE_PASSWORD_COMMAND"), str(helper))
            self.assertTrue((config.parent / ".tuxindrive-encrypted").is_file())
            self.assertIn("encryption", run.call_args_list[-1].args[0])

    def test_legacy_encryption_marker_and_helper_override_remain_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "rclone" / "rclone.conf"
            config.parent.mkdir()
            config.write_text("RCLONE_ENCRYPT_V0:\n", encoding="utf-8")
            (config.parent / ".tuxdrive-encrypted").touch()
            helper = root / "legacy-helper"
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o700)
            client = RcloneClient("/usr/bin/rclone")
            with patch.dict(
                os.environ,
                {"XDG_CONFIG_HOME": str(root), "TUXDRIVE_PASSWORD_HELPER": str(helper)},
                clear=False,
            ), patch("tuxindrive.rclone.subprocess.run") as run:
                client._ensure_config_security()
                self.assertEqual(os.environ.get("RCLONE_PASSWORD_COMMAND"), str(helper))
            run.assert_not_called()

    def test_noninteractive_question_is_parsed(self):
        output = json.dumps(
            {
                "State": "*oauth-islocal,",
                "Option": {
                    "Name": "config_is_local",
                    "Help": "Use browser?",
                    "Default": True,
                    "Examples": [{"Value": "true", "Help": "Yes"}],
                    "Required": False,
                    "IsPassword": False,
                    "Exclusive": True,
                },
                "Error": "",
            }
        )
        client = RcloneClient()
        with patch.object(
            client,
            "_run_oauth",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ):
            result = client.begin_oauth("work", Provider.GOOGLE_DRIVE)
        self.assertFalse(result.complete)
        self.assertEqual(result.question.name, "config_is_local")

    def test_oauth_address_in_use_error_is_concise(self):
        verbose = "Usage:\n" + ("flags\n" * 100) + "Fatal error: listen tcp 127.0.0.1:53682: bind: address already in use"
        message = RcloneClient._friendly_oauth_error(verbose)
        self.assertIn("callback port", message)
        self.assertLess(len(message), 220)

    def test_busy_callback_port_stops_before_starting_process(self):
        client = RcloneClient("/bin/true")
        with patch.object(client, "available", return_value=True), patch.object(
            client, "_callback_port_busy", return_value=True
        ), patch("tuxindrive.rclone.subprocess.Popen") as popen:
            with self.assertRaisesRegex(Exception, "already in use"):
                client.continue_oauth("work", "state", "true", "wizard-1")
        popen.assert_not_called()

    def test_remote_name_validation(self):
        with self.assertRaises(ValueError):
            RcloneClient._validate_remote_name("bad:name")

    def test_nested_cloud_folders_are_listed_for_tree_browser(self):
        client = RcloneClient()
        completed = subprocess.CompletedProcess(
            [], 0, stdout="Reports/\nProjects/\n", stderr=""
        )
        with patch.object(client, "_run", return_value=completed) as run:
            folders = client.list_directories("work", "Shared")
        self.assertEqual(folders, ["Projects", "Reports"])
        self.assertEqual(run.call_args.args[0][1], "work:Shared")

    def test_cloud_to_cloud_copy_is_non_destructive_and_previewed(self):
        client = RcloneClient()
        completed = subprocess.CompletedProcess([], 0, stdout="Transferred: 0 B", stderr="")
        with patch.object(client, "_run", return_value=completed) as run:
            client.copy_between_remotes(
                "source", "Team/Reports", "archive", "Imported",
                dry_run=True, bandwidth_args=["--bwlimit", "2M"],
            )
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["copy", "source:Team/Reports", "archive:Imported"])
        self.assertIn("--server-side-across-configs", command)
        self.assertIn("--dry-run", command)
        self.assertNotIn("sync", command)
        self.assertNotIn("delete", " ".join(command))

    def test_cloud_to_cloud_paths_reject_traversal(self):
        client = RcloneClient()
        with self.assertRaisesRegex(ValueError, "traversal"):
            client.copy_between_remotes("source", "../secret", "archive", "safe")

    def test_cloud_to_cloud_copy_requires_distinct_accounts(self):
        client = RcloneClient()
        with self.assertRaisesRegex(ValueError, "different accounts"):
            client.copy_between_remotes("same", "source", "same", "destination")

    def test_google_online_folder_url_uses_private_item_id_without_creating_share(self):
        client = RcloneClient()
        result = subprocess.CompletedProcess([], 0, stdout=json.dumps({"ID": "folder 123", "IsDir": True}), stderr="")
        with patch.object(client, "_run", return_value=result) as run:
            url, exact = client.online_url("google:Projects/Design", Provider.GOOGLE_DRIVE)
        self.assertTrue(exact)
        self.assertEqual(url, "https://drive.google.com/drive/folders/folder%20123")
        self.assertEqual(run.call_args.args[0][0], "lsjson")
        self.assertNotIn("link", run.call_args.args[0])

    def test_google_online_folder_falls_back_to_exact_parent_listing(self):
        client = RcloneClient()
        responses = [
            subprocess.CompletedProcess([], 0, stdout=json.dumps({"IsDir": True}), stderr=""),
            subprocess.CompletedProcess(
                [], 0,
                stdout=json.dumps([
                    {"Name": "Other", "ID": "other-id", "IsDir": True},
                    {"Name": "Design", "ID": "design-id", "IsDir": True},
                ]),
                stderr="",
            ),
        ]
        with patch.object(client, "_run", side_effect=responses) as run:
            url, exact = client.online_url(
                "google,team_drive=shared-1:Projects/Design", Provider.GOOGLE_DRIVE
            )
        self.assertTrue(exact)
        self.assertEqual(url, "https://drive.google.com/drive/folders/design-id")
        self.assertEqual(run.call_args_list[1].args[0][1], "google,team_drive=shared-1:Projects")

    def test_dropbox_online_folder_url_preserves_nested_path_without_public_link(self):
        client = RcloneClient()
        url, exact = client.online_url("drop:Team files/Design", Provider.DROPBOX)
        self.assertTrue(exact)
        self.assertEqual(url, "https://www.dropbox.com/home/Team%20files/Design")

    def test_google_locations_include_my_drive_shared_with_me_and_shared_drives(self):
        client = RcloneClient()
        output = json.dumps([{"id": "drive-123", "name": "Operations"}])
        with patch.object(
            client,
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout=output, stderr=""),
        ):
            locations = client.google_drive_locations("work")
        self.assertEqual(locations[0].name, "My Drive")
        self.assertEqual(locations[1].name, "Shared with me")
        self.assertTrue(any(item.name == "Shared Drive · Operations" for item in locations))
        shared = next(item for item in locations if item.key == "shared_drive:drive-123")
        self.assertIn("team_drive=drive-123", shared.scoped_remote)

    def test_google_scopes_override_a_preconfigured_shared_drive(self):
        self.assertIn("team_drive=", google_scoped_remote("work", "my_drive"))
        self.assertIn("root_folder_id=root", google_scoped_remote("work", "my_drive"))
        self.assertIn("shared_with_me=true", google_scoped_remote("work", "shared_with_me"))

    def test_cloud_git_vault_and_direct_peer_backends_are_available(self):
        self.assertEqual(len(Provider), 14)
        self.assertEqual(Provider.DROPBOX.rclone_type, "dropbox")
        self.assertEqual(Provider.BOX.rclone_type, "box")
        self.assertEqual(Provider.PCLOUD.rclone_type, "pcloud")
        self.assertEqual(Provider.MEGA.rclone_type, "mega")
        self.assertEqual(Provider.PROTON_DRIVE.rclone_type, "protondrive")
        self.assertEqual(Provider.NEXTCLOUD.rclone_type, "webdav")
        self.assertEqual(Provider.S3.rclone_type, "s3")
        self.assertEqual(Provider.WEBDAV.rclone_type, "webdav")
        self.assertEqual(Provider.SFTP.rclone_type, "sftp")
        self.assertEqual(Provider.GITHUB.rclone_type, "git")
        self.assertEqual(Provider.PEER.rclone_type, "sftp")

    def test_nextcloud_configuration_sets_webdav_vendor(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": temporary}, clear=False,
        ):
            client = RcloneClient()
            with patch.object(
                client,
                "_run_oauth",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ) as run:
                self.assertTrue(client.begin_oauth("cloud", Provider.NEXTCLOUD).complete)
        self.assertEqual(
            run.call_args.args[0][:6],
            ["config", "create", "cloud", "webdav", "vendor", "nextcloud"],
        )

    def test_proton_credentials_are_rejected_by_legacy_rclone_path(self):
        client = RcloneClient()
        with self.assertRaisesRegex(RcloneError, "official browser-authenticated CLI"):
            client.begin_oauth(
                "proton",
                Provider.PROTON_DRIVE,
                credentials={"password": "must-not-be-accepted"},
            )
        self.assertEqual(Provider.PROTON_DRIVE.credential_fields, ())

    def test_generic_webdav_configuration_sets_other_vendor(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CONFIG_HOME": temporary}, clear=False,
        ):
            client = RcloneClient()
            with patch.object(
                client,
                "_run_oauth",
                return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            ) as run:
                result = client.begin_oauth(
                    "files", Provider.WEBDAV,
                    credentials={"url": "https://dav.example.test", "user": "me"},
                )
        self.assertTrue(result.complete)
        self.assertEqual(
            run.call_args.args[0][:6],
            ["config", "create", "files", "webdav", "vendor", "other"],
        )

    def test_remote_is_listed_before_account_is_accepted(self):
        client = RcloneClient()
        with patch.object(
            client,
            "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ) as run:
            client.validate_remote("proton")
        self.assertEqual(
            run.call_args.args[0],
            ["lsf", "proton:", "--dirs-only", "--max-depth", "1"],
        )

    def test_legacy_rclone_has_no_proton_two_factor_prompt(self):
        self.assertFalse(hasattr(RcloneClient, "requires_proton_2fa"))

    def test_proton_credentials_cannot_be_updated_through_rclone(self):
        client = RcloneClient()
        with self.assertRaisesRegex(RcloneError, "cannot be entered into TuxInDrive"):
            client.update_credentials(
                "proton", Provider.PROTON_DRIVE, {"2fa": "must-not-be-accepted"}
            )

    def test_account_discovery_recognizes_added_backends(self):
        configured = {
            "drop": {"type": "dropbox"},
            "mega": {"type": "mega"},
            "next": {"type": "webdav", "vendor": "nextcloud"},
            "dav": {"type": "webdav", "vendor": "other"},
            "objects": {"type": "s3"},
            "server": {"type": "sftp"},
        }
        client = RcloneClient()
        with patch.object(
            client, "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(configured), stderr=""),
        ):
            accounts = client.discover_accounts()
        self.assertEqual(accounts["drop"], Provider.DROPBOX)
        self.assertEqual(accounts["mega"], Provider.MEGA)
        self.assertEqual(accounts["next"], Provider.NEXTCLOUD)
        self.assertEqual(accounts["dav"], Provider.WEBDAV)
        self.assertEqual(accounts["objects"], Provider.S3)
        self.assertEqual(accounts["server"], Provider.SFTP)

    def test_public_link_rejects_non_https_provider_output(self):
        client = RcloneClient()
        with patch.object(
            client, "_run",
            return_value=subprocess.CompletedProcess([], 0, stdout="http://unsafe.test/file", stderr=""),
        ):
            with self.assertRaisesRegex(RcloneError, "secure HTTPS"):
                client.public_link("cloud:file")


if __name__ == "__main__":
    unittest.main()
