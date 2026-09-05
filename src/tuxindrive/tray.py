"""Deterministic tray presentation state, independent from GTK."""

from __future__ import annotations

from dataclasses import dataclass


SYNC_ANIMATION_INTERVAL_MS = 160
SYNC_ANIMATION_ICONS = tuple(f"tuxindrive-sync-{frame}" for frame in range(8))
VALID_TRAY_STATES = frozenset(("ready", "syncing", "error"))


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
