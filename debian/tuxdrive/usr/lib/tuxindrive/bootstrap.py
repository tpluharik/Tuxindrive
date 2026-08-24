from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
import re
import threading
from pathlib import Path
from typing import Callable


RCLONE_VERSION = "1.75.0"
RCLONE_MINIMUM = (1, 75, 0)
MAX_RCLONE_ARCHIVE = 64 * 1024 * 1024
RCLONE_SHA256 = {
    ("linux", "amd64"): "aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa",
    ("linux", "arm64"): "d0ad88ba4c8e285b7c9efa591e0ab643280a91741e13c27f3a9c0957ccfa5203",
    ("osx", "amd64"): "19edbb8e5e73096eb66e92a42abbc5c34bfa8981ea3986a53872c7eef85a22f4",
    ("osx", "arm64"): "35e8f2a666ce789b29111db0dd843ddabc0d59c6b609d07bcaae5d1a07cba6f8",
    ("windows", "amd64"): "203581f0a7baeae873f2347483a798c79e2eaf5c384a4e9d866aa374f1c89ac0",
    ("windows", "arm64"): "bcf628fa6bb3b6ae9fdf105d04acafb40ec77841f686dc6dd7d126dde04c5f6a",
}

_COMPATIBILITY_CACHE: dict[tuple[str, int, int, int, int], bool] = {}
_COMPATIBILITY_LOCK = threading.Lock()


class BootstrapError(RuntimeError):
    pass


def user_rclone_path() -> Path:
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return base / "TuxInDrive" / "bin" / "rclone.exe"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "TuxInDrive" / "bin" / "rclone"
    current = Path.home() / ".local" / "lib" / "tuxindrive" / "rclone"
    legacy = Path.home() / ".local" / "lib" / "tuxdrive" / "rclone"
    return legacy if legacy.is_file() and not current.exists() else current


def resolve_rclone(configured: str = "rclone") -> str | None:
    candidates: list[Path] = []
    if configured and configured != "rclone":
        candidates.append(Path(configured).expanduser())
    candidates.extend(
        [
            Path("/usr/lib/tuxindrive/bin/rclone"),
            Path("/usr/lib/tuxdrive/bin/rclone"),
            user_rclone_path(),
        ]
    )
    system = shutil.which("rclone")
    if system:
        candidates.append(Path(system))
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.is_file() and os.access(candidate, os.X_OK) and rclone_compatible(candidate):
            return str(candidate)
    return None


def rclone_compatible(executable: Path) -> bool:
    """Require the bisync safety features used by TuxInDrive."""
    try:
        stat = executable.stat()
        identity = (
            str(executable.resolve()), stat.st_dev, stat.st_ino,
            stat.st_size, stat.st_mtime_ns,
        )
    except OSError:
        return False
    with _COMPATIBILITY_LOCK:
        cached = _COMPATIBILITY_CACHE.get(identity)
    if cached is not None:
        return cached
    try:
        version = subprocess.run(
            [str(executable), "version"], check=False, capture_output=True,
            text=True, timeout=10,
        )
        match = re.search(r"rclone v(\d+)\.(\d+)\.(\d+)", version.stdout + version.stderr)
        if version.returncode or not match or tuple(map(int, match.groups())) < RCLONE_MINIMUM:
            compatible = False
            with _COMPATIBILITY_LOCK:
                _COMPATIBILITY_CACHE[identity] = compatible
            return compatible
        result = subprocess.run(
            [str(executable), "bisync", "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    help_text = result.stdout + result.stderr
    compatible = all(
        flag in help_text for flag in ("--resilient", "--recover", "--resync-mode")
    )
    with _COMPATIBILITY_LOCK:
        # Prune identities for replaced versions of the same executable.
        for key in tuple(_COMPATIBILITY_CACHE):
            if key[0] == identity[0] and key != identity:
                _COMPATIBILITY_CACHE.pop(key, None)
        _COMPATIBILITY_CACHE[identity] = compatible
    return compatible


def install_rclone(progress: Callable[[str], None] | None = None) -> str:
    existing = resolve_rclone()
    if existing:
        return existing
    machine = platform.machine().lower()
    architecture = {
        "x86_64": "amd64",
        "amd64": "amd64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if not architecture:
        raise BootstrapError(f"Unsupported CPU architecture: {machine}")
    operating_system = {"Linux": "linux", "Darwin": "osx", "Windows": "windows"}.get(platform.system())
    if not operating_system:
        raise BootstrapError(f"Unsupported operating system: {platform.system()}")
    filename = f"rclone-v{RCLONE_VERSION}-{operating_system}-{architecture}.zip"
    url = f"https://downloads.rclone.org/v{RCLONE_VERSION}/{filename}"
    if progress:
        progress(f"Downloading rclone {RCLONE_VERSION}…")
    destination = user_rclone_path()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="tuxindrive-runtime-") as temporary:
        archive = Path(temporary) / filename
        try:
            with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as output:
                received = 0
                while chunk := response.read(1024 * 1024):
                    received += len(chunk)
                    if received > MAX_RCLONE_ARCHIVE:
                        raise BootstrapError("The transfer-engine archive exceeded its safety limit")
                    output.write(chunk)
        except OSError as exc:
            raise BootstrapError(
                "Could not download the embedded transfer engine. Check the internet connection."
            ) from exc
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != RCLONE_SHA256[(operating_system, architecture)]:
            raise BootstrapError("Downloaded rclone archive failed SHA-256 verification")
        if progress:
            progress("Installing verified transfer engine…")
        with zipfile.ZipFile(archive) as package:
            executable_name = "rclone.exe" if operating_system == "windows" else "rclone"
            members = [item for item in package.infolist() if item.filename.endswith(f"/{executable_name}")]
            if len(members) != 1 or members[0].file_size > 128 * 1024 * 1024:
                raise BootstrapError("The rclone archive did not contain the expected executable")
            temporary_target = destination.with_suffix(".new")
            with package.open(members[0]) as source, temporary_target.open("wb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(temporary_target, 0o755)
            os.replace(temporary_target, destination)
    return str(destination)
