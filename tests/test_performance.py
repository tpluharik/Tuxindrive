import json
import os
import platform
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tuxindrive.cache_manager import StreamingCacheManager
from tuxindrive.cache_manager import CacheCleanupResult
from tuxindrive.callbacks import ChangeMonitor, FileState, InotifyTreeMonitor
from tuxindrive.engine import SyncEngine
from tuxindrive.models import SyncJob, SyncMode


class PerformanceAndRecoveryTests(unittest.TestCase):
    def test_engine_reuses_durable_bisync_snapshot_after_restart(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_DATA_HOME": temporary},
        ):
            job = SyncJob("cloud", "/tmp/tuxindrive-local", id="resume", initialized=True)
            workdir = Path(temporary) / "tuxindrive" / "bisync" / job.id
            workdir.mkdir(parents=True)
            listing = (
                "# bisync listing v1\n"
                '- 5 - - 2026-08-27T10:00:00.000000000+0000 "ready.txt"\n'
            )
            (workdir / "state.path1.lst").write_text(listing, encoding="utf-8")
            (workdir / "state.path2.lst").write_text(listing, encoding="utf-8")
            engine = SyncEngine()
            with patch("tuxindrive.engine.ChangeMonitor") as monitor_class:
                engine.start_callbacks(job, lambda _result: None, lambda _job: None)
            initial = monitor_class.call_args.kwargs["initial_remote_snapshot"]
            initial_local = monitor_class.call_args.kwargs["initial_local_snapshot"]
        self.assertEqual(initial, {"ready.txt": FileState(5, "2026-08-27T10:00:00Z")})
        self.assertEqual(
            initial_local,
            {"ready.txt": FileState(5, "1787824800000000000")},
        )

    def test_restart_baseline_detects_local_changes_made_while_closed(self):
        class IdleEvents:
            def __init__(self, *_args):
                pass

            def read(self, timeout):
                from tuxindrive.callbacks import LocalEvents
                time.sleep(min(timeout, 0.01))
                return LocalEvents()

            def close(self):
                pass

        applied = []
        with tempfile.TemporaryDirectory() as temporary:
            changed = Path(temporary) / "changed.txt"
            changed.write_text("new", encoding="utf-8")
            job = SyncJob("restart", temporary, initialized=True)
            monitor = ChangeMonitor(
                job, lambda: "rclone",
                lambda _job, changes: applied.extend(changes) or True,
                lambda _job: None,
                initial_local_snapshot={"changed.txt": FileState(1, "1")},
                initial_remote_snapshot={},
                remote_backoff=(300,), event_factory=IdleEvents,
            )
            with patch.object(monitor, "remote_path_state", side_effect=ValueError), \
                    patch.object(monitor, "remote_snapshot", return_value={}):
                monitor.start()
                time.sleep(0.08)
                monitor.stop()
                monitor.thread.join(2)
        self.assertTrue(any(item.path == "changed.txt" for item in applied))

    def test_verified_bisync_baseline_avoids_immediate_remote_relist(self):
        class IdleEvents:
            def __init__(self, *_args):
                pass

            def read(self, timeout):
                from tuxindrive.callbacks import LocalEvents
                time.sleep(min(timeout, 0.01))
                return LocalEvents()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            job = SyncJob("cloud", temporary, initialized=True)
            monitor = ChangeMonitor(
                job, lambda: "rclone", lambda *_args: True, lambda _job: None,
                initial_remote_snapshot={"ready.txt": FileState(5, "2026-08-13T10:00:00Z")},
                remote_backoff=(300,), event_factory=IdleEvents,
            )
            with patch.object(monitor, "remote_snapshot") as remote_snapshot:
                monitor.start()
                time.sleep(0.05)
                monitor.stop()
                monitor.thread.join(2)
        remote_snapshot.assert_not_called()

    def test_identical_remote_metadata_scans_are_short_lived_and_shared(self):
        with tempfile.TemporaryDirectory() as temporary:
            job = SyncJob("shared", temporary, initialized=True)
            monitor_a = ChangeMonitor(job, lambda: "rclone", lambda *_args: True, lambda _job: None)
            monitor_b = ChangeMonitor(job, lambda: "rclone", lambda *_args: True, lambda _job: None)
            response = Mock(
                returncode=0,
                stdout='[{"Path":"ready.txt","Size":5,"ModTime":"2026-08-27T10:00:00Z"}]',
            )
            with patch("tuxindrive.callbacks.subprocess.run", return_value=response) as run:
                self.assertEqual(monitor_a.remote_snapshot(), monitor_b.remote_snapshot())
        self.assertEqual(run.call_count, 1)

    @unittest.skipUnless(platform.system() == "Linux", "inotify is Linux-specific")
    def test_idle_streaming_cache_skips_unchanged_recursive_rescan(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_CACHE_HOME": temporary},
        ):
            job = SyncJob("cloud", "/mnt/cloud", mode=SyncMode.VIRTUAL_DRIVE)
            data = Path(temporary) / "tuxindrive" / "vfs" / job.id / "vfs"
            data.mkdir(parents=True)
            engine = SyncEngine()
            with patch.object(
                engine.cache_manager, "enforce",
                return_value=CacheCleanupResult(job.id, examined_bytes=10),
            ) as enforce:
                engine.maintain_streaming_cache([job], 100, 0)
                engine.maintain_streaming_cache([job], 100, 0)
                self.assertEqual(enforce.call_count, 1)
                (data / "changed.bin").write_bytes(b"changed")
                deadline = time.monotonic() + 1
                while enforce.call_count == 1 and time.monotonic() < deadline:
                    engine.maintain_streaming_cache([job], 100, 0)
                    time.sleep(0.01)
                self.assertEqual(enforce.call_count, 2)
            engine.shutdown()

    @unittest.skipUnless(platform.system() == "Linux", "inotify is Linux-specific")
    def test_inotify_detects_file_save_without_recursive_rescan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            monitor = InotifyTreeMonitor(root, lambda _path: False)
            try:
                (root / "saved.txt").write_text("content", encoding="utf-8")
                deadline = time.monotonic() + 2
                paths = set()
                while time.monotonic() < deadline and "saved.txt" not in paths:
                    paths.update(monitor.read(0.2).paths)
            finally:
                monitor.close()
        self.assertIn("saved.txt", paths)

    def test_monitor_overflow_fails_closed_into_reconciliation(self):
        reconciled = threading.Event()

        class OverflowEvents:
            def __init__(self, *_args):
                self.sent = False

            def read(self, _timeout):
                from tuxindrive.callbacks import LocalEvents
                if not self.sent:
                    self.sent = True
                    return LocalEvents(overflow=True)
                time.sleep(0.01)
                return LocalEvents()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            job = SyncJob("cloud", temporary, initialized=True)
            monitor = ChangeMonitor(
                job, lambda: "rclone", lambda *_args: True,
                lambda _job: reconciled.set(), event_factory=OverflowEvents,
                remote_backoff=(300,),
            )
            with patch.object(monitor, "remote_snapshot", return_value={}):
                monitor.start()
                try:
                    self.assertTrue(reconciled.wait(2))
                finally:
                    monitor.stop()
                    monitor.thread.join(2)

    @unittest.skipUnless(platform.system() == "Linux", "inotify is Linux-specific")
    def test_change_during_slow_remote_baseline_is_not_lost(self):
        remote_started = threading.Event()
        release_remote = threading.Event()
        applied = threading.Event()
        captured = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            job = SyncJob("cloud", temporary, initialized=True)
            monitor = ChangeMonitor(
                job, lambda: "rclone",
                lambda _job, changes: captured.extend(changes) or applied.set() or True,
                lambda _job: None, remote_backoff=(300,),
            )

            def slow_remote():
                remote_started.set()
                release_remote.wait(2)
                return {}

            with patch.object(monitor, "remote_snapshot", side_effect=slow_remote):
                monitor.start()
                try:
                    self.assertTrue(remote_started.wait(1))
                    (root / "during-startup.txt").write_text("saved", encoding="utf-8")
                    release_remote.set()
                    self.assertTrue(applied.wait(2))
                finally:
                    monitor.stop()
                    monitor.thread.join(2)
        self.assertIn("during-startup.txt", {item.path for item in captured})

    def test_local_change_is_retried_after_remote_scan_failure(self):
        applied = threading.Event()

        class OneSave:
            def __init__(self, root, _excluded):
                self.root = root
                self.sent = False

            def read(self, timeout):
                from tuxindrive.callbacks import LocalEvents
                if not self.sent:
                    self.sent = True
                    (self.root / "retry.txt").write_text("saved", encoding="utf-8")
                    return LocalEvents(frozenset({"retry.txt"}))
                time.sleep(timeout)
                return LocalEvents()

            def close(self):
                pass

        with tempfile.TemporaryDirectory() as temporary:
            job = SyncJob("cloud", temporary, initialized=True)
            monitor = ChangeMonitor(
                job, lambda: "rclone",
                lambda _job, changes: applied.set() or bool(changes),
                lambda _job: None, local_poll_seconds=1, remote_poll_seconds=1,
                remote_backoff=(1,), event_factory=OneSave,
            )
            attempts = 0

            def intermittent_remote():
                nonlocal attempts
                attempts += 1
                if attempts == 2:
                    raise RuntimeError("offline")
                return {}

            with patch.object(monitor, "remote_snapshot", side_effect=intermittent_remote):
                monitor.start()
                try:
                    self.assertTrue(applied.wait(4))
                finally:
                    monitor.stop()
                    monitor.thread.join(2)

    def test_local_snapshot_excludes_symlinks_and_temporary_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "real.txt").write_text("ok", encoding="utf-8")
            (root / "draft.part").write_text("partial", encoding="utf-8")
            (root / "escape").symlink_to(Path(temporary).parent)
            job = SyncJob("cloud", temporary, initialized=True)
            monitor = ChangeMonitor(job, lambda: "rclone", lambda *_args: True, lambda _job: None)
            snapshot = monitor.local_snapshot()
        self.assertEqual(set(snapshot), {"real.txt"})

    def _cache_layout(self, temporary: str):
        job = SyncJob("cloud", "/mnt/cloud", mode=SyncMode.VIRTUAL_DRIVE, id="stream")
        root = Path(temporary) / "tuxindrive" / "vfs" / job.id
        data = root / "vfs" / "cloud"
        data.mkdir(parents=True)
        return job, root, data

    def test_cache_quota_never_evicts_pins_or_dirty_metadata(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            job, root, data = self._cache_layout(temporary)
            pinned = data / "pinned.bin"; pinned.write_bytes(b"p" * 16)
            dirty = data / "dirty.bin"; dirty.write_bytes(b"d" * 16)
            old = data / "old.bin"; old.write_bytes(b"o" * 16)
            marker = root / ".tuxdrive-pins" / "pin.json"
            marker.parent.mkdir()
            marker.write_text(json.dumps({"version": 2, "files": [{"path": "cloud/pinned.bin"}]}), encoding="utf-8")
            meta = root / "vfsMeta" / "cloud" / "dirty.bin"
            meta.parent.mkdir(parents=True); meta.write_text("dirty", encoding="utf-8")
            result = StreamingCacheManager(60).enforce(job, max_bytes=1, min_free_bytes=0, mounted=False)
            self.assertTrue(pinned.exists())
            self.assertTrue(dirty.exists())
            self.assertFalse(old.exists())
            self.assertEqual(result.released_files, 1)

    def test_mounted_cache_keeps_recent_stream_and_evicts_only_inactive_file(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            job, _root, data = self._cache_layout(temporary)
            old = data / "old.bin"; old.write_bytes(b"old" * 8)
            recent = data / "recent.bin"; recent.write_bytes(b"new" * 8)
            now = time.time()
            os.utime(old, (now - 120, now - 120))
            result = StreamingCacheManager(60).enforce(
                job, max_bytes=1, min_free_bytes=0, mounted=True, now=now
            )
            self.assertFalse(old.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(result.released_files, 1)

    def test_invalid_pin_marker_disables_eviction_for_entire_job(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            job, root, data = self._cache_layout(temporary)
            cached = data / "unknown.bin"; cached.write_bytes(b"content")
            marker = root / ".tuxdrive-pins" / "broken.json"
            marker.parent.mkdir(); marker.write_text("{broken", encoding="utf-8")
            result = StreamingCacheManager().enforce(job, max_bytes=1, min_free_bytes=0, mounted=False)
            self.assertTrue(cached.exists())
            self.assertEqual(result.skipped_uncertain, 1)

    def test_absolute_pin_marker_is_rejected_without_touching_external_path(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}):
            job, root, data = self._cache_layout(temporary)
            cached = data / "cached.bin"; cached.write_bytes(b"cache")
            external = Path(temporary) / "external.bin"; external.write_bytes(b"external")
            marker = root / ".tuxdrive-pins" / "absolute.json"
            marker.parent.mkdir()
            marker.write_text(json.dumps({"version": 2, "files": [{"path": str(external)}]}), encoding="utf-8")
            result = StreamingCacheManager().enforce(job, max_bytes=1, min_free_bytes=0, mounted=False)
            self.assertTrue(cached.exists())
            self.assertEqual(external.read_bytes(), b"external")
            self.assertEqual(result.skipped_uncertain, 1)

    def test_performance_hooks_are_wired_without_weakening_mount_policy(self):
        source = (Path(__file__).parents[1] / "src" / "tuxindrive" / "app.py").read_text(encoding="utf-8")
        service = (Path(__file__).parents[1] / "packaging" / "tuxindrive.service").read_text(encoding="utf-8")
        self.assertIn("not self.activity_panel.get_expanded()", source)
        self.assertIn("_run_scheduled_refresh", source)
        self.assertIn("maintain_streaming_cache", source)
        self.assertNotIn("network-online.target", service)


if __name__ == "__main__":
    unittest.main()
