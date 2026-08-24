from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import AppSettings


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    allowed: bool
    reason: str = "Maximum transfer usage"


class TransferPolicy:
    """Evaluate optional network, battery and schedule transfer limits."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def evaluate(self, now: datetime | None = None) -> PolicyDecision:
        if self.settings.network_policy == "maximum":
            return PolicyDecision(True)
        if not self.settings.allow_metered_networks and self._metered():
            return PolicyDecision(False, "Paused on a metered network")
        threshold = max(0, min(100, self.settings.pause_below_battery_percent))
        battery = self._battery_percent()
        if threshold and battery is not None and battery < threshold and not self._on_ac_power():
            return PolicyDecision(False, f"Paused below {threshold}% battery")
        if self.settings.schedule_start and self.settings.schedule_end:
            current = (now or datetime.now()).strftime("%H:%M")
            start, end = self.settings.schedule_start, self.settings.schedule_end
            inside = start <= current < end if start <= end else current >= start or current < end
            if not inside:
                return PolicyDecision(False, f"Paused outside schedule {start}–{end}")
        return PolicyDecision(True, "Transfer policy allows synchronization")

    @staticmethod
    def _battery_percent() -> int | None:
        values = []
        for path in Path("/sys/class/power_supply").glob("BAT*/capacity"):
            try:
                values.append(int(path.read_text(encoding="utf-8").strip()))
            except (OSError, ValueError):
                continue
        return min(values) if values else None

    @staticmethod
    def _on_ac_power() -> bool:
        for path in Path("/sys/class/power_supply").glob("*/online"):
            try:
                if path.read_text(encoding="utf-8").strip() == "1":
                    return True
            except OSError:
                continue
        return False

    @staticmethod
    def _metered() -> bool:
        try:
            result = subprocess.run(
                ["nmcli", "-t", "-f", "GENERAL.METERED", "device", "show"],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return any(line.rsplit(":", 1)[-1].lower() in {"yes", "guess-yes"} for line in result.stdout.splitlines())
