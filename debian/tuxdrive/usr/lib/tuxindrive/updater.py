from __future__ import annotations

import hashlib
import base64
import json
import os
import platform
import shutil
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .bandwidth import GlobalBandwidthController


# 0.19.1 and later use a dedicated manifest so the legacy 0.18.1 channel can
# remain signed by its original key long enough to bridge existing installs.
MANIFEST_URLS = {
    "linux": "https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/update/latest-v2.json",
    "windows": "https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/releases/windows/latest-v2.json",
    "macos": "https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/releases/macos/latest-v2.json",
}
MANIFEST_URL = MANIFEST_URLS["linux"]
ALLOWED_PREFIXES = (
    "https://raw.githubusercontent.com/tpluharik/TuxInDrive/",
    "https://raw.githubusercontent.com/tpluharik/Tuxdrive/",
    "https://github.com/tpluharik/Tuxindrive/releases/download/",
    "https://github.com/tpluharik/TuxInDrive/releases/download/",
)
UPDATE_PUBLIC_KEY = "3c0BtMjwCmlZR0nw2jdqsAQQm7nYyd68r8BtnK2XzyY="
MAX_UPDATE_SIZE = 1024 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class UpdateRelease:
    version: str
    url: str
    sha256: str
    notes: str = ""
    expires_at: str = ""


def version_key(value: str) -> tuple[int, ...]:
    parts = value.removeprefix("v").split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid release version: {value}")
    return tuple(int(part) for part in parts)


def current_platform(system: str | None = None) -> str:
    host = system or platform.system()
    return {"Linux": "linux", "Windows": "windows", "Darwin": "macos"}.get(host, "linux")


def release_package_name(release: UpdateRelease, target_platform: str = "linux") -> str:
    name = Path(urlparse(release.url).path).name
    allowed = {
        "linux": {
            f"tuxindrive_{release.version}_all.deb",
            f"tuxdrive_{release.version}_all.deb",
        },
        "windows": {f"TuxInDrive-{release.version}-windows-x64-setup.exe"},
        "macos": {
            f"TuxInDrive-{release.version}-macos-x64.dmg",
            f"TuxInDrive-{release.version}-macos-arm64.dmg",
        },
        "android": {f"TuxInDrive-{release.version}-android.apk"},
    }
    if target_platform not in allowed or name not in allowed[target_platform]:
        raise ValueError("The update filename does not match the signed release version")
    return name


class UpdateManager:
    def __init__(
        self,
        current_version: str,
        cache_dir: Path | None = None,
        public_key: str = UPDATE_PUBLIC_KEY,
        target_platform: str | None = None,
        manifest_url: str | None = None,
        bandwidth: GlobalBandwidthController | None = None,
    ) -> None:
        self.current_version = current_version
        self.cache_dir = cache_dir or Path.home() / ".cache" / "tuxindrive" / "updates"
        self.public_key = public_key
        self.target_platform = target_platform or current_platform()
        self.manifest_url = manifest_url or MANIFEST_URLS[self.target_platform]
        self.bandwidth = bandwidth or GlobalBandwidthController()

    @staticmethod
    def parse_manifest(
        payload: bytes,
        public_key: str = UPDATE_PUBLIC_KEY,
        target_platform: str = "linux",
    ) -> UpdateRelease:
        data = json.loads(payload.decode("utf-8"))
        signed = {key: data[key] for key in ("version", "url", "sha256", "notes", "expires_at")}
        canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode("utf-8")
        try:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
            key.verify(base64.b64decode(str(data["signature"]), validate=True), canonical)
        except (KeyError, ValueError, InvalidSignature) as exc:
            raise ValueError("The update manifest signature is missing or invalid") from exc
        release = UpdateRelease(
            version=str(data["version"]),
            url=str(data["url"]),
            sha256=str(data["sha256"]).lower(),
            notes=str(data.get("notes", "")),
            expires_at=str(data["expires_at"]),
        )
        version_key(release.version)
        if not any(release.url.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            raise ValueError("The update package URL is not an approved TuxInDrive repository URL")
        release_package_name(release, target_platform)
        if len(release.sha256) != 64 or any(c not in "0123456789abcdef" for c in release.sha256):
            raise ValueError("The update manifest has an invalid SHA-256 checksum")
        try:
            expiry = datetime.fromisoformat(release.expires_at)
        except ValueError as exc:
            raise ValueError("The update manifest has an invalid expiry") from exc
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("The signed update manifest has expired")
        return release

    def check(self) -> UpdateRelease | None:
        request = urllib.request.Request(self.manifest_url, headers={"User-Agent": "TuxInDrive-Updater"})
        # A synchronization can hold the transfer gate for minutes. Update
        # discovery is a bounded control-plane request and must remain
        # responsive while transfers run; its bytes still use the shared
        # global download clock below.
        with self.bandwidth.control_plane_guard():
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read(128 * 1024)
                self.bandwidth.throttle_download(len(payload))
                release = self.parse_manifest(payload, self.public_key, self.target_platform)
        return release if version_key(release.version) > version_key(self.current_version) else None

    def download(
        self,
        release: UpdateRelease,
        progress: Callable[[int, int], None] | None = None,
    ) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        target = self.cache_dir / release_package_name(release, self.target_platform)
        temporary = target.with_name(f"{target.name}.part")

        # A retry after a closed dialog or interrupted installation should not
        # download the same immutable release again. Trust only a regular file
        # whose digest still matches the signed manifest.
        if target.is_file() and not target.is_symlink() and target.stat().st_size <= MAX_UPDATE_SIZE:
            cached_digest = hashlib.sha256()
            with target.open("rb") as cached:
                while chunk := cached.read(1024 * 1024):
                    cached_digest.update(chunk)
            if cached_digest.hexdigest() == release.sha256:
                size = target.stat().st_size
                if progress:
                    progress(size, size)
                return target
        target.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)

        request = urllib.request.Request(release.url, headers={"User-Agent": "TuxInDrive-Updater"})
        digest = hashlib.sha256()
        try:
            # A user-requested update has its own serialized lane so an active
            # long-running sync cannot starve it. Bytes remain governed by the
            # same global download clock as every other in-process transfer.
            with self.bandwidth.interactive_transfer_guard():
                with urllib.request.urlopen(request, timeout=60) as response, temporary.open("xb") as output:
                    total = int(response.headers.get("Content-Length", 0)) if hasattr(response, "headers") else 0
                    received = 0
                    while chunk := response.read(1024 * 1024):
                        self.bandwidth.throttle_download(len(chunk))
                        digest.update(chunk)
                        output.write(chunk)
                        received += len(chunk)
                        if received > MAX_UPDATE_SIZE:
                            raise ValueError("The update package exceeded its 1 GiB safety limit")
                        if progress:
                            progress(received, total)
            if digest.hexdigest() != release.sha256:
                raise ValueError("Downloaded package failed SHA-256 verification")
            temporary.replace(target)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        if progress:
            progress(target.stat().st_size, target.stat().st_size)
        return target

    def install(self, package: Path) -> None:
        package_path = package.expanduser().absolute()
        if self.target_platform == "windows":
            if not hasattr(os, "startfile"):
                raise RuntimeError("The Windows installer launcher is unavailable")
            os.startfile(str(package_path))  # type: ignore[attr-defined]
            return
        if self.target_platform == "macos":
            result = subprocess.run(
                ["open", str(package_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(result.stdout.strip() or "The macOS installer could not be opened")
            return
        pkexec = shutil.which("pkexec")
        if not pkexec:
            raise RuntimeError("The PolicyKit update helper (pkexec) is unavailable")
        helper = Path("/usr/lib/tuxindrive/update-helper")
        if not helper.is_file():
            raise RuntimeError("The privileged TuxInDrive update helper is unavailable; reinstall the current package")
        metadata = subprocess.run(
            ["/usr/bin/dpkg-deb", "--show", "--showformat=${Package} ${Version}", str(package_path)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
        )
        expected_version = package.name.removeprefix("tuxindrive_").removeprefix("tuxdrive_").removesuffix("_all.deb")
        expected_metadata = {f"tuxindrive {expected_version}", f"tuxdrive {expected_version}"}
        if metadata.returncode or metadata.stdout.strip() not in expected_metadata:
            raise RuntimeError("The verified update is not the expected TuxInDrive Debian package")
        result = subprocess.run(
            [pkexec, str(helper), str(package_path)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=600,
            check=False,
        )
        if result.returncode:
            detail = result.stdout.strip()[-2000:]
            raise RuntimeError(detail or f"Package installer exited with status {result.returncode}")
