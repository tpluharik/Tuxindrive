from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from .config import cache_root
from .models import SyncJob


@dataclass(frozen=True, slots=True)
class CacheCleanupResult:
    job_id: str
    examined_bytes: int = 0
    released_bytes: int = 0
    released_files: int = 0
    skipped_pinned: int = 0
    skipped_uncertain: int = 0


class StreamingCacheManager:
    """Pin-aware cache quota enforcement with conservative uncertainty rules.

    rclone remains configured without its generic quota because it cannot know
    TuxInDrive pin state. This manager only removes regular cache objects that
    are outside every verified pin marker, have no VFS metadata/write-back
    record and have been inactive long enough to avoid racing an open stream.
    """

    def __init__(self, inactivity_seconds: float = 3600.0) -> None:
        self.inactivity_seconds = max(60.0, inactivity_seconds)

    @staticmethod
    def _root(job: SyncJob) -> Path:
        return cache_root() / "vfs" / job.id

    @staticmethod
    def _pinned_paths(root: Path) -> set[str] | None:
        pins = root / ".tuxdrive-pins"
        protected: set[str] = set()
        if not pins.exists():
            return protected
        try:
            markers = list(pins.glob("*.json"))
        except OSError:
            return None
        for marker in markers:
            try:
                payload = json.loads(marker.read_text(encoding="utf-8"))
                files = payload.get("files", [])
                if not isinstance(files, list):
                    return None
                for item in files:
                    path = item.get("path") if isinstance(item, dict) else None
                    parsed = Path(path) if isinstance(path, str) else None
                    if (
                        parsed is None or not path or parsed.is_absolute()
                        or ".." in parsed.parts
                    ):
                        return None
                    protected.add(parsed.as_posix())
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                # Invalid pin state means eviction is unsafe for the whole job.
                return None
        return protected

    def enforce(
        self,
        job: SyncJob,
        *,
        max_bytes: int,
        min_free_bytes: int,
        mounted: bool,
        now: float | None = None,
    ) -> CacheCleanupResult:
        root = self._root(job)
        data = root / "vfs"
        if max_bytes <= 0 or not data.exists():
            return CacheCleanupResult(job.id)
        pinned = self._pinned_paths(root)
        if pinned is None:
            return CacheCleanupResult(job.id, skipped_uncertain=1)
        metadata = root / "vfsMeta"
        current = time.time() if now is None else now
        candidates: list[tuple[float, int, Path]] = []
        total = 0
        skipped_pinned = 0
        skipped_uncertain = 0
        try:
            files = data.rglob("*")
            for path in files:
                try:
                    if path.is_symlink() or not path.is_file():
                        if path.is_symlink():
                            skipped_uncertain += 1
                        continue
                    relative = path.relative_to(data).as_posix()
                    stat = path.stat(follow_symlinks=False)
                    total += stat.st_size
                    if relative in pinned:
                        skipped_pinned += 1
                        continue
                    # Metadata may indicate an in-progress or dirty write-back.
                    if (metadata / relative).exists():
                        skipped_uncertain += 1
                        continue
                    last_use = max(stat.st_atime, stat.st_mtime)
                    if mounted and current - last_use < self.inactivity_seconds:
                        skipped_uncertain += 1
                        continue
                    candidates.append((last_use, stat.st_size, path))
                except OSError:
                    skipped_uncertain += 1
        except OSError:
            return CacheCleanupResult(job.id, total, skipped_uncertain=skipped_uncertain + 1)
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            return CacheCleanupResult(job.id, total, skipped_pinned=skipped_pinned, skipped_uncertain=skipped_uncertain + 1)
        need = max(0, total - max_bytes, min_free_bytes - free)
        released = files_released = 0
        for _last_use, size, path in sorted(candidates):
            if released >= need:
                break
            try:
                # Recheck the object immediately before deletion. A recent
                # access or newly-created metadata record makes it ineligible.
                stat = path.stat(follow_symlinks=False)
                relative = path.relative_to(data).as_posix()
                if path.is_symlink() or relative in pinned or (metadata / relative).exists():
                    skipped_uncertain += 1
                    continue
                if mounted and current - max(stat.st_atime, stat.st_mtime) < self.inactivity_seconds:
                    skipped_uncertain += 1
                    continue
                path.unlink()
                released += size
                files_released += 1
            except OSError:
                skipped_uncertain += 1
        # Empty directories contain no user data and are best-effort cleanup.
        for directory in sorted((item for item in data.rglob("*") if item.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        return CacheCleanupResult(
            job.id, total, released, files_released, skipped_pinned, skipped_uncertain
        )
