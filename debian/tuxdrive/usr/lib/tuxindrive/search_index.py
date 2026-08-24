"""Private, local filename index for synchronized folders.

The index deliberately records metadata only.  It never opens file contents and
does not walk files-on-demand mounts, so refreshing it cannot hydrate cloud data
or turn an idle desktop into a remote metadata scan.
"""

from __future__ import annotations

import fnmatch
import os
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Iterable

from .models import SyncJob, SyncMode


SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES_PER_JOB = 250_000


@dataclass(frozen=True, slots=True)
class SearchResult:
    job_id: str
    job_name: str
    root: Path
    relative_path: str
    is_directory: bool
    size: int
    modified_ns: int

    @property
    def name(self) -> str:
        return Path(self.relative_path).name

    @property
    def local_path(self) -> Path:
        return self.root / Path(self.relative_path)


@dataclass(frozen=True, slots=True)
class IndexStats:
    indexed: int = 0
    removed: int = 0
    skipped_jobs: int = 0
    limited_jobs: int = 0
    cancelled: bool = False


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _excluded(relative: str, patterns: Iterable[str]) -> bool:
    candidate = relative.replace(os.sep, "/")
    return any(
        fnmatch.fnmatch(candidate, pattern.lstrip("/"))
        or fnmatch.fnmatch("/" + candidate, pattern)
        or any(fnmatch.fnmatch(part, pattern) for part in Path(candidate).parts)
        for pattern in patterns
        if pattern.strip()
    )


class FolderSearchIndex:
    """SQLite-backed index of names and paths under local sync roots."""

    def __init__(
        self,
        path: Path,
        *,
        max_entries_per_job: int = DEFAULT_MAX_ENTRIES_PER_JOB,
    ) -> None:
        self.path = Path(path)
        self.max_entries_per_job = max(1, int(max_entries_per_job))
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._protect(self.path.parent, 0o700)
        self._initialize()

    @staticmethod
    def _protect(path: Path, mode: int) -> None:
        try:
            os.chmod(path, mode)
        except (OSError, NotImplementedError):
            # Native Windows ACLs are authoritative there.
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS entries (
                    job_id TEXT NOT NULL,
                    job_name TEXT NOT NULL,
                    root TEXT NOT NULL,
                    relative_path TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    is_directory INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    generation INTEGER NOT NULL,
                    PRIMARY KEY (job_id, relative_path)
                );
                CREATE INDEX IF NOT EXISTS entries_search_text
                    ON entries(search_text);
                CREATE INDEX IF NOT EXISTS entries_generation
                    ON entries(job_id, generation);
                """
            )
            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
        self._protect(self.path, 0o600)
        for suffix in ("-wal", "-shm"):
            auxiliary = Path(str(self.path) + suffix)
            if auxiliary.exists():
                self._protect(auxiliary, 0o600)

    @staticmethod
    def _eligible(job: SyncJob) -> bool:
        return (
            job.mode is not SyncMode.VIRTUAL_DRIVE
            and job.local.is_dir()
            and not job.local.is_symlink()
        )

    def refresh(
        self,
        jobs: Iterable[SyncJob],
        *,
        stop_event: Event | None = None,
    ) -> IndexStats:
        indexed = removed = skipped = limited = 0
        cancelled = False
        configured_ids: set[str] = set()
        with self._connect() as connection:
            known_generation = connection.execute(
                "SELECT COALESCE(MAX(generation), 0) FROM entries"
            ).fetchone()[0]
            generation = int(known_generation) + 1
            for job in jobs:
                configured_ids.add(job.id)
                if stop_event is not None and stop_event.is_set():
                    cancelled = True
                    break
                if not self._eligible(job):
                    skipped += 1
                    removed += connection.execute(
                        "DELETE FROM entries WHERE job_id = ?", (job.id,)
                    ).rowcount
                    continue
                count, hit_limit, was_cancelled = self._refresh_job(
                    connection, job, generation, stop_event
                )
                indexed += count
                limited += int(hit_limit)
                if was_cancelled:
                    cancelled = True
                    break
                if not hit_limit:
                    removed += connection.execute(
                        "DELETE FROM entries WHERE job_id = ? AND generation <> ?",
                        (job.id, generation),
                    ).rowcount
            if not cancelled:
                if configured_ids:
                    placeholders = ",".join("?" for _ in configured_ids)
                    removed += connection.execute(
                        f"DELETE FROM entries WHERE job_id NOT IN ({placeholders})",
                        tuple(sorted(configured_ids)),
                    ).rowcount
                else:
                    removed += connection.execute("DELETE FROM entries").rowcount
        return IndexStats(indexed, removed, skipped, limited, cancelled)

    def refresh_job(
        self,
        job: SyncJob,
        *,
        stop_event: Event | None = None,
    ) -> IndexStats:
        if not self._eligible(job):
            with self._connect() as connection:
                removed = connection.execute(
                    "DELETE FROM entries WHERE job_id = ?", (job.id,)
                ).rowcount
            return IndexStats(removed=removed, skipped_jobs=1)
        with self._connect() as connection:
            generation = int(connection.execute(
                "SELECT COALESCE(MAX(generation), 0) FROM entries"
            ).fetchone()[0]) + 1
            count, hit_limit, cancelled = self._refresh_job(
                connection, job, generation, stop_event
            )
            removed = 0
            if not cancelled and not hit_limit:
                removed = connection.execute(
                    "DELETE FROM entries WHERE job_id = ? AND generation <> ?",
                    (job.id, generation),
                ).rowcount
        return IndexStats(count, removed, limited_jobs=int(hit_limit), cancelled=cancelled)

    def _refresh_job(
        self,
        connection: sqlite3.Connection,
        job: SyncJob,
        generation: int,
        stop_event: Event | None,
    ) -> tuple[int, bool, bool]:
        root = job.local.resolve(strict=False)
        pending = [root]
        count = 0
        hit_limit = False
        while pending:
            if stop_event is not None and stop_event.is_set():
                return count, hit_limit, True
            directory = pending.pop()
            try:
                children = list(os.scandir(directory))
            except OSError:
                continue
            for child in children:
                if stop_event is not None and stop_event.is_set():
                    return count, hit_limit, True
                try:
                    relative = Path(child.path).relative_to(root).as_posix()
                    if child.is_symlink() or _excluded(relative, job.exclude_patterns):
                        continue
                    is_directory = child.is_dir(follow_symlinks=False)
                    stat = child.stat(follow_symlinks=False)
                except (OSError, ValueError):
                    continue
                connection.execute(
                    """
                    INSERT INTO entries(
                        job_id, job_name, root, relative_path, search_text,
                        is_directory, size, modified_ns, generation
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id, relative_path) DO UPDATE SET
                        job_name=excluded.job_name,
                        root=excluded.root,
                        search_text=excluded.search_text,
                        is_directory=excluded.is_directory,
                        size=excluded.size,
                        modified_ns=excluded.modified_ns,
                        generation=excluded.generation
                    """,
                    (
                        job.id,
                        job.name,
                        str(root),
                        relative,
                        _normalized(relative),
                        int(is_directory),
                        0 if is_directory else max(0, int(stat.st_size)),
                        max(0, int(stat.st_mtime_ns)),
                        generation,
                    ),
                )
                count += 1
                if is_directory:
                    pending.append(Path(child.path))
                if count >= self.max_entries_per_job:
                    hit_limit = True
                    return count, hit_limit, False
        return count, hit_limit, False

    @staticmethod
    def _like_token(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def search(self, query: str, *, limit: int = 200) -> list[SearchResult]:
        tokens = [self._like_token(item) for item in _normalized(query).split() if item]
        if not tokens or limit <= 0:
            return []
        where = " AND ".join("search_text LIKE ? ESCAPE '\\'" for _ in tokens)
        parameters: list[object] = [f"%{token}%" for token in tokens]
        parameters.append(min(max(int(limit), 1), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT job_id, job_name, root, relative_path, is_directory,
                       size, modified_ns
                FROM entries
                WHERE {where}
                ORDER BY is_directory DESC, length(relative_path), relative_path
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [
            SearchResult(
                row["job_id"], row["job_name"], Path(row["root"]),
                row["relative_path"], bool(row["is_directory"]),
                int(row["size"]), int(row["modified_ns"]),
            )
            for row in rows
        ]

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
