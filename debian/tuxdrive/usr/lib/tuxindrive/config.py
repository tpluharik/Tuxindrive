from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path

from .models import AppConfig
from .file_permissions import private_descriptor


def config_home() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    root = os.environ.get("XDG_CONFIG_HOME")
    return Path(root) if root else Path.home() / ".config"


def cache_home() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Cache"
    if system == "Darwin":
        return Path.home() / "Library" / "Caches"
    root = os.environ.get("XDG_CACHE_HOME")
    return Path(root) if root else Path.home() / ".cache"


def data_home() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    root = os.environ.get("XDG_DATA_HOME")
    return Path(root) if root else Path.home() / ".local" / "share"


def branded_root(root: Path) -> Path:
    """Use the new product directory, or an existing legacy directory.

    Existing installations keep using their original private state in place so
    an upgrade cannot lose credentials, peer identities, recovery history, or
    cached offline files. Fresh installations use the TuxInDrive namespace.
    """
    current = root / "tuxindrive"
    legacy = root / "tuxdrive"
    if current.exists() or not legacy.exists():
        return current
    return legacy


def config_root() -> Path:
    return branded_root(config_home())


def cache_root() -> Path:
    return branded_root(cache_home())


def data_root() -> Path:
    return branded_root(data_home())


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_root() / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                return AppConfig.from_dict(json.load(handle))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            backup = self.path.with_suffix(".json.invalid")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            raise RuntimeError(f"Invalid TuxInDrive configuration; moved to {backup}") from exc

    def save(self, config: AppConfig) -> None:
        serialized = (
            json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        try:
            if self.path.read_bytes() == serialized:
                # Keep durability for changed configuration, but avoid an
                # fsync/rename and downstream filesystem notifications when
                # callers save an identical object.
                os.chmod(self.path, 0o600)
                return
        except FileNotFoundError:
            pass
        except OSError:
            # A failed comparison must never suppress the authoritative write.
            pass
        descriptor, temporary = tempfile.mkstemp(
            prefix="config-", suffix=".json", dir=self.path.parent
        )
        try:
            private_descriptor(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(serialized.decode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
