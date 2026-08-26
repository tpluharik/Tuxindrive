"""Deterministic release-readiness scenarios which never contact a provider.

Live provider tests remain credential-gated.  This module supplies a stable,
machine-readable baseline for upgrade, recovery, policy and index behaviour so
release CI can distinguish an application regression from an external outage.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    success: bool
    duration_ms: int
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReliabilityReport:
    generated_at: int
    results: tuple[ScenarioResult, ...]

    @property
    def success(self) -> bool:
        return all(item.success for item in self.results)

    def to_dict(self) -> dict:
        return {
            "schema": 1,
            "generated_at": self.generated_at,
            "success": self.success,
            "results": [asdict(item) for item in self.results],
        }

    def write(self, destination: Path) -> None:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)


def run_scenarios(
    scenarios: Iterable[tuple[str, Callable[[], str | None]]],
) -> ReliabilityReport:
    results: list[ScenarioResult] = []
    for name, scenario in scenarios:
        started = time.monotonic_ns()
        try:
            detail = scenario() or "ok"
            success = True
        except Exception as exc:  # the report must preserve all scenario results
            detail = f"{type(exc).__name__}: {exc}"
            success = False
        duration = max(0, (time.monotonic_ns() - started) // 1_000_000)
        results.append(ScenarioResult(name, success, duration, detail))
    return ReliabilityReport(int(time.time()), tuple(results))
