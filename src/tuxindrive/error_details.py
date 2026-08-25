"""Bounded, redacted error details for the desktop job card."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .models import SyncJob


_MAX_LOG_BYTES = 64 * 1024
_MAX_DETAIL_LINES = 16
_SECRET = re.compile(
    r"(?i)\b(authorization|bearer|token|password|secret|cookie|session)\b\s*[:=]\s*([^\s,;]+)"
)
_URL_CREDENTIALS = re.compile(r"(https?://)[^/@\s:]+:[^/@\s]+@", re.IGNORECASE)
_AUTH_HEADER = re.compile(r"(?i)\bAuthorization\s*:\s*(?:Bearer|Basic)\s+\S+")
_QUERY_SECRET = re.compile(r"(?i)([?&](?:access_token|token|password|secret)=)[^&\s]+")
_ERROR_LINE = re.compile(r"(?i)(error|failed|failure|denied|forbidden|not found|cannot|could not)")
_RCLONE_SOURCE = re.compile(r"(?i)\b(?:ERROR|NOTICE)\s*:\s*(.+?):\s+(?:failed|error|could not|cannot)")
_NAMED_SOURCE = re.compile(r"(?i)\b(?:source|file|path)\s*[:=]\s*([^\r\n,;]+)")


@dataclass(frozen=True, slots=True)
class ErrorDetails:
    reason: str
    source: str
    occurred_at: str
    log_path: str
    excerpt: str


def redact_error_text(value: str) -> str:
    """Remove common credentials before rendering a log excerpt in the UI."""
    value = _URL_CREDENTIALS.sub(r"\1[redacted]@", value)
    value = _AUTH_HEADER.sub("Authorization: [redacted]", value)
    value = _QUERY_SECRET.sub(r"\1[redacted]", value)
    return _SECRET.sub(lambda match: f"{match.group(1)}=[redacted]", value)


def _safe_log_tail(path_value: str, log_root: Path) -> str:
    if not path_value:
        return ""
    try:
        root = log_root.resolve(strict=True)
        path = Path(path_value).expanduser().resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            return ""
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > _MAX_LOG_BYTES:
                handle.seek(-_MAX_LOG_BYTES, os.SEEK_END)
            raw = handle.read(_MAX_LOG_BYTES)
    except (OSError, RuntimeError, ValueError):
        return ""
    return raw.decode("utf-8", errors="replace")


def _source_from_text(value: str) -> str:
    for pattern in (_RCLONE_SOURCE, _NAMED_SOURCE):
        match = pattern.search(value)
        if match:
            return redact_error_text(match.group(1).strip())[:1000]
    return ""


def details_for_job(job: SyncJob, log_root: Path) -> ErrorDetails:
    """Return immediate details without any provider or conflict scan."""
    tail = _safe_log_tail(job.last_error_log, log_root)
    relevant = [
        redact_error_text(line.strip())[:1200]
        for line in tail.splitlines()
        if line.strip() and _ERROR_LINE.search(line)
    ][-_MAX_DETAIL_LINES:]
    source = job.last_error_source or _source_from_text(job.last_error) or _source_from_text(tail)
    return ErrorDetails(
        reason=redact_error_text(job.last_error)[:2000]
        or "No synchronization error has been recorded for this folder.",
        source=redact_error_text(source)[:1000]
        or "No individual source file was reported.",
        occurred_at=job.last_error_at or "Unknown",
        log_path=job.last_error_log or "No job log was recorded.",
        excerpt="\n".join(relevant) or "No additional error lines are available.",
    )
