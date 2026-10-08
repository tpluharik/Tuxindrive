from tests import signal_safety as _signal_safety  # noqa: F401

import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxindrive.models import Account, AppConfig, ConflictPolicy, Provider, SyncJob, SyncMode
from tuxindrive.engine import SyncEngine
from tuxindrive.proton import ProtonDriveClient, ProtonDriveError, ProtonNode, ProtonSyncResult, proton_path


class ProtonPathTests(unittest.TestCase):
    def test_paths_are_confined_to_my_files(self):
        self.assertEqual(proton_path(), "/my-files")
        self.assertEqual(proton_path("Work/Reports"), "/my-files/Work/Reports")
        for unsafe in ("../secret", "a/../../b", "a\nname"):
            with self.subTest(unsafe=unsafe), self.assertRaises(ProtonDriveError):
                proton_path(unsafe)

    def test_native_backend_survives_configuration_round_trip(self):
        original = AppConfig(accounts=[Account("proton-web", Provider.PROTON_DRIVE, "Private", backend="proton_cli")])
        restored = AppConfig.from_dict(original.to_dict())
        self.assertEqual(restored.accounts[0].backend, "proton_cli")
        self.assertEqual(restored.settings.proton_drive_path, "proton-drive")

    def test_legacy_account_defaults_to_rclone_backend(self):
        restored = Account.from_dict({
            "remote": "old-proton",
            "provider": "proton_drive",
            "display_name": "Old",
        })
        self.assertEqual(restored.backend, "rclone")

    def test_native_backend_is_accepted_only_for_proton(self):
        restored = Account.from_dict({
            "remote": "google-main",
            "provider": "google_drive",
            "display_name": "Work",
            "backend": "proton_cli",
        })
        self.assertEqual(restored.backend, "rclone")


class ProtonClientTests(unittest.TestCase):
    def setUp(self):
        self.client = ProtonDriveClient("/usr/bin/proton-drive")

    @staticmethod
    def process(stdout="", stderr="", returncode=0):
        process = MagicMock()
        process.communicate.return_value = (stdout, stderr)
        process.returncode = returncode
        process.pid = 1234
        process.poll.return_value = returncode
        return process

    def test_missing_official_cli_has_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_DATA_HOME": temporary}, clear=False,
        ):
            client = ProtonDriveClient("proton-drive")
            with patch("tuxindrive.proton.shutil.which", return_value=None), self.assertRaisesRegex(
                ProtonDriveError, "Install CLI and connect"
            ):
                client.resolve()

    @staticmethod
    def response(value: bytes, url: str, content_length: str | None = None):
        response = io.BytesIO(value)
        response.geturl = MagicMock(return_value=url)
        response.headers = {"Content-Length": content_length or str(len(value))}
        return response

    @staticmethod
    def manifest(binary: bytes, platform_name: str = "linux-x64") -> bytes:
        checksum = hashlib.sha512(binary).hexdigest()
        return (
            "<html><table><tr><td>linux/x64</td><td>"
            f"<a href='https://proton.me/download/drive/cli/0.7.0/{platform_name}/proton-drive'>download</a>"
            f"</td><td><code>{checksum}</code></td></tr></table></html>"
        ).encode("utf-8")

    def test_install_fetches_matching_architecture_and_verifies_checksum(self):
        binary = b"\x7fELF official proton cli"
        manifest = self.manifest(binary)
        manifest_url = "https://proton.me/download/drive/cli/index.html"
        binary_url = "https://proton.me/download/drive/cli/0.7.0/linux-x64/proton-drive"
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_DATA_HOME": temporary}
        ), patch("tuxindrive.proton.platform.machine", return_value="x86_64"), patch.object(
            self.client,
            "_open_url",
            side_effect=[
                self.response(manifest, manifest_url),
                self.response(binary, binary_url),
            ],
        ) as fetch:
            installed = self.client.install()
            self.assertEqual(installed.read_bytes(), binary)
            self.assertEqual(stat.S_IMODE(installed.stat().st_mode), 0o700)
            self.assertEqual(self.client.resolve(), str(installed))
        self.assertEqual(fetch.call_args_list[0].args[0], manifest_url)
        self.assertEqual(fetch.call_args_list[1].args[0], binary_url)

    def test_install_rejects_checksum_mismatch_and_keeps_existing_binary(self):
        old = b"existing verified executable"
        replacement = b"tampered download"
        manifest = self.manifest(b"expected download")
        manifest_url = "https://proton.me/download/drive/cli/index.html"
        binary_url = "https://proton.me/download/drive/cli/0.7.0/linux-x64/proton-drive"
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_DATA_HOME": temporary}
        ), patch("tuxindrive.proton.platform.machine", return_value="x86_64"):
            target = self.client.managed_path()
            target.parent.mkdir(parents=True)
            target.write_bytes(old)
            target.chmod(0o700)
            with patch.object(
                self.client,
                "_open_url",
                side_effect=[
                    self.response(manifest, manifest_url),
                    self.response(replacement, binary_url),
                ],
            ), self.assertRaisesRegex(ProtonDriveError, "checksum verification failed"):
                self.client.install()
            self.assertEqual(target.read_bytes(), old)
            self.assertEqual(list(target.parent.glob("*.download")), [])

    def test_manifest_must_remain_on_exact_official_location(self):
        response = self.response(
            b"<html></html>", "https://example.com/download/drive/cli/index.html"
        )
        with patch.object(self.client, "_open_url", return_value=response), self.assertRaisesRegex(
            ProtonDriveError, "untrusted location"
        ):
            self.client.install()

    def test_manifest_rejects_non_proton_binary_even_with_a_checksum(self):
        checksum = "a" * 128
        manifest = (
            "<table><tr><td><a href='https://example.com/linux-x64/proton-drive'>download</a></td>"
            f"<td>{checksum}</td></tr></table>"
        )
        with self.assertRaisesRegex(ProtonDriveError, "no unambiguous"):
            self.client._manifest_entry(
                manifest, "https://proton.me/download/drive/cli/index.html", "linux-x64"
            )

    def test_install_and_login_installs_only_when_missing(self):
        with patch.object(self.client, "available", return_value=False), patch.object(
            self.client, "install"
        ) as install, patch.object(self.client, "login") as login:
            self.client.install_and_login()
        install.assert_called_once_with()
        login.assert_called_once_with()

    def test_cancel_during_install_never_starts_browser_login(self):
        def cancel_install():
            self.client.cancel_login()
            raise ProtonDriveError("Proton CLI installation was cancelled")

        with patch.object(self.client, "available", return_value=False), patch.object(
            self.client, "install", side_effect=cancel_install
        ), patch.object(self.client, "login") as login, self.assertRaisesRegex(
            ProtonDriveError, "cancelled"
        ):
            self.client.install_and_login()
        login.assert_not_called()

    def test_environment_forces_secret_service_and_ignores_unsafe_override(self):
        with patch.dict(os.environ, {
            "PROTON_DRIVE_CACHE_DIR": "/tmp/plain-session",
            "PROTON_DRIVE_CREDENTIALS_STORE": "unsafe_file",
        }):
            environment = self.client._environment()
        self.assertNotIn("PROTON_DRIVE_CACHE_DIR", environment)
        self.assertEqual(environment["PROTON_DRIVE_CREDENTIALS_STORE"], "keychain")
        self.assertEqual(environment["PROTON_DRIVE_LOG_LEVEL"], "WARNING")

    def test_browser_login_never_passes_credentials(self):
        login = self.process(stdout="Authentication successful\n")
        listing = self.process(stdout="[]\n")
        with patch.object(self.client, "resolve", return_value="/usr/bin/proton-drive"), patch(
            "tuxindrive.proton.subprocess.Popen", side_effect=[login, listing]
        ) as popen:
            self.client.login()
        self.assertEqual(popen.call_args_list[0].args[0], ["/usr/bin/proton-drive", "auth", "login"])
        flattened = " ".join(popen.call_args_list[0].args[0]).lower()
        self.assertNotIn("password", flattened)
        self.assertNotIn("2fa", flattened)
        self.assertEqual(
            popen.call_args_list[1].args[0],
            ["/usr/bin/proton-drive", "filesystem", "list", "/my-files", "--json"],
        )

    def test_directory_listing_uses_json_and_rejects_unsafe_names(self):
        payload = json.dumps([
            {"name": "Documents", "type": "folder", "uid": "1"},
            {"name": "photo.jpg", "type": "file", "uid": "2"},
        ])
        with patch.object(self.client, "_json", return_value=json.loads(payload)) as command:
            self.assertEqual(self.client.list_directories("proton-web", ""), ["Documents"])
        self.assertEqual(command.call_args.args[0], ["filesystem", "list", "/my-files", "--json"])
        with patch.object(self.client, "_json", return_value=[{"name": "../escape", "type": "file"}]), self.assertRaises(
            ProtonDriveError
        ):
            self.client.list_directories("proton-web", "")

    def test_auth_error_redacts_url_and_session_value(self):
        detail = self.client._safe_error(
            "Open https://account.proton.me/auth?token=secret\nsession: super-secret"
        )
        self.assertNotIn("account.proton.me", detail)
        self.assertNotIn("super-secret", detail)
        self.assertIn("[authorization URL omitted]", detail)

    def test_session_expiry_is_actionable(self):
        failed = self.process(stderr="401 unauthorized: session expired", returncode=1)
        with patch.object(self.client, "resolve", return_value="/usr/bin/proton-drive"), patch(
            "tuxindrive.proton.subprocess.Popen", return_value=failed
        ), self.assertRaisesRegex(ProtonDriveError, "Reconnect in browser"):
            self.client.validate_session()

    def test_mass_change_guard_blocks_before_transfer(self):
        job = SyncJob(
            "proton-web", "/data/proton", initialized=True,
            mass_change_limit=2, mass_change_percent=60,
        )
        previous = {"local": {"a": "1", "b": "1", "c": "1"}, "remote": {}}
        with self.assertRaisesRegex(ProtonDriveError, "Protection paused"):
            self.client._guard_mass_change(
                job, {"a": "2", "b": "2", "c": "1"}, {}, previous
            )

    def test_mass_change_guard_does_not_pause_on_only_one_noisy_signal(self):
        job = SyncJob(
            "proton-web", "/data/proton", initialized=True,
            mass_change_limit=500, mass_change_percent=80,
        )
        previous = {"local": {f"file-{index}": "1" for index in range(390)}, "remote": {}}
        current = {key: "2" if index < 300 else value for index, (key, value) in enumerate(previous["local"].items())}
        self.client._guard_mass_change(job, current, {}, previous)

    def test_sync_rejects_streaming_without_running_cli(self):
        job = SyncJob("proton-web", "/data/proton", mode=SyncMode.VIRTUAL_DRIVE)
        with patch.object(self.client, "_run") as run, self.assertRaisesRegex(
            ProtonDriveError, "no mount API"
        ):
            self.client.sync(job)
        run.assert_not_called()

    def test_empty_upload_does_not_invoke_transfer(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "local"
            local.mkdir()
            job = SyncJob(
                "proton-web", str(local), mode=SyncMode.UPLOAD_ONLY,
                conflict_policy=ConflictPolicy.LOCAL_WINS,
            )
            with patch.dict(os.environ, {"XDG_DATA_HOME": temporary}), patch.object(
                self.client, "remote_tree", side_effect=[{}, {}]
            ) as remote_tree, patch.object(
                self.client, "_run"
            ) as run, patch.object(self.client, "_save_state"):
                result = self.client.sync(job)
        self.assertEqual(result.uploaded, 0)
        run.assert_not_called()
        self.assertEqual(remote_tree.call_count, 1)

    def test_remote_tree_reuses_unchanged_directory_subtree(self):
        folder = ProtonNode("folder", "/my-files/folder", True, "d:0:rev:1")
        child = ProtonNode("file.txt", "/my-files/folder/file.txt", False, "f:1:rev:2")
        with patch.object(self.client, "_list", side_effect=[[folder], [child], [folder]]) as listing:
            first = self.client.remote_tree(job_id="job")
            second = self.client.remote_tree(job_id="job")
        self.assertEqual(first, second)
        self.assertEqual(listing.call_count, 3)

    def test_nested_exclusions_are_not_uploaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "local"
            (local / "nested").mkdir(parents=True)
            (local / "nested" / "report.txt").write_text("ok", encoding="utf-8")
            (local / "nested" / "partial.part").write_text("temporary", encoding="utf-8")
            job = SyncJob("proton-web", str(local), mode=SyncMode.UPLOAD_ONLY)
            completed = MagicMock(stdout="[]", stderr="", returncode=0)
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(Path(temporary) / "state")}), patch.object(
                self.client, "remote_tree", side_effect=[{}, {}]
            ), patch.object(self.client, "_run", return_value=completed) as run, patch.object(
                self.client, "_save_state"
            ):
                self.client.sync(job)
        commands = [call.args[0] for call in run.call_args_list]
        flattened = "\n".join(" ".join(command) for command in commands)
        self.assertIn("report.txt", flattened)
        self.assertNotIn("partial.part", flattened)
        self.assertTrue(any(command[:2] == ["filesystem", "create-folder"] for command in commands))

    def test_download_rejects_existing_symlink_before_cli_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary) / "local"
            outside = Path(temporary) / "outside"
            local.mkdir()
            outside.mkdir()
            (local / "linked").symlink_to(outside, target_is_directory=True)
            tree = {
                "linked/file.txt": ProtonNode(
                    "file.txt", "/my-files/linked/file.txt", False, "fingerprint"
                )
            }
            job = SyncJob("proton-web", str(local), mode=SyncMode.DOWNLOAD_ONLY)
            with patch.object(self.client, "_run") as run, self.assertRaisesRegex(
                ProtonDriveError, "symbolic link"
            ):
                self.client._download_children(
                    tree, local, "replace", job, None, {"linked/file.txt"}
                )
        run.assert_not_called()

    def test_unchanged_files_are_not_transferred_again(self):
        job = SyncJob("proton-web", "/data/proton")
        local = {"report.txt": "f:10:100"}
        remote = {"report.txt": "f:10:sha1:uid"}
        uploads, downloads = self.client._transfer_plan(
            job, local, remote, {"local": local, "remote": remote}
        )
        self.assertEqual(uploads, {})
        self.assertEqual(downloads, {})

    def test_one_sided_deletions_are_restored(self):
        job = SyncJob("proton-web", "/data/proton")
        previous = {
            "local": {"local-deleted.txt": "f:1:1", "remote-deleted.txt": "f:1:1"},
            "remote": {"local-deleted.txt": "f:1:a", "remote-deleted.txt": "f:1:b"},
        }
        uploads, downloads = self.client._transfer_plan(
            job,
            {"remote-deleted.txt": "f:1:1"},
            {"local-deleted.txt": "f:1:a"},
            previous,
        )
        self.assertEqual(uploads, {"merge": {"remote-deleted.txt"}})
        self.assertEqual(downloads, {"replace": {"local-deleted.txt"}})

    def test_changed_both_sides_keeps_both_without_guessing_newer(self):
        job = SyncJob(
            "proton-web", "/data/proton", conflict_policy=ConflictPolicy.NEWER_WINS
        )
        uploads, downloads = self.client._transfer_plan(
            job,
            {"report.txt": "f:11:200"},
            {"report.txt": "f:12:new:uid"},
            {
                "local": {"report.txt": "f:10:100"},
                "remote": {"report.txt": "f:10:old:uid"},
            },
        )
        self.assertEqual(uploads, {"merge": {"report.txt"}})
        self.assertEqual(downloads, {"keep-both": {"report.txt"}})

    def test_sync_rejects_a_symlink_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            real = Path(temporary) / "real"
            linked = Path(temporary) / "linked"
            real.mkdir()
            linked.symlink_to(real, target_is_directory=True)
            job = SyncJob("proton-web", str(linked), mode=SyncMode.UPLOAD_ONLY)
            with patch.object(self.client, "_run") as run, self.assertRaisesRegex(
                ProtonDriveError, "root cannot be a symbolic link"
            ):
                self.client.sync(job)
        run.assert_not_called()


class ProtonEngineTests(unittest.TestCase):
    def test_native_job_uses_proton_adapter_not_rclone(self):
        proton = MagicMock(spec=ProtonDriveClient)
        proton.sync.return_value = ProtonSyncResult(1, 1, 3, 3)
        engine = SyncEngine("/usr/bin/rclone", proton=proton)
        account = Account(
            "proton-web", Provider.PROTON_DRIVE, "Private", backend="proton_cli"
        )
        with tempfile.TemporaryDirectory() as temporary:
            job = SyncJob("proton-web", temporary)
            engine.configure_jobs([job], [account])
            completed = []
            with patch("tuxindrive.engine.resolve_rclone") as rclone:
                engine._run_worker(
                    job, Path(temporary) / "proton.log", completed.append, False
                )
        rclone.assert_not_called()
        proton.sync.assert_called_once()
        self.assertTrue(completed[0].success)

    def test_native_streaming_job_fails_closed(self):
        proton = MagicMock(spec=ProtonDriveClient)
        engine = SyncEngine("/usr/bin/rclone", proton=proton)
        account = Account(
            "proton-web", Provider.PROTON_DRIVE, "Private", backend="proton_cli"
        )
        job = SyncJob("proton-web", "/data/proton", mode=SyncMode.VIRTUAL_DRIVE)
        engine.configure_jobs([job], [account])
        completed = []
        self.assertFalse(engine.run_async(job, completed.append))
        self.assertIn("no mount API", completed[0].message)
        proton.sync.assert_not_called()

    def test_native_job_never_starts_rclone_change_monitor(self):
        proton = MagicMock(spec=ProtonDriveClient)
        engine = SyncEngine("/usr/bin/rclone", proton=proton)
        account = Account(
            "proton-web", Provider.PROTON_DRIVE, "Private", backend="proton_cli"
        )
        job = SyncJob("proton-web", "/data/proton", initialized=True)
        engine.configure_jobs([job], [account])
        with patch("tuxindrive.engine.ChangeMonitor") as monitor:
            engine.start_callbacks(job, lambda _result: None, lambda _job: None)
        monitor.assert_not_called()

if __name__ == "__main__":
    unittest.main()
