"""Cross-platform device network traffic meter with persistent daily totals."""
from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .config import cache_root
from .file_permissions import private_descriptor


@dataclass(frozen=True, slots=True)
class NetworkUsage:
    download_rate: float = 0.0
    upload_rate: float = 0.0
    downloaded_today: int = 0
    uploaded_today: int = 0
    available: bool = True


def format_bytes(value: float, *, rate: bool = False) -> str:
    amount = max(0.0, float(value))
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = units[0]
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            break
        amount /= 1024.0
    precision = 0 if unit == "B" else 1
    rendered = f"{amount:.{precision}f} {unit}"
    return f"{rendered}/s" if rate else rendered


def _linux_counters(path: Path = Path("/proc/net/dev")) -> tuple[int, int] | None:
    try:
        totals = [0, 0]
        for line in path.read_text(encoding="utf-8").splitlines()[2:]:
            name, values = line.split(":", 1)
            if name.strip() == "lo":
                continue
            fields = values.split()
            totals[0] += int(fields[0])
            totals[1] += int(fields[8])
        return totals[0], totals[1]
    except (OSError, ValueError, IndexError):
        return None


def _macos_counters() -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            ["netstat", "-ibn"], capture_output=True, text=True,
            timeout=3, check=False,
        )
        if result.returncode:
            return None
        lines = result.stdout.splitlines()
        header = next((line.split() for line in lines if "Ibytes" in line and "Obytes" in line), None)
        if not header:
            return None
        in_index, out_index = header.index("Ibytes"), header.index("Obytes")
        interfaces: dict[str, tuple[int, int]] = {}
        for line in lines:
            fields = line.split()
            if len(fields) <= max(in_index, out_index) or fields[0] == "Name" or fields[0].startswith("lo"):
                continue
            try:
                current = int(fields[in_index]), int(fields[out_index])
            except ValueError:
                continue
            previous = interfaces.get(fields[0], (0, 0))
            interfaces[fields[0]] = max(previous[0], current[0]), max(previous[1], current[1])
        return sum(item[0] for item in interfaces.values()), sum(item[1] for item in interfaces.values())
    except (OSError, subprocess.SubprocessError):
        return None


def _windows_counters() -> tuple[int, int] | None:
    if platform.system() != "Windows":
        return None

    class MibIfRow(ctypes.Structure):
        _fields_ = [
            ("wszName", ctypes.c_wchar * 256), ("dwIndex", ctypes.c_ulong),
            ("dwType", ctypes.c_ulong), ("dwMtu", ctypes.c_ulong),
            ("dwSpeed", ctypes.c_ulong), ("dwPhysAddrLen", ctypes.c_ulong),
            ("bPhysAddr", ctypes.c_ubyte * 8), ("dwAdminStatus", ctypes.c_ulong),
            ("dwOperStatus", ctypes.c_ulong), ("dwLastChange", ctypes.c_ulong),
            ("dwInOctets", ctypes.c_ulong), ("dwInUcastPkts", ctypes.c_ulong),
            ("dwInNUcastPkts", ctypes.c_ulong), ("dwInDiscards", ctypes.c_ulong),
            ("dwInErrors", ctypes.c_ulong), ("dwInUnknownProtos", ctypes.c_ulong),
            ("dwOutOctets", ctypes.c_ulong), ("dwOutUcastPkts", ctypes.c_ulong),
            ("dwOutNUcastPkts", ctypes.c_ulong), ("dwOutDiscards", ctypes.c_ulong),
            ("dwOutErrors", ctypes.c_ulong), ("dwOutQLen", ctypes.c_ulong),
            ("dwDescrLen", ctypes.c_ulong), ("bDescr", ctypes.c_ubyte * 256),
        ]

    try:
        api = ctypes.WinDLL("iphlpapi")
        size = ctypes.c_ulong(0)
        api.GetIfTable(None, ctypes.byref(size), False)
        buffer = ctypes.create_string_buffer(size.value)
        if api.GetIfTable(buffer, ctypes.byref(size), False) != 0:
            return None
        count = ctypes.c_ulong.from_buffer(buffer).value
        offset = ctypes.sizeof(ctypes.c_ulong)
        received = sent = 0
        for index in range(count):
            row = MibIfRow.from_buffer(buffer, offset + index * ctypes.sizeof(MibIfRow))
            if row.dwType != 24:  # MIB_IF_TYPE_LOOPBACK
                received += row.dwInOctets
                sent += row.dwOutOctets
        return received, sent
    except (AttributeError, OSError, ValueError):
        return None


def read_network_counters() -> tuple[int, int] | None:
    system = platform.system()
    if system == "Linux":
        return _linux_counters()
    if system == "Darwin":
        return _macos_counters()
    if system == "Windows":
        return _windows_counters()
    return None


class NetworkUsageMeter:
    def __init__(
        self,
        state_path: Path | None = None,
        reader: Callable[[], tuple[int, int] | None] = read_network_counters,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = date.today,
        minimum_sample_seconds: float | None = None,
    ) -> None:
        self.state_path = state_path or cache_root() / "network-usage.json"
        self.reader, self.clock, self.today = reader, clock, today
        self._lock = threading.RLock()
        self.day = self.today().isoformat()
        self.downloaded = self.uploaded = 0
        self.previous: tuple[int, int] | None = None
        self.previous_time: float | None = None
        self._last_saved = 0.0
        self.minimum_sample_seconds = max(
            0.0,
            3.0 if minimum_sample_seconds is None and platform.system() == "Darwin"
            else float(minimum_sample_seconds or 0.0),
        )
        persisted = self._load()
        current = self.reader()
        if persisted and persisted.get("day") == self.day:
            try:
                self.downloaded = max(0, int(persisted.get("downloaded", 0)))
                self.uploaded = max(0, int(persisted.get("uploaded", 0)))
                old = persisted.get("counters")
                if current and isinstance(old, list) and len(old) == 2:
                    self.downloaded += self._delta(current[0], int(old[0]))
                    self.uploaded += self._delta(current[1], int(old[1]))
            except (TypeError, ValueError):
                self.downloaded = self.uploaded = 0
        self.previous = current
        self.previous_time = self.clock() if current else None
        self._usage = NetworkUsage(
            downloaded_today=self.downloaded, uploaded_today=self.uploaded,
            available=current is not None,
        )
        self.save()

    @staticmethod
    def _delta(current: int, previous: int) -> int:
        return current - previous if current >= previous else 0

    def sample(self) -> NetworkUsage:
        with self._lock:
            return self._sample_locked()

    def _sample_locked(self) -> NetworkUsage:
        now = self.clock()
        if (
            self.previous_time is not None and self.minimum_sample_seconds
            and now - self.previous_time < self.minimum_sample_seconds
        ):
            return self._usage
        current, day = self.reader(), self.today().isoformat()
        if current is None:
            self._usage = NetworkUsage(
                downloaded_today=self.downloaded, uploaded_today=self.uploaded,
                available=False,
            )
            return self._usage
        if day != self.day:
            self.day, self.downloaded, self.uploaded = day, 0, 0
        down_delta = up_delta = 0
        elapsed = 0.0
        if self.previous is not None and self.previous_time is not None:
            down_delta = self._delta(current[0], self.previous[0])
            up_delta = self._delta(current[1], self.previous[1])
            elapsed = max(0.0, now - self.previous_time)
            self.downloaded += down_delta
            self.uploaded += up_delta
        self.previous, self.previous_time = current, now
        self._usage = NetworkUsage(
            down_delta / elapsed if elapsed else 0.0,
            up_delta / elapsed if elapsed else 0.0,
            self.downloaded, self.uploaded, True,
        )
        if now - self._last_saved >= 60.0:
            self.save()
        return self._usage

    @property
    def usage(self) -> NetworkUsage:
        return self._usage

    def _load(self) -> dict | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def _save_locked(self) -> None:
        if self.previous is None:
            return
        payload = {
            "day": self.day, "downloaded": self.downloaded,
            "uploaded": self.uploaded, "counters": list(self.previous),
        }
        temporary = ""
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(self.state_path.parent, 0o700)
            descriptor, temporary = tempfile.mkstemp(prefix="network-", suffix=".json", dir=self.state_path.parent)
            private_descriptor(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.write("\n")
            os.replace(temporary, self.state_path)
            os.chmod(self.state_path, 0o600)
            self._last_saved = self.clock()
        except OSError:
            return
        finally:
            if temporary and os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
