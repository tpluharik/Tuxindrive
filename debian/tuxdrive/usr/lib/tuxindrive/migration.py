from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from . import __version__
from .config import ConfigStore, config_root
from .models import AppConfig
from .password_helper import configuration_password, store_configuration_password
from .rclone import RcloneClient


PROFILE_PATH = "TuxInDrive/TuxInDrive-Profile.tdx"
LEGACY_PROFILE_PATH = ".tuxdrive-profile/tuxdrive-profile.tdx"
FORMAT = "tuxindrive-encrypted-profile"
LEGACY_FORMAT = "tuxdrive-encrypted-profile"
MAX_PROFILE_SIZE = 128 * 1024 * 1024
CURRENT_SCRYPT_N = 2**17


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    created_at: str
    app_version: str
    device_name: str
    accounts: int
    jobs: int
    includes_credentials: bool


def _derive(password: str, salt: bytes, n: int = CURRENT_SCRYPT_N, minimum: int = 14) -> bytes:
    if len(password) < minimum:
        raise MigrationError(f"Use a backup passphrase of at least {minimum} characters")
    return Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(password.encode("utf-8"))


def encrypt_profile(payload: dict[str, Any], password: str) -> bytes:
    salt, nonce = os.urandom(16), os.urandom(12)
    header = {"format": FORMAT, "version": 2, "kdf": "scrypt", "n": CURRENT_SCRYPT_N, "r": 8, "p": 1}
    aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    clear = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    envelope = dict(header)
    envelope.update({
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(AESGCM(_derive(password, salt)).encrypt(nonce, clear, aad)).decode(),
    })
    return (json.dumps(envelope, sort_keys=True) + "\n").encode()


def decrypt_profile(data: bytes, password: str) -> dict[str, Any]:
    if len(data) > MAX_PROFILE_SIZE:
        raise MigrationError("The encrypted profile exceeds the 128 MiB safety limit")
    try:
        envelope = json.loads(data)
        version = int(envelope.get("version", 0))
        if envelope.get("format") not in {FORMAT, LEGACY_FORMAT} or version not in {1, 2}:
            raise MigrationError("This is not a supported TuxInDrive profile backup")
        header = {key: envelope[key] for key in ("format", "version", "kdf", "n", "r", "p")}
        expected_n = 2**15 if version == 1 else CURRENT_SCRYPT_N
        if header["kdf"] != "scrypt" or header["r"] != 8 or header["p"] != 1 or header["n"] != expected_n:
            raise MigrationError("Unsupported profile key-derivation settings")
        aad = json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
        salt = base64.b64decode(envelope["salt"], validate=True)
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        cipher = base64.b64decode(envelope["ciphertext"], validate=True)
        return json.loads(AESGCM(_derive(password, salt, expected_n, 10 if version == 1 else 14)).decrypt(nonce, cipher, aad))
    except MigrationError:
        raise
    except (InvalidTag, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise MigrationError("The backup password is wrong or the encrypted profile was changed") from exc


class ProfileManager:
    def __init__(self, store: ConfigStore, rclone: RcloneClient, peer_root: Path | None = None) -> None:
        self.store = store
        self.rclone = rclone
        self.peer_root = peer_root or config_root() / "peer"

    @staticmethod
    def remote_spec(remote: str, path: str = PROFILE_PATH) -> str:
        if not remote or any(character in remote for character in ":/\\"):
            raise MigrationError("Choose a valid connected profile account")
        return f"{remote}:{path}"

    def _available_spec(self, remote: str) -> str | None:
        for path in (PROFILE_PATH, LEGACY_PROFILE_PATH):
            spec = self.remote_spec(remote, path)
            if self.rclone.object_exists(spec):
                return spec
        return None

    def _secrets(self, include_peer_files: bool = True) -> dict[str, Any]:
        rclone_file = self.rclone.config_file()
        peers: dict[str, str] = {}
        if include_peer_files and self.peer_root.is_dir():
            for path in self.peer_root.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(self.peer_root)
                    peers[str(relative)] = base64.b64encode(path.read_bytes()).decode()
        return {
            "rclone_config": base64.b64encode(rclone_file.read_bytes()).decode(),
            "rclone_config_password": configuration_password(),
            "peer_files": peers,
        }

    def create_bytes(self, config: AppConfig, password: str, include_credentials: bool = False) -> bytes:
        serialized = config.to_dict()
        if not include_credentials:
            for share in serialized.get("peer_shares", []):
                share["tor_bridge_lines"] = []
                share["tor_pluggable_transports"] = []
        payload: dict[str, Any] = {
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "app_version": __version__,
                "device_name": socket.gethostname(),
                "includes_credentials": include_credentials,
            },
            "config": serialized,
        }
        if include_credentials:
            payload["secrets"] = self._secrets()
        return encrypt_profile(payload, password)

    def create_mobile_bytes(self, config: AppConfig, password: str) -> bytes:
        """Create a compact encrypted profile for local desktop-to-phone transfer."""
        payload: dict[str, Any] = {
            "metadata": {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "app_version": __version__,
                "device_name": socket.gethostname(),
                "includes_credentials": True,
                "mobile_transfer": True,
            },
            "config": config.to_dict(),
            "secrets": self._secrets(include_peer_files=False),
        }
        return encrypt_profile(payload, password)

    def upload(self, remote: str, config: AppConfig, password: str, include_credentials: bool = False) -> ProfileSummary:
        data = self.create_bytes(config, password, include_credentials)
        with tempfile.TemporaryDirectory(prefix="tuxindrive-profile-") as temporary:
            source = Path(temporary) / "profile.tdx"
            source.write_bytes(data)
            os.chmod(source, 0o600)
            self.rclone.copy_to(source, self.remote_spec(remote))
        return self.summary(data, password)

    def download(self, remote: str) -> bytes:
        source = self._available_spec(remote)
        if source is None:
            raise MigrationError("No TuxInDrive profile backup was found in this account")
        with tempfile.TemporaryDirectory(prefix="tuxindrive-profile-") as temporary:
            destination = Path(temporary) / "profile.tdx"
            self.rclone.copy_to(source, destination)
            if destination.stat().st_size > MAX_PROFILE_SIZE:
                raise MigrationError("The downloaded profile exceeds the 128 MiB safety limit")
            data = destination.read_bytes()
            if source == self.remote_spec(remote, LEGACY_PROFILE_PATH):
                self.rclone.copy_to(destination, self.remote_spec(remote))
            return data

    def available(self, remote: str) -> bool:
        return self._available_spec(remote) is not None

    def summary(self, data: bytes, password: str) -> ProfileSummary:
        payload = decrypt_profile(data, password)
        metadata, config = payload.get("metadata", {}), payload.get("config", {})
        AppConfig.from_dict(config)
        return ProfileSummary(
            created_at=str(metadata.get("created_at", "Unknown")),
            app_version=str(metadata.get("app_version", "Unknown")),
            device_name=str(metadata.get("device_name", "Unknown")),
            accounts=len(config.get("accounts", [])),
            jobs=len(config.get("jobs", [])),
            includes_credentials=bool(metadata.get("includes_credentials", False)),
        )

    def restore(self, data: bytes, password: str, restore_credentials: bool = False) -> AppConfig:
        payload = decrypt_profile(data, password)
        restored = AppConfig.from_dict(payload.get("config", {}))
        backup = self.store.path.with_suffix(".json.before-migration")
        if self.store.path.exists():
            backup.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(self.store.path, backup)
            os.chmod(backup, 0o600)
        if restore_credentials and payload.get("secrets"):
            secrets = payload["secrets"]
            try:
                rclone_bytes = base64.b64decode(secrets["rclone_config"], validate=True)
                rclone_password = str(secrets["rclone_config_password"])
                if not rclone_password or len(rclone_password) > 1024:
                    raise ValueError("invalid rclone configuration password")
                peer_bytes: list[tuple[Path, bytes]] = []
                root = self.peer_root.resolve()
                for relative, encoded in secrets.get("peer_files", {}).items():
                    target = (self.peer_root / relative).resolve()
                    if target != root and root not in target.parents:
                        raise MigrationError("The profile contains an unsafe peer-key path")
                    peer_bytes.append((target, base64.b64decode(encoded, validate=True)))
            except (KeyError, TypeError, ValueError) as exc:
                raise MigrationError(
                    "The profile lacks the cloud-configuration unlock key; create a new credential-enabled backup on the old device"
                ) from exc
            rclone_file = self.rclone.config_file()
            store_configuration_password(rclone_password)
            rclone_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            rclone_file.write_bytes(rclone_bytes)
            os.chmod(rclone_file, 0o600)
            for target, decoded in peer_bytes:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.write_bytes(decoded)
                os.chmod(target, 0o600)
        self.store.save(restored)
        return restored
