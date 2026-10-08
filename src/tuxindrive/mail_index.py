"""Private, bounded attachment metadata/text search; never a mailbox mirror."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, RLock

from .file_permissions import private_descriptor
from .file_preview import OFFICE_SUFFIXES, TEXT_SUFFIXES, MAX_INDEX_CHARACTERS, index_text_path
from .mail_auth import MailAccount, MailCancelled, MailError, check_cancel
from .mail_connectors import MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS, MailAttachment, MailClient, safe_message_url
from .search_index import FolderSearchIndex, _normalized


MAX_DOWNLOAD_BYTES_PER_REFRESH = 64 * 1024 * 1024
MAX_DOWNLOADS_PER_REFRESH = 500


@dataclass(frozen=True)
class MailSearchResult:
    attachment: MailAttachment
    matched_content: bool = False
    indexed_text: str = ""

    @property
    def name(self):
        return self.attachment.name

    @property
    def job_name(self):
        provider = "Gmail" if self.attachment.provider == "gmail" else "Microsoft 365"
        return provider + " · " + self.attachment.account_name

    @property
    def relative_path(self):
        return self.attachment.sender + " · " + self.attachment.subject

    @property
    def size(self):
        return self.attachment.size

    is_directory = False


@dataclass(frozen=True)
class MailIndexStats:
    indexed: int
    messages: int
    removed: int = 0
    reused: int = 0
    downloaded: int = 0
    content_skipped: int = 0
    complete: bool = True


def _fingerprint(item: MailAttachment) -> str:
    value = [item.message_id, item.attachment_id, item.name, item.size, item.received,
             item.mime_type, item.revision]
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


class MailSearchIndex(FolderSearchIndex):
    """Reuse private SQLite connection handling, in a separate mail database."""

    def __init__(self, path: Path):
        super().__init__(path)
        self.refresh_lock = RLock()
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS mail_attachments (
                  account_id TEXT NOT NULL, message_id TEXT NOT NULL, attachment_id TEXT NOT NULL,
                  item_json TEXT NOT NULL, search_text TEXT NOT NULL, content_text TEXT NOT NULL DEFAULT '',
                  content_ready INTEGER NOT NULL DEFAULT 0, fingerprint TEXT NOT NULL,
                  generation INTEGER NOT NULL,
                  PRIMARY KEY(account_id, message_id, attachment_id)
                );
                CREATE INDEX IF NOT EXISTS mail_account_generation
                  ON mail_attachments(account_id, generation);
            """)

    def count(self, account_id: str | None = None) -> int:
        with self._connect() as connection:
            if account_id:
                return int(connection.execute("SELECT COUNT(*) FROM mail_attachments WHERE account_id=?", (account_id,)).fetchone()[0])
            return int(connection.execute("SELECT COUNT(*) FROM mail_attachments").fetchone()[0])

    @contextmanager
    def maintenance(self):
        """Do not let a still-running refresh resurrect disconnected/private data."""
        if not self.refresh_lock.acquire(blocking=False):
            raise MailError("Another mailbox refresh is running; stop it and wait before changing its index.")
        try:
            yield
        finally:
            self.refresh_lock.release()

    def clear_contents(self, account_id: str | None = None) -> None:
        with self.maintenance(), self._connect() as connection:
            if account_id:
                connection.execute("UPDATE mail_attachments SET content_text='',content_ready=0 WHERE account_id=?", (account_id,))
            else:
                connection.execute("UPDATE mail_attachments SET content_text='',content_ready=0")

    def remove_account(self, account_id: str) -> None:
        with self.maintenance(), self._connect() as connection:
            connection.execute("DELETE FROM mail_attachments WHERE account_id=?", (account_id,))

    def search(self, query: str, *, stop_event: Event | None = None, limit: int = 200) -> list[MailSearchResult]:
        if stop_event is not None and stop_event.is_set():
            return []
        tokens = _normalized(query).split()
        if not tokens:
            return []
        if len(tokens) > 20 or len(query) > 1000:
            raise MailError("Use a shorter attachment search query.")
        conditions, values = [], []
        for token in tokens:
            literal = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append("(search_text LIKE ? ESCAPE '\\' OR content_text LIKE ? ESCAPE '\\')")
            values += ["%" + literal + "%"] * 2
        with self._connect() as connection:
            if stop_event is not None:
                connection.set_progress_handler(lambda: int(stop_event.is_set()), 1000)
            try:
                rows = connection.execute(
                    "SELECT item_json,search_text,content_text FROM mail_attachments WHERE "
                    + " AND ".join(conditions) + " ORDER BY account_id,message_id,attachment_id LIMIT ?",
                    (*values, max(1, min(200, limit))),
                ).fetchall()
            except sqlite3.OperationalError:
                if stop_event is not None and stop_event.is_set():
                    return []
                raise
            results = []
            for row in rows:
                if stop_event is not None and stop_event.is_set():
                    return []
                item = MailAttachment(**json.loads(row["item_json"]))
                # A corrupted SQLite URL must not become an arbitrary browser action.
                safe_message_url(item.message_url, item.provider)
                results.append(MailSearchResult(item, any(t not in row["search_text"] for t in tokens), row["content_text"]))
            return results

    def refresh(self, account: MailAccount, client: MailClient, *, stop_event: Event | None = None,
                include_content: bool | None = None, progress=None) -> MailIndexStats:
        account.validate()
        if client.account.id != account.id:
            raise MailError("The index refresh client belongs to another mailbox.")
        if not self.refresh_lock.acquire(blocking=False):
            raise MailError("Another mailbox refresh is already running; stop it or wait for completion.")
        try:
            include_content = account.include_content if include_content is None else include_content
            if not include_content:
                self.clear_contents(account.id)
            with self._connect() as connection:
                previous = {
                    (row["message_id"], row["attachment_id"]): dict(row)
                    for row in connection.execute("SELECT * FROM mail_attachments WHERE account_id=?", (account.id,))
                }
            scan = client.scan(progress)
            rows, reused, downloaded, skipped, total_bytes = [], 0, 0, 0, 0
            for item in scan.attachments:
                check_cancel(stop_event)
                if item.account_id != account.id or item.provider != account.provider:
                    raise MailError("The provider mixed attachment accounts; the previous index is retained.")
                safe_message_url(item.message_url, item.provider)
                fingerprint = _fingerprint(item)
                old = previous.get((item.message_id, item.attachment_id))
                content, content_ready = "", False
                if include_content and old and old["fingerprint"] == fingerprint and old["content_ready"]:
                    content, content_ready = old["content_text"], True
                    reused += 1
                elif include_content:
                    suffix = Path(item.name).suffix.lower()
                    eligible = suffix in TEXT_SUFFIXES | OFFICE_SUFFIXES | {".pdf"}
                    if (not eligible or item.size > MAX_ATTACHMENT_BYTES
                            or downloaded >= MAX_DOWNLOADS_PER_REFRESH
                            or total_bytes + item.size > MAX_DOWNLOAD_BYTES_PER_REFRESH):
                        skipped += 1
                    else:
                        # Every downloaded byte counts, even when extraction fails.
                        total_bytes += item.size
                        downloaded += 1
                        try:
                            data = client.download(item)
                            if len(data) != item.size or len(data) > MAX_ATTACHMENT_BYTES:
                                raise MailError("Attachment bytes did not match their metadata.")
                            with tempfile.TemporaryDirectory(prefix="tuxindrive-mail-") as temporary:
                                path = Path(temporary) / ("attachment" + suffix)
                                with path.open("xb") as stream:
                                    private_descriptor(stream.fileno())
                                    stream.write(data)
                                content = _normalized(index_text_path(path))[:MAX_INDEX_CHARACTERS]
                                content_ready = True
                        except MailCancelled:
                            raise
                        except (MailError, OSError, ValueError):
                            skipped += 1
                search_text = _normalized(" ".join((item.name, item.subject, item.sender, item.account_name, item.received)))
                rows.append((item, search_text, content, int(content_ready), fingerprint))
            check_cancel(stop_event)
            generation, indexed, removed = time.monotonic_ns(), 0, 0
            complete = scan.complete
            available = max(0, MAX_ATTACHMENTS - len(previous))
            with self._connect() as connection:
                for item, searchable, content, content_ready, fingerprint in rows:
                    check_cancel(stop_event)
                    key = (item.message_id, item.attachment_id)
                    if not scan.complete and key not in previous:
                        if not available:
                            complete = False
                            continue
                        available -= 1
                    connection.execute("""
                        INSERT INTO mail_attachments VALUES(?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(account_id,message_id,attachment_id) DO UPDATE SET
                          item_json=excluded.item_json,search_text=excluded.search_text,
                          content_text=excluded.content_text,content_ready=excluded.content_ready,
                          fingerprint=excluded.fingerprint,generation=excluded.generation
                    """, (account.id, item.message_id, item.attachment_id, json.dumps(asdict(item)),
                          searchable, content, content_ready, fingerprint, generation))
                    indexed += 1
                if scan.complete:
                    removed = connection.execute(
                        "DELETE FROM mail_attachments WHERE account_id=? AND generation!=?", (account.id, generation)
                    ).rowcount
            return MailIndexStats(indexed, scan.messages, removed, reused, downloaded, skipped, complete)
        finally:
            self.refresh_lock.release()
