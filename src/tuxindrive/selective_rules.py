"""Named selective-sync presets and a bounded local dry-run preview."""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import SyncJob


@dataclass(frozen=True, slots=True)
class RulePreset:
    key: str
    label: str
    extensions: tuple[str, ...] = ()
    max_size_mb: int = 0
    max_age_days: int = 0


PRESETS: tuple[RulePreset, ...] = (
    RulePreset("all", "All files"),
    RulePreset(
        "documents", "Documents",
        ("txt", "md", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "csv"),
    ),
    RulePreset(
        "photos", "Photos",
        ("jpg", "jpeg", "png", "gif", "webp", "heic", "tif", "tiff", "raw", "dng"),
    ),
    RulePreset("recent", "Modified in the last 30 days", max_age_days=30),
    RulePreset("small", "Files up to 100 MiB", max_size_mb=100),
)


def preset_by_key(key: str) -> RulePreset:
    return next((item for item in PRESETS if item.key == key), PRESETS[0])


@dataclass(frozen=True, slots=True)
class RulePreview:
    examined_files: int
    selected_files: int
    rejected_files: int
    selected_bytes: int
    skipped_uncertain: int
    truncated: bool

    def to_dict(self) -> dict[str, int | bool]:
        return asdict(self)


def _excluded(job: SyncJob, relative: str) -> bool:
    value = relative.replace(os.sep, "/")
    name = Path(value).name
    if job.include_patterns and not any(
        fnmatch.fnmatchcase(value, pattern)
        or fnmatch.fnmatchcase(f"/{value}", pattern)
        or fnmatch.fnmatchcase(name, pattern)
        for pattern in job.include_patterns
    ):
        return True
    return job.excluded_by_rules(value)


def preview_local_rules(
    job: SyncJob,
    *,
    max_files: int = 100_000,
    now: float | None = None,
) -> RulePreview:
    """Evaluate the exact job predicate without reading file contents or links."""
    limit = min(1_000_000, max(1, int(max_files)))
    root = job.local
    examined = selected = rejected = selected_bytes = uncertain = 0
    truncated = False
    if not root.is_dir() or root.is_symlink():
        return RulePreview(0, 0, 0, 0, 1, False)
    current = time.time() if now is None else now
    try:
        iterator = os.walk(root, topdown=True, followlinks=False)
        for directory, folders, files in iterator:
            base = Path(directory)
            safe_folders = []
            for folder in folders:
                candidate = base / folder
                try:
                    if candidate.is_symlink():
                        uncertain += 1
                    else:
                        safe_folders.append(folder)
                except OSError:
                    uncertain += 1
            folders[:] = safe_folders
            for name in files:
                if examined >= limit:
                    truncated = True
                    return RulePreview(examined, selected, rejected, selected_bytes, uncertain, truncated)
                path = base / name
                try:
                    if path.is_symlink() or not path.is_file():
                        uncertain += 1
                        continue
                    relative = path.relative_to(root).as_posix()
                    stat = path.stat(follow_symlinks=False)
                except (OSError, ValueError):
                    uncertain += 1
                    continue
                examined += 1
                if _excluded(job, relative):
                    rejected += 1
                    continue
                # Use an explicit clock so a long preview cannot change its own
                # result when crossing an age boundary.
                age_selected = (
                    job.selective_max_age_days <= 0
                    or stat.st_mtime >= current - job.selective_max_age_days * 86400
                )
                if age_selected and job.selected_by_rules(
                    relative, size=stat.st_size, modified_timestamp=None
                ):
                    selected += 1
                    selected_bytes += stat.st_size
                else:
                    rejected += 1
    except OSError:
        uncertain += 1
    return RulePreview(examined, selected, rejected, selected_bytes, uncertain, truncated)
