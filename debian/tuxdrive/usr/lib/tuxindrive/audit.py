from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .config import data_root
from .file_permissions import private_descriptor


@dataclass(frozen=True, slots=True)
class AuditEvent:
    timestamp: str
    category: str
    action: str
    outcome: str
    job_id: str = ""
    peer: str = ""
    path: str = ""
    detail: str = ""
    id: str = ""


class AuditTimeline:
    """Private append-only operational history with atomic compaction."""

    def __init__(self, path: Path | None = None, limit: int = 5000) -> None:
        self.path = path or data_root() / "audit.jsonl"
        self.limit = max(100, limit)
        self._lock = threading.RLock()

    def record(self, category: str, action: str, outcome: str, *, job_id: str = "", peer: str = "", path: str = "", detail: str = "") -> AuditEvent:
        event = AuditEvent(datetime.now(timezone.utc).isoformat(), category, action, outcome, job_id, peer, path, detail[:1000], uuid4().hex)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.path.parent, 0o700)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
            os.chmod(self.path, 0o600)
            if self.path.stat().st_size > 5 * 1024 * 1024:
                self._compact()
        return event

    def recent(self, limit: int = 250, job_id: str = "") -> list[AuditEvent]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        events = []
        for line in reversed(lines):
            try:
                event = AuditEvent(**json.loads(line))
            except (TypeError, json.JSONDecodeError):
                continue
            if job_id and event.job_id != job_id:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        return events

    def _compact(self) -> None:
        lines = self.path.read_text(encoding="utf-8").splitlines()[-self.limit:]
        descriptor, temporary = tempfile.mkstemp(prefix="audit-", suffix=".jsonl", dir=self.path.parent)
        try:
            private_descriptor(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + ("\n" if lines else ""))
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
