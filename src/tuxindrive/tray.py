"""Deterministic tray presentation state, independent from GTK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .error_details import redact_error_text
from .models import SyncJob


SYNC_ANIMATION_INTERVAL_MS = 320
SYNC_ANIMATION_ICONS = tuple(f"tuxindrive-sync-{frame}" for frame in range(8))
VALID_TRAY_STATES = frozenset(("ready", "syncing", "error"))
MAX_VISIBLE_TRAY_ALERTS = 5


def compact_tray_text(value: str, limit: int = 110) -> str:
    """Keep panel menus bounded and redact credentials before shortening."""
    text = " ".join(redact_error_text(value).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


@dataclass(frozen=True)
class TrayAlert:
    job_id: str | None
    name: str
    reason: str

    @property
    def menu_label(self) -> str:
        return f"{compact_tray_text(self.name, 40)} — {compact_tray_text(self.reason)}"

    @property
    def tooltip(self) -> str:
        return redact_error_text(f"{self.name}\n{self.reason}")[:2200]


def alerts_for_jobs(jobs: Iterable[SyncJob], runtime_error: str = "") -> tuple[TrayAlert, ...]:
    """Read outstanding failures without provider calls or log scanning."""
    alerts = [
        TrayAlert(job.id, job.name, job.last_error)
        for job in jobs if job.last_error.strip()
    ]
    if runtime_error:
        alerts.insert(0, TrayAlert(None, "TuxInDrive", runtime_error))
    return tuple(alerts)


def tray_state_for_jobs(
    jobs: Iterable[SyncJob], active_ids: set[str], detail: str = "", runtime_error: str = ""
) -> tuple[str, str]:
    alerts = alerts_for_jobs(jobs, runtime_error)
    if alerts:
        # A successful result or another active transfer cannot hide a failure.
        return "error", alerts[0].menu_label
    if active_ids:
        return "syncing", detail or "Synchronization in progress"
    return "ready", detail


@dataclass
class TrayIconModel:
    """Select the packaged icon and label for the current application state."""

    state: str = "ready"
    detail: str = ""
    frame: int = 0

    @property
    def animated(self) -> bool:
        return self.state == "syncing"

    @property
    def attention(self) -> bool:
        return self.state == "error"

    @property
    def icon_name(self) -> str:
        if self.state == "syncing":
            return SYNC_ANIMATION_ICONS[self.frame % len(SYNC_ANIMATION_ICONS)]
        if self.state == "error":
            return "tuxindrive-error"
        return "tuxindrive"

    @property
    def accessible_label(self) -> str:
        description = self.detail.strip() or {
            "ready": "ready",
            "syncing": "synchronizing",
            "error": "needs attention",
        }[self.state]
        return f"TuxInDrive: {description}"

    def set_state(self, state: str, detail: str = "") -> None:
        self.state = state if state in VALID_TRAY_STATES else "ready"
        self.detail = detail
        self.frame = 0

    def advance(self) -> None:
        if self.animated:
            self.frame = (self.frame + 1) % len(SYNC_ANIMATION_ICONS)
