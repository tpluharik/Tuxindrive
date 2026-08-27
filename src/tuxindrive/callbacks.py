from __future__ import annotations

import ctypes
import contextlib
import errno
import fnmatch
import json
import os
import platform
import re
import selectors
import struct
import subprocess
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager

from .models import SyncJob, SyncMode


TRANSIENT_PATTERNS = (
    ".~lock.*#", "~$*", ".goutputstream-*", ".nfs*", "*.part",
    "*.partial", "*.crdownload", "*.swp", "*.swx", "*~",
)

_REMOTE_METADATA_CACHE_LOCK = threading.Lock()
_REMOTE_METADATA_CACHE: dict[
    tuple[str, str, tuple[str, ...], tuple[str, ...]],
    tuple[float, dict[str, "FileState"]],
] = {}
_REMOTE_METADATA_CACHE_SECONDS = 5.0


def is_transient_path(relative: str) -> bool:
    return any(
        fnmatch.fnmatch(part, pattern)
        for part in Path(relative).parts
        for pattern in TRANSIENT_PATTERNS
    )


def normalize_remote_modtime(value: str) -> str:
    """Canonicalize rclone JSON and bisync-listing timestamp spellings."""
    match = re.fullmatch(
        r"(.+?)(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})", value.strip()
    )
    if not match:
        return value.strip()
    base, fraction, zone = match.groups()
    fraction = (fraction or "").rstrip("0")
    if zone in {"+0000", "+00:00"}:
        zone = "Z"
    elif len(zone) == 5:
        zone = f"{zone[:3]}:{zone[3:]}"
    return base + (f".{fraction}" if fraction else "") + zone


def normalize_remote_path(value: str) -> str:
    """Use one Unicode spelling for rclone listings and provider JSON paths."""
    return unicodedata.normalize("NFC", value.replace("\\", "/").strip("/"))


@dataclass(frozen=True, slots=True)
class FileState:
    size: int
    modified: str


@dataclass(frozen=True, slots=True)
class FileChange:
    path: str
    side: str
    deleted: bool = False


def changes_between(
    previous: dict[str, FileState], current: dict[str, FileState], side: str
) -> list[FileChange]:
    return [
        FileChange(path, side, path not in current)
        for path in sorted(previous.keys() | current.keys())
        if previous.get(path) != current.get(path)
    ]


@dataclass(frozen=True, slots=True)
class LocalEvents:
    paths: frozenset[str] = frozenset()
    overflow: bool = False
    rescan: bool = False


class InotifyTreeMonitor:
    """Bounded kernel-backed recursive monitor.

    The kernel queue is the bound. IN_Q_OVERFLOW is surfaced explicitly so
    callers can fail closed into a full reconciliation instead of losing a
    change silently. Directory topology changes request a local rescan because
    a single rename event cannot safely describe every descendant.
    """

    _EVENT = struct.Struct("iIII")
    _NONBLOCK = getattr(os, "O_NONBLOCK", 0x800)
    _CLOEXEC = getattr(os, "O_CLOEXEC", 0x80000)
    _MODIFY = 0x00000002
    _ATTRIB = 0x00000004
    _CLOSE_WRITE = 0x00000008
    _MOVED_FROM = 0x00000040
    _MOVED_TO = 0x00000080
    _CREATE = 0x00000100
    _DELETE = 0x00000200
    _DELETE_SELF = 0x00000400
    _MOVE_SELF = 0x00000800
    _Q_OVERFLOW = 0x00004000
    _IGNORED = 0x00008000
    _ONLYDIR = 0x01000000
    _DONT_FOLLOW = 0x02000000
    _ISDIR = 0x40000000
    _WATCH_MASK = (
        _MODIFY | _ATTRIB | _CLOSE_WRITE | _MOVED_FROM | _MOVED_TO |
        _CREATE | _DELETE | _DELETE_SELF | _MOVE_SELF
    )

    def __init__(self, root: Path, excluded: Callable[[str], bool]) -> None:
        if platform.system() != "Linux":
            raise OSError(errno.ENOSYS, "inotify is available only on Linux")
        libc = ctypes.CDLL(None, use_errno=True)
        init = libc.inotify_init1
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        self._add = libc.inotify_add_watch
        self._add.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        self._add.restype = ctypes.c_int
        self.fd = init(self._NONBLOCK | self._CLOEXEC)
        if self.fd < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        self.root = root.resolve(strict=False)
        self.excluded = excluded
        self._watches: dict[int, Path] = {}
        self._selector = selectors.DefaultSelector()
        self._selector.register(self.fd, selectors.EVENT_READ)
        try:
            self._watch_tree(self.root)
        except Exception:
            self.close()
            raise

    def _watch(self, directory: Path) -> None:
        descriptor = self._add(
            self.fd, os.fsencode(directory),
            ctypes.c_uint32(self._WATCH_MASK | self._ONLYDIR | self._DONT_FOLLOW),
        )
        if descriptor < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(directory))
        self._watches[descriptor] = directory

    def _watch_tree(self, directory: Path) -> None:
        for root, directories, _files in os.walk(directory, followlinks=False):
            root_path = Path(root)
            kept: list[str] = []
            for name in directories:
                candidate = root_path / name
                try:
                    relative = candidate.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                if not candidate.is_symlink() and not self.excluded(relative):
                    kept.append(name)
            directories[:] = kept
            self._watch(root_path)

    def read(self, timeout: float) -> LocalEvents:
        if not self._selector.select(max(0.0, timeout)):
            return LocalEvents()
        paths: set[str] = set()
        overflow = False
        rescan = False
        while True:
            try:
                data = os.read(self.fd, 256 * 1024)
            except BlockingIOError:
                break
            if not data:
                break
            offset = 0
            while offset + self._EVENT.size <= len(data):
                watch, mask, _cookie, length = self._EVENT.unpack_from(data, offset)
                offset += self._EVENT.size
                raw_name = data[offset:offset + length]
                offset += length
                name = os.fsdecode(raw_name.split(b"\0", 1)[0]) if raw_name else ""
                if mask & self._Q_OVERFLOW:
                    overflow = True
                    continue
                parent = self._watches.get(watch)
                if parent is None:
                    rescan = True
                    continue
                candidate = parent / name if name else parent
                try:
                    relative = candidate.relative_to(self.root).as_posix()
                except ValueError:
                    overflow = True
                    continue
                if relative == "." or self.excluded(relative):
                    continue
                if mask & self._ISDIR:
                    rescan = True
                    if mask & (self._CREATE | self._MOVED_TO):
                        try:
                            self._watch_tree(candidate)
                        except OSError:
                            overflow = True
                else:
                    paths.add(relative)
                if mask & (self._DELETE_SELF | self._MOVE_SELF | self._IGNORED):
                    self._watches.pop(watch, None)
                    rescan = True
        return LocalEvents(frozenset(paths), overflow, rescan)

    def close(self) -> None:
        try:
            self._selector.close()
        finally:
            try:
                os.close(self.fd)
            except OSError:
                pass


class ChangeMonitor:
    """Event-driven local callbacks plus adaptive provider reconciliation."""

    def __init__(
        self,
        job: SyncJob,
        rclone_path: Callable[[], str],
        apply: Callable[[SyncJob, list[FileChange]], bool],
        reconcile: Callable[[SyncJob], None],
        protected_patterns: tuple[str, ...] = (),
        local_poll_seconds: float = 10.0,
        remote_poll_seconds: float = 30.0,
        remote_backoff: tuple[float, ...] = (30.0, 60.0, 120.0, 300.0),
        initial_local_snapshot: dict[str, FileState] | None = None,
        initial_remote_snapshot: dict[str, FileState] | None = None,
        event_factory: Callable[[Path, Callable[[str], bool]], InotifyTreeMonitor] = InotifyTreeMonitor,
        network_activity: Callable[[], None] | None = None,
        network_guard: Callable[[], ContextManager] | None = None,
        rclone_args: Callable[[], list[str]] | None = None,
        scan_jitter: Callable[[float], float] | None = None,
    ) -> None:
        self.job = job
        self.rclone_path = rclone_path
        self.apply = apply
        self.reconcile = reconcile
        self.protected_patterns = protected_patterns
        self.local_poll_seconds = max(1.0, local_poll_seconds)
        self.remote_poll_seconds = max(1.0, remote_poll_seconds)
        self.remote_backoff = tuple(max(1.0, value) for value in remote_backoff)
        self.initial_local_snapshot = initial_local_snapshot
        self.initial_remote_snapshot = initial_remote_snapshot
        self.event_factory = event_factory
        self.network_activity = network_activity or (lambda: None)
        self.network_guard = network_guard or contextlib.nullcontext
        self.rclone_args = rclone_args or (lambda: [])
        self.scan_jitter = scan_jitter or (lambda _base: 0.0)
        self.stop_event = threading.Event()
        self.last_remote_success = 0.0
        self.thread = threading.Thread(
            target=self._run, name=f"tuxindrive-callback-{job.id[:8]}", daemon=True
        )

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def healthy(self) -> bool:
        if not self.thread.is_alive() or not self.last_remote_success:
            return False
        maximum = max(self.remote_backoff or (self.remote_poll_seconds,))
        return time.monotonic() - self.last_remote_success <= max(120.0, maximum * 2)

    def _excluded(self, relative: str) -> bool:
        candidate = relative.replace(os.sep, "/")
        return is_transient_path(candidate) or any(
            fnmatch.fnmatch(candidate, pattern.lstrip("/"))
            or fnmatch.fnmatch("/" + candidate, pattern)
            for pattern in (*self.job.exclude_patterns, *self.protected_patterns)
            if pattern.strip()
        )

    def _file_state(self, relative: str) -> FileState | None:
        try:
            path = self.job.local / relative
            stat = path.stat(follow_symlinks=False)
            if not path.is_file() or path.is_symlink():
                return None
            return FileState(stat.st_size, str(stat.st_mtime_ns))
        except OSError:
            return None

    def local_snapshot(self) -> dict[str, FileState]:
        result: dict[str, FileState] = {}
        if not self.job.local.exists():
            return result
        for root, directories, files in os.walk(self.job.local, followlinks=False):
            relative_root = os.path.relpath(root, self.job.local)
            directories[:] = [
                directory for directory in directories
                if not os.path.islink(os.path.join(root, directory))
                and not self._excluded(
                    directory if relative_root == "." else f"{relative_root}/{directory}"
                )
            ]
            for filename in files:
                relative = (
                    filename if relative_root == "." else f"{relative_root}/{filename}"
                ).replace(os.sep, "/")
                if self._excluded(relative):
                    continue
                try:
                    stat = os.stat(os.path.join(root, filename), follow_symlinks=False)
                except OSError:
                    continue
                if not self.job.selected_by_rules(
                    relative, size=stat.st_size, modified_timestamp=stat.st_mtime
                ):
                    continue
                state = self._file_state(relative)
                if state is not None:
                    result[relative] = state
        return result

    def remote_snapshot(self) -> dict[str, FileState]:
        key = (
            self.rclone_path(), self.job.remote_spec,
            tuple(self.rclone_args()),
            tuple(sorted((*self.job.exclude_patterns, *self.protected_patterns))),
        )
        now = time.monotonic()
        with _REMOTE_METADATA_CACHE_LOCK:
            cached = _REMOTE_METADATA_CACHE.get(key)
            if cached and now - cached[0] <= _REMOTE_METADATA_CACHE_SECONDS:
                return dict(cached[1])
        self.network_activity()
        with self.network_guard():
            process = subprocess.run(
                [key[0], "lsjson", self.job.remote_spec, "--recursive",
                 "--files-only", "--no-mimetype", *key[2]],
                check=False, capture_output=True, text=True, timeout=120,
            )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "Cloud change scan failed")
        values = json.loads(process.stdout or "[]")
        if not isinstance(values, list):
            raise ValueError("Cloud change scan returned an invalid object")
        snapshot = {
            normalize_remote_path(str(item["Path"])): FileState(
                int(item.get("Size", -1)),
                normalize_remote_modtime(str(item.get("ModTime", ""))),
            )
            for item in values
            if isinstance(item, dict) and item.get("Path")
            and not self._excluded(str(item["Path"]))
            and self.job.selected_by_rules(
                str(item["Path"]), size=int(item.get("Size", -1))
            )
        }
        with _REMOTE_METADATA_CACHE_LOCK:
            _REMOTE_METADATA_CACHE[key] = (time.monotonic(), dict(snapshot))
            if len(_REMOTE_METADATA_CACHE) > 128:
                cutoff = time.monotonic() - _REMOTE_METADATA_CACHE_SECONDS
                for old_key, (stamp, _value) in list(_REMOTE_METADATA_CACHE.items()):
                    if stamp < cutoff:
                        _REMOTE_METADATA_CACHE.pop(old_key, None)
        return snapshot

    def remote_path_state(self, relative: str) -> FileState | None:
        """Read one existing remote file without recursively listing the job root.

        A missing object or any provider ambiguity deliberately raises so the
        caller falls back to the authoritative recursive scan.
        """
        safe = relative.strip("/")
        if not safe or ".." in Path(safe).parts or self._excluded(safe):
            raise ValueError("Unsafe targeted cloud path")
        remote = f"{self.job.remote_spec.rstrip('/')}/{safe}"
        self.network_activity()
        with self.network_guard():
            process = subprocess.run(
                [self.rclone_path(), "lsjson", remote, "--stat", "--no-mimetype",
                 *self.rclone_args()],
                check=False, capture_output=True, text=True, timeout=30,
            )
        if process.returncode:
            raise RuntimeError(process.stderr.strip() or "Targeted cloud check failed")
        value = json.loads(process.stdout or "{}")
        if not isinstance(value, dict) or value.get("IsDir") or "Size" not in value:
            raise ValueError("Targeted cloud check returned an invalid file")
        return FileState(
            int(value.get("Size", -1)),
            normalize_remote_modtime(str(value.get("ModTime", ""))),
        )

    def remote_paths_state(self, relatives: list[str]) -> dict[str, FileState]:
        """Read several verified provider states through one rclone session."""
        safe = [normalize_remote_path(item) for item in relatives]
        if not safe or any(not item or ".." in Path(item).parts for item in safe):
            raise ValueError("Unsafe targeted cloud paths")
        manifest_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="tuxindrive-paths-",
                suffix=".txt", delete=False,
            ) as manifest:
                manifest_name = manifest.name
                for item in safe:
                    manifest.write(item + "\n")
            self.network_activity()
            with self.network_guard():
                process = subprocess.run(
                    [self.rclone_path(), "lsjson", self.job.remote_spec, "--recursive",
                     "--files-only", "--no-mimetype", "--files-from-raw", manifest_name,
                     *self.rclone_args()],
                    check=False, capture_output=True, text=True, timeout=60,
                )
            if process.returncode:
                raise RuntimeError(process.stderr.strip() or "Targeted cloud check failed")
            values = json.loads(process.stdout or "[]")
            result = {
                normalize_remote_path(str(item["Path"])): FileState(
                    int(item.get("Size", -1)),
                    normalize_remote_modtime(str(item.get("ModTime", ""))),
                )
                for item in values
                if isinstance(item, dict) and item.get("Path")
            }
            if set(result) != set(safe):
                raise ValueError("One or more uploaded paths are unavailable")
            return result
        finally:
            if manifest_name:
                Path(manifest_name).unlink(missing_ok=True)

    def _run(self) -> None:
        local = self.initial_local_snapshot
        if local is None:
            local = self.local_snapshot()
        else:
            local = {
                normalize_remote_path(path): state
                for path, state in local.items()
                if not self._excluded(path)
            }
            self.initial_local_snapshot = None
        try:
            events: InotifyTreeMonitor | None = self.event_factory(self.job.local, self._excluded)
        except OSError:
            events = None
        if self.initial_remote_snapshot is not None:
            remote = {
                normalize_remote_path(path): state
                for path, state in self.initial_remote_snapshot.items()
                if not self._excluded(path)
            }
            remote_known = True
            self.last_remote_success = time.monotonic()
            self.initial_remote_snapshot = None
        else:
            try:
                initial_delay = (
                    self.remote_backoff[0]
                    if self.remote_backoff else self.remote_poll_seconds
                )
                if self.stop_event.wait(self.scan_jitter(initial_delay)):
                    return
                remote = self.remote_snapshot()
                remote_known = True
                self.last_remote_success = time.monotonic()
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                remote, remote_known = {}, False
        # Close the startup race between the initial snapshot and watch
        # installation/remote baseline. Events remain queued by the kernel,
        # while this second snapshot catches anything changed just before the
        # watches were installed.
        startup_local = self.local_snapshot()
        startup_changes = changes_between(local, startup_local, "local")
        local = startup_local
        deferred_local = {change.path: change for change in startup_changes}
        deferred_remote: dict[str, FileChange] = {}
        last_local_scan = time.monotonic()
        last_remote_scan = time.monotonic()
        backoff_index = 0
        base_delay = self.remote_backoff[0] if self.remote_backoff else self.remote_poll_seconds
        remote_delay = base_delay + self.scan_jitter(base_delay)
        recovery_due: float | None = None
        try:
            while not self.stop_event.is_set():
                if not self.job.enabled or not self.job.realtime_sync:
                    self.stop_event.wait(1.0)
                    continue
                now = time.monotonic()
                remote_due_at = last_remote_scan + remote_delay
                if recovery_due is not None:
                    remote_due_at = min(remote_due_at, recovery_due)
                timeout = min(1.0, max(0.0, remote_due_at - now))
                local_changes: list[FileChange] = []
                unsafe_monitor = False
                if events is not None and not local_changes:
                    batch = events.read(timeout)
                    if batch.overflow or batch.rescan:
                        new_local = self.local_snapshot()
                        local_changes = changes_between(local, new_local, "local")
                        local = new_local
                        unsafe_monitor = batch.overflow
                    elif batch.paths:
                        before = dict(local)
                        for relative in batch.paths:
                            state = self._file_state(relative)
                            if state is None:
                                local.pop(relative, None)
                            else:
                                local[relative] = state
                        local_changes = changes_between(before, local, "local")
                elif events is None:
                    self.stop_event.wait(timeout)
                    now = time.monotonic()
                    if now - last_local_scan >= self.local_poll_seconds:
                        new_local = self.local_snapshot()
                        local_changes = changes_between(local, new_local, "local")
                        local = new_local
                        last_local_scan = now
                if deferred_local:
                    merged = dict(deferred_local)
                    merged.update({change.path: change for change in local_changes})
                    local_changes = list(merged.values())
                if unsafe_monitor:
                    self.reconcile(self.job)
                    recovery_due = time.monotonic() + 10.0
                    continue
                now = time.monotonic()
                full_remote_due = now >= last_remote_scan + remote_delay
                remote_due = bool(local_changes) or full_remote_due
                if recovery_due is not None and now >= recovery_due:
                    remote_due = True
                if not remote_due:
                    continue
                targeted = False
                try:
                    # A normal save of an existing file only needs a same-path
                    # conflict check. The regular full scan remains due at the
                    # exact same deadline and catches unrelated remote changes.
                    if (
                        local_changes and not full_remote_due and remote_known
                        and all(
                            not change.deleted
                            and (self.job.local / change.path).is_file()
                            for change in local_changes
                        )
                    ):
                        new_remote = dict(remote)
                        for change in local_changes:
                            state = self.remote_path_state(change.path)
                            if state is None:
                                raise ValueError("Remote file disappeared")
                            new_remote[change.path] = state
                        targeted = True
                    else:
                        new_remote = self.remote_snapshot()
                except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                    if local_changes and not full_remote_due:
                        try:
                            new_remote = self.remote_snapshot()
                        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                            deferred_local.update({change.path: change for change in local_changes})
                            remote_delay = min(
                                300.0, max(remote_delay * 2, self.remote_poll_seconds)
                            )
                            if recovery_due is not None:
                                recovery_due = time.monotonic() + remote_delay
                            continue
                    else:
                        # Network/provider failure must not cause a local full scan.
                        deferred_local.update({change.path: change for change in local_changes})
                        remote_delay = min(
                            300.0, max(remote_delay * 2, self.remote_poll_seconds)
                        )
                        if recovery_due is not None:
                            recovery_due = time.monotonic() + remote_delay
                        continue
                if not targeted:
                    last_remote_scan = time.monotonic()
                    self.last_remote_success = last_remote_scan
                baseline_uncertain = not remote_known
                if not remote_known:
                    remote, remote_known = new_remote, True
                    base_delay = self.remote_backoff[0] if self.remote_backoff else self.remote_poll_seconds
                    remote_delay = base_delay + self.scan_jitter(base_delay)
                remote_changes = [] if baseline_uncertain else changes_between(remote, new_remote, "remote")
                if deferred_remote:
                    merged_remote = dict(deferred_remote)
                    merged_remote.update({change.path: change for change in remote_changes})
                    remote_changes = list(merged_remote.values())
                if baseline_uncertain and local_changes and self.job.mode is SyncMode.TWO_WAY:
                    # We cannot prove that the provider side remained unchanged
                    # while its baseline was unavailable. Merge through the
                    # authoritative full reconciliation instead of guessing.
                    self.reconcile(self.job)
                    remote = new_remote
                    deferred_local.clear()
                    deferred_remote.clear()
                    recovery_due = time.monotonic() + 10.0
                    continue
                local_paths = {normalize_remote_path(change.path) for change in local_changes}
                remote_paths = {normalize_remote_path(change.path) for change in remote_changes}
                if local_paths & remote_paths and self.job.mode is SyncMode.TWO_WAY:
                    self.reconcile(self.job)
                    deferred_local.clear()
                    deferred_remote.clear()
                    recovery_due = time.monotonic() + 10.0
                else:
                    permitted = [
                        change for change in local_changes + remote_changes
                        if not (change.side == "local" and self.job.mode is SyncMode.DOWNLOAD_ONLY)
                        and not (change.side == "remote" and self.job.mode is SyncMode.UPLOAD_ONLY)
                    ]
                    applied = not permitted or self.apply(self.job, permitted)
                    if permitted and applied:
                        local_applied = [item for item in permitted if item.side == "local"]
                        remote_applied = [item for item in permitted if item.side == "remote"]
                        # Local and provider timestamps use different encodings;
                        # never mirror one side's FileState into the other side.
                        # Refresh only the changed paths after transfer.
                        try:
                            existing = [item.path for item in local_applied if not item.deleted]
                            refreshed = (
                                self.remote_paths_state(existing) if len(existing) > 1 else {}
                            )
                            for item in local_applied:
                                if item.deleted:
                                    new_remote.pop(item.path, None)
                                else:
                                    state = refreshed.get(normalize_remote_path(item.path))
                                    if state is None:
                                        state = self.remote_path_state(item.path)
                                    if state is None:
                                        raise ValueError("Uploaded path is unavailable")
                                    new_remote[normalize_remote_path(item.path)] = state
                        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
                            remote_known = False
                        for item in remote_applied:
                            state = self._file_state(item.path)
                            if state is None:
                                local.pop(item.path, None)
                            else:
                                local[item.path] = state
                        recovery_due = time.monotonic() + 10.0
                    if permitted and not applied:
                        deferred_local.update({change.path: change for change in local_changes})
                        deferred_remote.update({
                            change.path: change for change in remote_changes
                        })
                    else:
                        deferred_local.clear()
                        deferred_remote.clear()
                remote = new_remote
                if local_changes or remote_changes:
                    backoff_index = 0
                else:
                    backoff_index = min(backoff_index + 1, len(self.remote_backoff) - 1)
                if self.remote_backoff:
                    base_delay = self.remote_backoff[backoff_index]
                    remote_delay = base_delay + self.scan_jitter(base_delay)
                recovery_due = None if recovery_due is not None and time.monotonic() >= recovery_due else recovery_due
        finally:
            if events is not None:
                events.close()
