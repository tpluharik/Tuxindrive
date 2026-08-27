"""Shared admission and rate controls for every application network path."""
from __future__ import annotations

import contextlib
import random
import re
import threading
import time
from collections.abc import Iterator


_RATE = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>[BKMGTP]?)$", re.IGNORECASE)
_SCALES = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4, "P": 1024**5}


def normalize_bandwidth_limit(value: str) -> str:
    """Validate a simple rclone upload[:download] rate without schedules."""
    text = str(value or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if len(parts) > 2:
        raise ValueError("Use a rate such as 2M or separate upload:download rates")
    for part in parts:
        if part.lower() == "off":
            continue
        match = _RATE.fullmatch(part)
        if not match or float(match.group("value")) < 0:
            raise ValueError("Use a rate such as 2M or 1M:4M")
    return text


def _rate_bytes(value: str, *, download: bool = True) -> float | None:
    text = normalize_bandwidth_limit(value)
    if not text:
        return None
    parts = text.split(":")
    part = parts[-1] if download and len(parts) == 2 else parts[0]
    if part.lower() == "off":
        return None
    match = _RATE.fullmatch(part)
    assert match is not None
    amount = float(match.group("value"))
    unit = match.group("unit").upper()
    # rclone interprets a suffix-free value as KiB/s.
    return amount * (_SCALES[unit] if unit else 1024)


def effective_rclone_limit(global_limit: str, job_limit: str = "") -> str:
    """Return the stricter limit independently for upload and download."""
    global_value = normalize_bandwidth_limit(global_limit)
    job_value = str(job_limit or "").strip()
    if not global_value:
        return job_value
    if not job_value:
        return global_value
    try:
        normalized_job = normalize_bandwidth_limit(job_value)
    except ValueError:
        return global_value

    def directions(value: str) -> tuple[str, str]:
        parts = value.split(":")
        return (parts[0], parts[-1])

    selected: list[str] = []
    for global_part, job_part in zip(directions(global_value), directions(normalized_job)):
        global_rate = _rate_bytes(global_part)
        job_rate = _rate_bytes(job_part)
        if global_rate is None:
            selected.append(job_part)
        elif job_rate is None:
            selected.append(global_part)
        else:
            selected.append(job_part if job_rate <= global_rate else global_part)
    return selected[0] if selected[0].lower() == selected[1].lower() else ":".join(selected)


def protected_bandwidth_limit(
    limit: str, *, headroom_percent: int = 50, parallel_budget: int = 1
) -> str:
    """Reserve link headroom and divide a process limit across consumers.

    rclone's ``--bwlimit`` is process-local. Without this division, several
    mounts plus a synchronization can each consume the complete configured
    ceiling and overwhelm the connection in aggregate.
    """
    normalized = normalize_bandwidth_limit(limit)
    if not normalized:
        return ""
    headroom = min(80, max(0, int(headroom_percent)))
    consumers = max(1, int(parallel_budget))
    factor = (100 - headroom) / 100 / consumers
    selected: list[str] = []
    for part in normalized.split(":"):
        if part.lower() == "off":
            selected.append("off")
            continue
        rate = _rate_bytes(part, download=False)
        assert rate is not None
        selected.append("0B" if rate <= 0 else f"{max(1, int(rate * factor))}B")
    if len(selected) == 1:
        return selected[0]
    return ":".join(selected)


class GlobalBandwidthController:
    """One shared gate plus a byte-rate clock for in-process downloads."""

    def __init__(
        self,
        limit: str = "",
        max_active: int = 1,
        *,
        automatic: bool = False,
        headroom_percent: int = 50,
    ) -> None:
        self.max_active = max(1, int(max_active))
        self._slots = threading.BoundedSemaphore(self.max_active)
        self._admission = threading.Lock()
        self._control_plane = threading.Lock()
        self._interactive_transfer = threading.Lock()
        self._lock = threading.RLock()
        self._next_download = 0.0
        self._next_upload = 0.0
        self.automatic = bool(automatic)
        self.headroom_percent = min(80, max(0, int(headroom_percent)))
        self.parallel_budget = 1
        self.limit = ""
        self.configure(limit)

    def configure(self, limit: str) -> None:
        normalized = normalize_bandwidth_limit(limit)
        with self._lock:
            self.limit = normalized
            self._next_download = 0.0
            self._next_upload = 0.0

    def configure_automatic(self, enabled: bool, headroom_percent: int = 50) -> None:
        automatic = bool(enabled)
        headroom = min(80, max(0, int(headroom_percent)))
        with self._lock:
            if self.automatic == automatic and self.headroom_percent == headroom:
                return
            self.automatic = automatic
            self.headroom_percent = headroom
            self._next_download = 0.0
            self._next_upload = 0.0

    def configure_parallel_budget(self, consumers: int) -> None:
        """Set the maximum simultaneous process-local traffic consumers."""
        budget = max(1, int(consumers))
        with self._lock:
            if self.parallel_budget == budget:
                return
            self.parallel_budget = budget
            self._next_download = 0.0
            self._next_upload = 0.0

    def _controller_limit(self) -> str:
        with self._lock:
            if not self.automatic:
                return self.limit
            return protected_bandwidth_limit(
                self.limit,
                headroom_percent=self.headroom_percent,
                parallel_budget=self.parallel_budget,
            )

    @property
    def enabled(self) -> bool:
        return any(
            (_rate_bytes(part) or 0) > 0
            for part in (self.limit.split(":") if self.limit else ())
        )

    def rclone_args(self, job_limit: str = "") -> list[str]:
        limit = effective_rclone_limit(self._controller_limit(), job_limit)
        return ["--bwlimit", limit] if limit else []

    @contextlib.contextmanager
    def guard(self, *, exclusive: bool = False) -> Iterator[None]:
        count = self.max_active if exclusive else 1
        # Serialize multi-slot acquisition so two exclusive callers cannot
        # each hold one slot while waiting forever for the other.
        with self._admission:
            for _index in range(count):
                self._slots.acquire()
        try:
            yield
        finally:
            for _index in range(count):
                self._slots.release()

    @contextlib.contextmanager
    def control_plane_guard(self) -> Iterator[None]:
        """Serialize bounded control requests without waiting for transfers.

        Callers must keep their response size bounded and apply the shared byte
        clock. This lane is intentionally separate from transfer admission so
        a long-running synchronization cannot starve an interactive manifest
        or other small control-plane request.
        """
        with self._control_plane:
            yield

    @contextlib.contextmanager
    def interactive_transfer_guard(self) -> Iterator[None]:
        """Keep one responsive update lane within the divided traffic budget."""
        with self._interactive_transfer:
            yield

    def throttle_download(self, byte_count: int) -> None:
        self._throttle(byte_count, download=True)

    def throttle_upload(self, byte_count: int) -> None:
        self._throttle(byte_count, download=False)

    def _throttle(self, byte_count: int, *, download: bool) -> None:
        rate = _rate_bytes(self._controller_limit(), download=download)
        if rate is None or rate <= 0 or byte_count <= 0:
            return
        with self._lock:
            now = time.monotonic()
            next_transfer = self._next_download if download else self._next_upload
            scheduled = max(now, next_transfer)
            if download:
                self._next_download = scheduled + byte_count / rate
            else:
                self._next_upload = scheduled + byte_count / rate
        delay = scheduled - now
        if delay > 0:
            time.sleep(delay)

    @staticmethod
    def scan_jitter(base_seconds: float) -> float:
        return random.uniform(0.0, min(30.0, max(1.0, base_seconds) * 0.25))
