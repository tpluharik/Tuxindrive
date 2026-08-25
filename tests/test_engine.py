import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from tuxindrive.bandwidth import GlobalBandwidthController
from tuxindrive.engine import JobResult, SyncEngine
from tuxindrive.callbacks import FileChange, FileState, changes_between, is_transient_path, normalize_remote_modtime
from tuxindrive.models import (
    ConflictPolicy, PeerRole, SyncJob, SyncMode, paths_overlap, safe_streaming_overlap,
)


class SyncEngineCommandTests(unittest.TestCase):
    def setUp(self):
        self.engine = SyncEngine("/usr/bin/rclone")

    def test_first_two_way_run_is_safe_resync(self):
        job = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            remote_path="Team",
            conflict_policy=ConflictPolicy.KEEP_BOTH,
            initialized=False,
            max_delete=25,
        )
        command = self.engine.command_for_job(job)
        self.assertEqual(command[:4], ["/usr/bin/rclone", "bisync", "/data/Drive", "google:Team"])
        self.assertIn("--resync", command)
        self.assertIn("pathname", command)
        self.assertIn("--track-renames", command)
        self.assertEqual(command[command.index("--track-renames-strategy") + 1], "modtime,leaf")
        self.assertEqual(command[command.index("--max-delete") + 1], "25")

    def test_later_run_does_not_resync(self):
        job = SyncJob(account_remote="one", local_path="/data/One", initialized=True)
        self.assertNotIn("--resync", self.engine.command_for_job(job))

    def test_bisync_state_uses_durable_application_data(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_DATA_HOME": f"{temporary}/data", "XDG_CACHE_HOME": f"{temporary}/cache"},
        ):
            job = SyncJob(account_remote="one", local_path="/data/One")
            command = self.engine.command_for_job(job)
        workdir = Path(command[command.index("--workdir") + 1])
        self.assertEqual(workdir, Path(temporary) / "data" / "tuxindrive" / "bisync" / job.id)

    def test_bisync_remote_listing_seeds_callback_without_timestamp_noise(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_DATA_HOME": temporary},
        ):
            job = SyncJob(account_remote="one", local_path="/data/One")
            workdir = self.engine._prepare_bisync_workdir(job)
            (workdir / "sync.path2.lst").write_text(
                '# bisync listing v1\n- 42 - - 2026-08-13T10:20:30.000000000+0000 "Folder/report.txt"\n',
                encoding="utf-8",
            )
            snapshot = self.engine._bisync_remote_snapshot(job)
        self.assertEqual(
            snapshot,
            {"Folder/report.txt": FileState(42, "2026-08-13T10:20:30Z")},
        )

    def test_remote_timestamp_formats_compare_equally(self):
        self.assertEqual(
            normalize_remote_modtime("2026-08-13T10:20:30.000000000+0000"),
            normalize_remote_modtime("2026-08-13T10:20:30Z"),
        )

    def test_remote_unicode_paths_compare_in_one_canonical_form(self):
        from tuxindrive.callbacks import normalize_remote_path
        self.assertEqual(normalize_remote_path("Cafe\u0301/report.txt"), "Caf\u00e9/report.txt")

    def test_legacy_bisync_state_is_migrated_out_of_cache(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_DATA_HOME": f"{temporary}/data", "XDG_CACHE_HOME": f"{temporary}/cache"},
        ):
            job = SyncJob(account_remote="one", local_path="/data/One", initialized=True)
            legacy = Path(temporary) / "cache" / "tuxindrive" / "bisync" / job.id
            legacy.mkdir(parents=True)
            (legacy / "sync.path1.lst").write_text("local", encoding="utf-8")
            (legacy / "sync.path2.lst").write_text("remote", encoding="utf-8")
            workdir = self.engine._prepare_bisync_workdir(job)
            self.assertTrue(self.engine._has_bisync_baselines(workdir))
            self.assertEqual((workdir / "sync.path1.lst").read_text(), "local")

    def test_missing_bisync_state_triggers_automatic_reinitialization(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_DATA_HOME": f"{temporary}/data", "XDG_CACHE_HOME": f"{temporary}/cache"},
        ):
            job = SyncJob(
                account_remote="one",
                local_path=f"{temporary}/local",
                initialized=True,
            )
            Path(job.local_path).mkdir()
            completed = []
            process = MagicMock()
            process.wait.return_value = 0
            with patch("tuxindrive.engine.resolve_rclone", return_value="/usr/bin/rclone"), \
                 patch("tuxindrive.engine.subprocess.run") as preview, \
                 patch("tuxindrive.engine.subprocess.Popen", return_value=process) as popen:
                self.engine._run_worker(
                    job, Path(temporary) / "sync.log", completed.append, False
                )
            preview.assert_not_called()
            command = popen.call_args.args[0]
            self.assertIn("--resync", command)
            self.assertEqual(command[command.index("--resync-mode") + 1], "newer")
            self.assertTrue(completed[0].success)
            self.assertIn("reinitialized automatically", completed[0].message)

    def test_preview_can_recover_if_bisync_state_disappears_during_run(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_DATA_HOME": f"{temporary}/data", "XDG_CACHE_HOME": f"{temporary}/cache"},
        ):
            job = SyncJob(
                account_remote="one",
                local_path=f"{temporary}/local",
                initialized=True,
            )
            Path(job.local_path).mkdir()
            workdir = self.engine._prepare_bisync_workdir(job)
            (workdir / "sync.path1.lst").write_text("local", encoding="utf-8")
            (workdir / "sync.path2.lst").write_text("remote", encoding="utf-8")
            completed = []
            process = MagicMock()
            process.wait.return_value = 0

            def fail_preview(_command, **kwargs):
                kwargs["stdout"].write(
                    "Bisync critical error: cannot find prior Path1 or Path2 listings\n"
                )
                return MagicMock(returncode=1)

            with patch("tuxindrive.engine.resolve_rclone", return_value="/usr/bin/rclone"), \
                 patch("tuxindrive.engine.subprocess.run", side_effect=fail_preview), \
                 patch("tuxindrive.engine.subprocess.Popen", return_value=process) as popen:
                self.engine._run_worker(
                    job, Path(temporary) / "sync.log", completed.append, False
                )
            self.assertIn("--resync", popen.call_args.args[0])
            self.assertTrue(completed[0].success)

    def test_authentication_preview_failure_does_not_force_resync(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_DATA_HOME": f"{temporary}/data", "XDG_CACHE_HOME": f"{temporary}/cache"},
        ):
            job = SyncJob(
                account_remote="one",
                local_path=f"{temporary}/local",
                initialized=True,
            )
            Path(job.local_path).mkdir()
            workdir = self.engine._prepare_bisync_workdir(job)
            (workdir / "sync.path1.lst").write_text("local", encoding="utf-8")
            (workdir / "sync.path2.lst").write_text("remote", encoding="utf-8")
            completed = []

            def fail_preview(_command, **kwargs):
                kwargs["stdout"].write("Failed to create file system: invalid_grant\n")
                return MagicMock(returncode=1)

            with patch("tuxindrive.engine.resolve_rclone", return_value="/usr/bin/rclone"), \
                 patch("tuxindrive.engine.subprocess.run", side_effect=fail_preview), \
                 patch("tuxindrive.engine.subprocess.Popen") as popen:
                self.engine._run_worker(
                    job, Path(temporary) / "sync.log", completed.append, False
                )
            popen.assert_not_called()
            self.assertFalse(completed[0].success)
            self.assertIn("safety preview could not be completed", completed[0].message)

    def test_peer_lease_metadata_is_never_synchronized_as_user_content(self):
        job = SyncJob(account_remote="peer-team", local_path="/data/Team", peer_leases=True)
        command = self.engine.command_for_job(job)
        self.assertIn("/.tuxdrive-leases/**", command)

    def test_google_location_scope_is_used_in_sync_command(self):
        job = SyncJob(
            account_remote="google",
            remote_scope="google,team_drive=abc,root_folder_id=",
            local_path="/data/Drive",
            remote_path="Reports",
        )
        command = self.engine.command_for_job(job)
        self.assertEqual(command[3], "google,team_drive=abc,root_folder_id=:Reports")

    def test_one_way_direction(self):
        download = SyncJob(
            account_remote="one",
            local_path="/data/One",
            remote_path="Docs",
            mode=SyncMode.DOWNLOAD_ONLY,
        )
        upload = SyncJob(
            account_remote="one",
            local_path="/data/One",
            remote_path="Docs",
            mode=SyncMode.UPLOAD_ONLY,
        )
        self.assertEqual(self.engine.command_for_job(download)[2:4], ["one:Docs", "/data/One"])
        self.assertEqual(self.engine.command_for_job(upload)[2:4], ["/data/One", "one:Docs"])

    def test_peer_roles_constrain_full_and_incremental_direction(self):
        read_only = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.DOWNLOAD_ONLY, peer_role=PeerRole.READ_ONLY)
        receive = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.DOWNLOAD_ONLY, peer_role=PeerRole.RECEIVE_ONLY)
        send = SyncJob(account_remote="peer", local_path="/data/Peer", mode=SyncMode.UPLOAD_ONLY, peer_role=PeerRole.SEND_ONLY)
        self.assertEqual(self.engine.command_for_job(read_only)[1], "copy")
        self.assertEqual(self.engine.command_for_job(receive)[1], "sync")
        self.assertIsNone(self.engine._incremental_command(read_only, FileChange("local.txt", "local", False)))
        self.assertIsNone(self.engine._incremental_command(send, FileChange("remote.txt", "remote", False)))
        self.assertEqual(self.engine._incremental_command(send, FileChange("local.txt", "local", False))[1], "copyto")

    def test_virtual_drive_uses_full_vfs_cache(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            command = self.engine.mount_command(job)
            self.assertEqual(command[:4], ["/usr/bin/rclone", "mount", "google:", "/mnt/Google"])
            self.assertEqual(command[command.index("--vfs-cache-mode") + 1], "full")
            self.assertEqual(command[command.index("--vfs-read-chunk-size") + 1], "8M")
            self.assertEqual(command[command.index("--vfs-cache-max-age") + 1], "87600h")
            self.assertEqual(command[command.index("--vfs-cache-max-size") + 1], "off")
            self.assertEqual(command[command.index("--vfs-cache-min-free-space") + 1], "off")
            self.assertIn("--vfs-fast-fingerprint", command)
            self.assertIn("--log-level", command)
            self.assertIn("--stats", command)

    def test_all_rclone_transfer_modes_honor_bandwidth_limit(self):
        job = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            bandwidth_limit="5M",
        )
        full = self.engine.command_for_job(job)
        incremental = self.engine._incremental_command(
            job, FileChange("report.pdf", "local")
        )
        job.mode = SyncMode.VIRTUAL_DRIVE
        streaming = self.engine.mount_command(job)
        for command in (full, incremental, streaming):
            self.assertEqual(command[command.index("--bwlimit") + 1], "5M")

    def test_global_bandwidth_limit_caps_every_rclone_mode(self):
        engine = SyncEngine(
            "/usr/bin/rclone", bandwidth=GlobalBandwidthController("3M")
        )
        job = SyncJob("google", "/data/Drive", bandwidth_limit="5M")
        commands = [
            engine.command_for_job(job),
            engine._incremental_command(job, FileChange("report.pdf", "local")),
        ]
        job.mode = SyncMode.VIRTUAL_DRIVE
        commands.append(engine.mount_command(job))
        for command in commands:
            self.assertEqual(command[command.index("--bwlimit") + 1], "3M")

    def test_automatic_limit_budgets_sync_with_all_streaming_drives(self):
        controller = GlobalBandwidthController(
            "10M", automatic=True, headroom_percent=20
        )
        engine = SyncEngine("/usr/bin/rclone", bandwidth=controller)
        streams = [
            SyncJob("google", f"/data/Stream{index}", mode=SyncMode.VIRTUAL_DRIVE)
            for index in range(2)
        ]
        engine.configure_jobs(streams)
        command = engine.command_for_job(SyncJob("google", "/data/Sync"))
        self.assertEqual(command[command.index("--bwlimit") + 1], "2097152B")

    def test_incremental_job_is_reserved_before_waiting_for_network_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = SyncEngine(
                "/usr/bin/rclone",
                bandwidth=GlobalBandwidthController("1M", max_active=1),
            )
            job = SyncJob("google", temporary)
            result: list[bool] = []
            with patch.object(engine, "_apply_incremental_unlocked", return_value=True):
                with engine.bandwidth.guard():
                    worker = threading.Thread(
                        target=lambda: result.append(
                            engine._apply_incremental(job, [], MagicMock())
                        )
                    )
                    worker.start()
                    for _attempt in range(100):
                        if job.id in engine.running_jobs:
                            break
                        time.sleep(0.001)
                    self.assertIn(job.id, engine.running_jobs)
                    self.assertFalse(engine.run_async(job, MagicMock()))
                worker.join(timeout=1)
            self.assertEqual(result, [True])
            self.assertNotIn(job.id, engine.running_jobs)

    def test_full_jobs_use_conservative_connection_fanout(self):
        command = self.engine.command_for_job(
            SyncJob(account_remote="google", local_path="/data/Drive")
        )
        self.assertEqual(command[command.index("--transfers") + 1], "2")
        self.assertEqual(command[command.index("--checkers") + 1], "4")

    def test_streaming_refresh_modes_change_only_polling_policy(self):
        job = SyncJob("google", "/data/stream", mode=SyncMode.VIRTUAL_DRIVE)
        self.engine.configure_streaming_refresh("balanced")
        balanced = self.engine.mount_command(job)
        self.assertEqual(balanced[balanced.index("--poll-interval") + 1], "2m")
        self.engine.configure_streaming_refresh("low_traffic")
        low = self.engine.mount_command(job)
        self.assertEqual(low[low.index("--poll-interval") + 1], "5m")

    def test_multiple_incremental_uploads_use_one_private_batch(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary}
        ):
            root = Path(temporary) / "local"
            root.mkdir()
            (root / "one.txt").write_text("1", encoding="utf-8")
            (root / "two.txt").write_text("2", encoding="utf-8")
            job = SyncJob("google", str(root), ransomware_protection=False)
            process = MagicMock()
            process.wait.return_value = 0
            callback = MagicMock()
            with patch("tuxindrive.engine.subprocess.Popen", return_value=process) as popen, \
                 patch.object(self.engine.recovery, "archive_incoming_changes"):
                result = self.engine._apply_incremental(
                    job,
                    [FileChange("one.txt", "local"), FileChange("two.txt", "local")],
                    callback,
                )
            self.assertTrue(result)
            self.assertEqual(popen.call_count, 1)
            command = popen.call_args.args[0]
            self.assertEqual(command[1], "copy")
            self.assertIn("--files-from-raw", command)

    def test_per_job_traffic_accumulates_sessions_and_payload(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "job.log"
            log.write_text(
                "[2026-08-14T10:00:00+00:00] Starting TuxInDrive 0.0 sync\n"
                "2026/08/14 12:00:01 INFO  : 1.5 MiB / 1.5 MiB, 100%, 1 MiB/s\n",
                encoding="utf-8",
            )
            self.engine._record_network("job", sessions=2)
            sessions, payload = self.engine.finalize_traffic("job", log)
        self.assertEqual(sessions, 2)
        self.assertEqual(payload, int(1.5 * 1024 ** 2))

    def test_pin_state_never_changes_live_mount_policy(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["projects/rail"],
            )
            command = self.engine.mount_command(job)
            job.offline_paths.clear()
            online_only_command = self.engine.mount_command(job)
        self.assertEqual(command, online_only_command)

    def test_offline_root_and_file_are_fully_hydrated_and_persisted(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            (root / "folder" / "one.bin").write_bytes(b"one")
            (root / "two.bin").write_bytes(b"two")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                remote_path="RemoteRoot",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            cached = Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" / "google" / "RemoteRoot" / "folder"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            (cached.parent / "two.bin").write_bytes(b"two")
            message = self.engine.set_offline(job, ".", True)
            verified = self.engine.verified_offline_rules(job)
        self.assertEqual(job.offline_paths, ["."])
        self.assertEqual(verified, {"."})
        self.assertIn("2 file(s)", message)
        self.assertIn("6 bytes", message)

    def test_offline_parent_rule_replaces_redundant_children(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder" / "child").mkdir(parents=True)
            (root / "folder" / "child" / "one.bin").write_bytes(b"one")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder/child"],
            )
            cached = Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" / "google" / "folder" / "child"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            self.engine.set_offline(job, "folder", True)
        self.assertEqual(job.offline_paths, ["folder"])

    def test_single_file_pin_waits_for_rclone_cache_publication(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            source = root / "folder" / "one.bin"
            source.write_bytes(b"one")
            job = SyncJob(
                account_remote="google,team_drive=,root_folder_id=root",
                local_path=str(root),
                remote_path="RemoteRoot",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            cached = (
                Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" /
                "google,team_drive=,root_folder_id=root" / "RemoteRoot" / "folder" / "one.bin"
            )

            def publish_cache() -> None:
                time.sleep(0.05)
                cached.parent.mkdir(parents=True)
                cached.write_bytes(b"one")

            publisher = threading.Thread(target=publish_cache)
            publisher.start()
            try:
                message = self.engine.set_offline(job, "folder/one.bin", True)
            finally:
                publisher.join()
            self.assertEqual(job.offline_paths, ["folder/one.bin"])
            self.assertEqual(self.engine.verified_offline_rules(job), {"folder/one.bin"})
            self.assertIn("1 file(s)", message)

    def test_single_file_pin_matches_real_mount_relative_rclone_cache(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            source = root / "one.bin"
            source.write_bytes(b"one")
            job = SyncJob(
                account_remote="google,team_drive=,root_folder_id=root",
                local_path=str(root),
                remote_path="Cloud/Subfolder",
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            # A mount rooted at remote:Cloud/Subfolder stores the selected
            # object relative to that mount. It need not repeat Cloud/Subfolder
            # in the per-job VFS cache path.
            cached = (
                Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" /
                "google,team_drive=,root_folder_id=root" / "one.bin"
            )
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"one")

            message = self.engine.set_offline(job, "one.bin", True)
            marker = json.loads(
                self.engine._pin_marker(job, "one.bin").read_text(encoding="utf-8")
            )

            self.assertEqual(job.offline_paths, ["one.bin"])
            self.assertEqual(self.engine.verified_offline_rules(job), {"one.bin"})
            self.assertEqual(marker["files"][0]["relative"], "one.bin")
            self.assertEqual(marker["version"], 2)
            self.assertIn("1 file(s)", message)

    def test_stalled_offline_reader_is_killed_retried_and_returns_an_error(self):
        class StalledStream:
            def fileno(self):
                return 7

            def readline(self):
                return ""

        class StalledProcess:
            next_pid = 4000

            def __init__(self):
                self.pid = self.next_pid
                StalledProcess.next_pid += 1
                self.returncode = None
                self.stdout = StalledStream()
                self.stderr = StalledStream()

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = -15
                return self.returncode

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "stalled.pdf"
            source.write_bytes(b"pdf")
            self.engine._OFFLINE_READ_INACTIVITY_TIMEOUT = 0.001
            self.engine._OFFLINE_READ_ATTEMPTS = 2
            processes = [StalledProcess(), StalledProcess()]
            with patch("tuxindrive.engine.subprocess.Popen", side_effect=processes) as popen, \
                 patch("tuxindrive.engine.selectors.DefaultSelector") as selector_type, \
                 patch("tuxindrive.engine.os.killpg") as killpg:
                selector = selector_type.return_value
                selector.select.return_value = []
                with self.assertRaisesRegex(RuntimeError, "cancelled the stalled download"):
                    self.engine._hydrate_file(source, "stalled.pdf")
            self.assertEqual(popen.call_count, 2)
            self.assertEqual(killpg.call_count, 2)

    def test_hydration_timeout_rolls_back_file_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "stalled.pdf").write_bytes(b"pdf")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["already.pdf"],
            )
            with patch.object(
                self.engine,
                "_hydrate_file",
                side_effect=RuntimeError("cancelled the stalled download"),
            ):
                with self.assertRaisesRegex(RuntimeError, "cancelled the stalled download"):
                    self.engine.set_offline(job, "stalled.pdf", True)
            self.assertEqual(job.offline_paths, ["already.pdf"])

    def test_version_one_pin_marker_survives_mount_relative_cache_upgrade(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Cloud",
                remote_path="Cloud/Subfolder",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder"],
            )
            cached = (
                Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" /
                "google" / "folder" / "one.bin"
            )
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"one")
            stat = cached.stat()
            marker = self.engine._pin_marker(job, "folder")
            marker.parent.mkdir(parents=True)
            marker.write_text(
                json.dumps({
                    "relative": "folder",
                    "files": [{
                        "path": cached.relative_to(
                            Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs"
                        ).as_posix(),
                        "size": stat.st_size,
                        "blocks": getattr(stat, "st_blocks", 0),
                    }],
                }),
                encoding="utf-8",
            )

            self.assertEqual(self.engine.verified_offline_rules(job), {"folder"})

    def test_online_only_child_overrides_parent_and_releases_matching_cache(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "folder").mkdir()
            (root / "folder" / "online.bin").write_bytes(b"online")
            (root / "folder" / "kept.bin").write_bytes(b"kept")
            job = SyncJob(
                account_remote="google",
                local_path=str(root),
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder"],
            )
            cache_files = Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" / "google" / "folder"
            cache_files.mkdir(parents=True)
            (cache_files / "online.bin").write_bytes(b"online")
            (cache_files / "kept.bin").write_bytes(b"kept")
            message = self.engine.set_offline(job, "folder/online.bin", False)
            self.assertFalse((cache_files / "online.bin").exists())
            self.assertTrue((cache_files / "kept.bin").exists())
        self.assertEqual(job.offline_paths, ["folder"])
        self.assertEqual(job.online_only_paths, ["folder/online.bin"])
        self.assertIn("Online only", message)

    def test_online_only_root_clears_rules_cache_and_markers(self):
        with tempfile.TemporaryDirectory() as temporary, tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            root = Path(temporary)
            (root / "one.bin").write_bytes(b"one")
            job = SyncJob(account_remote="google", local_path=str(root), mode=SyncMode.VIRTUAL_DRIVE)
            cached = Path(cache) / "tuxindrive" / "vfs" / job.id / "vfs" / "google"
            cached.mkdir(parents=True)
            (cached / "one.bin").write_bytes(b"one")
            self.engine.set_offline(job, ".", True)
            cache_root = Path(cache) / "tuxindrive" / "vfs" / job.id
            self.assertTrue((cache_root / ".tuxdrive-pins").exists())
            self.engine.set_offline(job, ".", False)
            self.assertFalse(cache_root.exists())
        self.assertEqual(job.offline_paths, [])
        self.assertEqual(job.online_only_paths, [])

    def test_old_pin_without_marker_is_not_downloaded_or_verified(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["."],
            )
            with patch.object(
                self.engine, "set_offline", side_effect=AssertionError("mount must not be read")
            ):
                verified = self.engine.verified_offline_rules(job)
        self.assertEqual(verified, set())

    def test_tampered_pin_marker_cannot_escape_cache_root(self):
        with tempfile.TemporaryDirectory() as cache, patch.dict(
            os.environ, {"XDG_CACHE_HOME": cache}
        ):
            job = SyncJob(
                account_remote="google",
                local_path="/mnt/Google",
                mode=SyncMode.VIRTUAL_DRIVE,
                offline_paths=["folder"],
            )
            marker = self.engine._pin_marker(job, "folder")
            marker.parent.mkdir(parents=True)
            marker.write_text(
                '{"relative":"folder","files":[{"path":"../../outside","size":1,"blocks":1}]}',
                encoding="utf-8",
            )
            self.assertEqual(self.engine.verified_offline_rules(job), set())

    def test_restart_mount_applies_changed_vfs_policy(self):
        job = SyncJob(
            account_remote="google",
            local_path="/mnt/Google",
            mode=SyncMode.VIRTUAL_DRIVE,
            offline_paths=["folder"],
        )
        expected = JobResult(job.id, True, "mounted", Path("/tmp/mount.log"))
        callback = Mock()
        with patch.object(self.engine, "stop_mount", return_value=True) as stop, \
             patch.object(self.engine, "start_mount", return_value=expected) as start:
            result = self.engine.restart_mount(job, callback)
        self.assertIs(result, expected)
        stop.assert_called_once_with(job)
        start.assert_called_once_with(job)

    def test_failed_offline_symlink_hydration_rolls_back_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root.parent / "outside-tuxindrive-test"
            outside.write_text("secret", encoding="utf-8")
            try:
                (root / "escape").symlink_to(outside)
                job = SyncJob(account_remote="google", local_path=str(root), mode=SyncMode.VIRTUAL_DRIVE)
                with self.assertRaises(ValueError):
                    self.engine.set_offline(job, "escape", True)
                self.assertEqual(job.offline_paths, [])
            finally:
                outside.unlink(missing_ok=True)

    def test_overlapping_sync_and_streaming_paths_are_detected(self):
        self.assertTrue(paths_overlap("/data/TuxInDrive", "/data/TuxInDrive/CEVRO"))
        self.assertTrue(paths_overlap("/data/TuxInDrive/CEVRO", "/data/TuxInDrive"))
        self.assertFalse(paths_overlap("/data/TuxInDrive", "/data/StreamingDrive"))

    def test_streaming_child_is_safe_and_automatically_excluded_from_parent(self):
        parent = SyncJob(account_remote="google", local_path="/data/TuxInDrive")
        streamed = SyncJob(
            account_remote="google",
            local_path="/data/TuxInDrive/Online",
            mode=SyncMode.VIRTUAL_DRIVE,
        )
        self.assertTrue(safe_streaming_overlap(parent, streamed))
        self.assertFalse(safe_streaming_overlap(streamed, SyncJob(
            account_remote="google",
            local_path="/data/TuxInDrive/Online/Downloaded",
        )))
        self.engine.configure_jobs([parent, streamed])
        command = self.engine.command_for_job(parent)
        self.assertIn("/Online/**", command)

    def test_unchanged_job_layout_skips_quadratic_exclusion_rebuild(self):
        parent = SyncJob(account_remote="google", local_path="/data/TuxInDrive")
        streamed = SyncJob(
            account_remote="google", local_path="/data/TuxInDrive/Online",
            mode=SyncMode.VIRTUAL_DRIVE,
        )
        self.engine.configure_jobs([parent, streamed])
        original = self.engine._protected_patterns
        self.engine.configure_jobs([parent, streamed])
        self.assertIs(self.engine._protected_patterns, original)
        streamed.local_path = "/data/TuxInDrive/Other"
        self.engine.configure_jobs([parent, streamed])
        self.assertIsNot(self.engine._protected_patterns, original)

    def test_remote_backoff_respects_provider_characteristics(self):
        from tuxindrive.models import Account, Provider
        proton = Account("proton", Provider.PROTON_DRIVE, "Private")
        peer = Account("peer", Provider.PEER, "LAN")
        proton_job = SyncJob("proton", "/data/proton")
        peer_job = SyncJob("peer", "/data/peer")
        self.engine.configure_jobs([proton_job, peer_job], [proton, peer])
        self.assertEqual(self.engine._remote_backoffs[proton_job.id], (60.0, 120.0, 300.0, 600.0))
        self.assertEqual(self.engine._remote_backoffs[peer_job.id], (10.0, 30.0, 60.0, 120.0))

    def test_streaming_mount_rejects_a_nonempty_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            mountpoint = Path(temporary) / "mount"
            mountpoint.mkdir()
            (mountpoint / "existing").mkdir()
            job = SyncJob(
                account_remote="google",
                local_path=str(mountpoint),
                mode=SyncMode.VIRTUAL_DRIVE,
            )
            result = self.engine.start_mount(job)
        self.assertFalse(result.success)
        self.assertIn("empty local folder", result.message)

    def test_startup_recovers_only_untracked_stale_streaming_mounts(self):
        stale = SyncJob(account_remote="google", local_path="/data/stale", mode=SyncMode.VIRTUAL_DRIVE)
        normal = SyncJob(account_remote="google", local_path="/data/normal")
        with patch("tuxindrive.engine.os.path.ismount", side_effect=lambda value: str(value) == "/data/stale"), \
             patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            recovered = self.engine.recover_stale_mounts([normal, stale])
        self.assertEqual(recovered, [stale.id])
        unmount.assert_called_once_with(stale.local)

    def test_unexpected_stream_exit_detaches_kernel_mount_before_retry(self):
        job = SyncJob(account_remote="google", local_path="/data/stream", mode=SyncMode.VIRTUAL_DRIVE)
        process = MagicMock()
        process.wait.return_value = 7
        self.engine._mounts[job.id] = process
        callback = MagicMock()
        with patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            self.engine._watch_mount(job, process, Path("/tmp/stream.log"), callback)
        unmount.assert_called_once_with(job.local)
        self.assertTrue(callback.call_args.args[0].mount_lost)

    def test_orderly_shutdown_also_detaches_streaming_mount(self):
        job = SyncJob(account_remote="google", local_path="/data/stream", mode=SyncMode.VIRTUAL_DRIVE)
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        self.engine._mounts[job.id] = process
        self.engine._mount_paths[job.id] = job.local
        with patch("tuxindrive.engine.os.killpg"), \
             patch.object(self.engine, "_unmount_path", return_value=True) as unmount:
            self.engine.shutdown()
        unmount.assert_called_once_with(job.local)

    def test_failure_summary_surfaces_fatal_detail(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = os.path.join(temporary, "sync.log")
            with open(log, "w", encoding="utf-8") as handle:
                handle.write("Usage:\nFatal error: unknown flag: --resilient\n")
            message = self.engine._failure_summary(Path(log), 1)
        self.assertEqual(message, "Synchronization failed: unknown flag: --resilient")

    def test_google_abuse_failure_is_actionable_and_requires_recovery(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "sync.log"
            log.write_text(
                "ERROR : myweb/handy_switch.zip: Failed to copy: cannotDownloadAbusiveFile\n"
                "ERROR : Bisync aborted. Must run --resync to recover.\n",
                encoding="utf-8",
            )
            message = self.engine._failure_summary(log, 7)
            recovery = self.engine._requires_resync(log)
            blocked = self.engine._blocked_google_path(log)
        self.assertIn("myweb/handy_switch.zip", message)
        self.assertIn("suspected malware", message)
        self.assertTrue(recovery)
        self.assertEqual(blocked, "myweb/handy_switch.zip")

    def test_google_abuse_acknowledgement_is_opt_in(self):
        safe = SyncJob(account_remote="google", local_path="/data/Drive")
        allowed = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            acknowledge_google_abuse=True,
        )
        self.assertNotIn("--drive-acknowledge-abuse", self.engine.command_for_job(safe))
        self.assertIn("--drive-acknowledge-abuse", self.engine.command_for_job(allowed))

    def test_async_jobs_are_globally_bounded_and_queued_jobs_are_visible(self):
        entered = 0
        maximum = 0
        completed = []
        lock = threading.Lock()
        two_started = threading.Event()
        release = threading.Event()

        def worker(job, log_path, callback, dry_run):
            nonlocal entered, maximum
            with lock:
                entered += 1
                maximum = max(maximum, entered)
                if entered == 2:
                    two_started.set()
            release.wait(3)
            callback(JobResult(job.id, True, "done", log_path))
            with lock:
                entered -= 1

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            self.engine, "_run_worker", side_effect=worker
        ):
            jobs = [SyncJob("google", str(Path(temporary) / str(index))) for index in range(3)]
            for job in jobs:
                self.assertTrue(self.engine.run_async(job, completed.append))
            self.assertTrue(two_started.wait(2))
            self.assertEqual(self.engine.running_jobs, {job.id for job in jobs})
            self.assertEqual(maximum, 2)
            release.set()
            deadline = time.monotonic() + 3
            while len(completed) < 3 and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertEqual(len(completed), 3)
        self.assertEqual(maximum, 2)

    def test_worker_replaces_incompatible_rclone_before_launch(self):
        job = SyncJob(account_remote="google", local_path="/data/Drive")
        completed = []
        process = MagicMock()
        process.wait.return_value = 0
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.engine.resolve_rclone", return_value=None
        ), patch("tuxindrive.engine.install_rclone", return_value="/private/rclone"), patch(
            "tuxindrive.engine.subprocess.Popen", return_value=process
        ) as popen:
            self.engine._run_worker(
                job, Path(temporary) / "sync.log", completed.append, False
            )
        self.assertEqual(self.engine.rclone_path, "/private/rclone")
        self.assertEqual(popen.call_args.args[0][0], "/private/rclone")
        self.assertTrue(completed[0].success)

    def test_incremental_commands_transfer_only_the_changed_path(self):
        job = SyncJob(account_remote="google", local_path="/data/Drive", remote_path="Docs")
        upload = self.engine._incremental_command(
            job, FileChange("Reports/result.pdf", "local")
        )
        download = self.engine._incremental_command(
            job, FileChange("Notes/today.txt", "remote")
        )
        deletion = self.engine._incremental_command(
            job, FileChange("old.txt", "local", deleted=True)
        )
        self.assertEqual(
            upload,
            ["/usr/bin/rclone", "copyto", "/data/Drive/Reports/result.pdf", "google:Docs/Reports/result.pdf"],
        )
        self.assertEqual(download[1], "copyto")
        self.assertEqual(download[-1], "/data/Drive/Notes/today.txt")
        self.assertEqual(deletion[1], "deletefile")

    def test_selective_rules_cover_full_and_incremental_transfers(self):
        job = SyncJob(
            account_remote="google",
            local_path="/data/Drive",
            selective_extensions=["pdf"],
            selective_max_size_mb=8,
            selective_max_age_days=30,
        )
        command = self.engine.command_for_job(job)
        self.assertIn("*.pdf", command)
        self.assertEqual(command[command.index("--max-size") + 1], "8M")
        self.assertEqual(command[command.index("--max-age") + 1], "30d")
        self.assertIsNotNone(
            self.engine._incremental_command(job, FileChange("report.pdf", "local"))
        )
        self.assertIsNone(
            self.engine._incremental_command(job, FileChange("archive.zip", "local"))
        )

    def test_callback_delta_contains_only_created_changed_and_deleted_paths(self):
        previous = {
            "same.txt": FileState(1, "1"),
            "changed.txt": FileState(1, "1"),
            "deleted.txt": FileState(1, "1"),
        }
        current = {
            "same.txt": FileState(1, "1"),
            "changed.txt": FileState(2, "2"),
            "created.txt": FileState(3, "3"),
        }
        changes = changes_between(previous, current, "local")
        self.assertEqual(
            [(item.path, item.deleted) for item in changes],
            [("changed.txt", False), ("created.txt", False), ("deleted.txt", True)],
        )

    def test_office_lock_and_partial_files_are_never_synchronized(self):
        self.assertTrue(is_transient_path(".~lock.Cloud.pptx#"))
        self.assertTrue(is_transient_path("folder/~$Budget.xlsx"))
        self.assertTrue(is_transient_path("download.part"))
        job = SyncJob(account_remote="google", local_path="/data/Drive")
        self.assertIsNone(
            self.engine._incremental_command(
                job, FileChange(".~lock.Cloud.pptx#", "local")
            )
        )
        command = self.engine.command_for_job(job)
        self.assertIn(".~lock.*#", command)


if __name__ == "__main__":
    unittest.main()
