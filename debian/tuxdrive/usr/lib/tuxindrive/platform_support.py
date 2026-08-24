"""Host capability discovery for portable Debian-family installations."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .proton import ProtonDriveClient


@dataclass(frozen=True, slots=True)
class FeatureCheck:
    name: str
    available: bool
    required: bool
    detail: str
    install_hint: str = ""


def _os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"')
    except OSError:
        pass
    return values


def _command(name: str, required: bool, detail: str, hint: str) -> FeatureCheck:
    location = shutil.which(name)
    return FeatureCheck(name, bool(location), required, location or detail, hint)


def inspect_host() -> dict[str, object]:
    release = _os_release()
    system = platform.system()
    is_macos = system == "Darwin"
    is_windows = system == "Windows"
    machine = platform.machine().lower()
    supported_arch = machine in {"x86_64", "amd64", "aarch64", "arm64"}
    desktop = "Aqua" if is_macos else "Windows Shell" if is_windows else os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    session = "Quartz" if is_macos else "Win32" if is_windows else os.environ.get("XDG_SESSION_TYPE", "unknown")
    checks = [
        FeatureCheck("Windows Credential Manager", True, True, "Native keyring backend") if is_windows else
        _command(
            "security" if is_macos else "secret-tool", True,
            "macOS Keychain client missing" if is_macos else "Secret Service client missing",
            "The macOS security utility is required" if is_macos else "Install libsecret-tools and enable a Secret Service keyring",
        ),
        _command("explorer.exe" if is_windows else "open" if is_macos else "xdg-open", True, "Desktop URL opener missing", "Repair the Windows shell" if is_windows else "Install xdg-utils"),
        FeatureCheck(
            "macFUSE", Path("/Library/Filesystems/macfuse.fs").exists(), False,
            "/Library/Filesystems/macfuse.fs" if Path("/Library/Filesystems/macfuse.fs").exists() else "Experimental streaming unavailable",
            "Install and approve macFUSE, then reboot" if is_macos else "",
        ) if is_macos else
        FeatureCheck("WinFsp", bool(os.environ.get("ProgramFiles")) and (Path(os.environ["ProgramFiles"]) / "WinFsp").exists(), False, "Installed" if bool(os.environ.get("ProgramFiles")) and (Path(os.environ["ProgramFiles"]) / "WinFsp").exists() else "Streaming unavailable", "Install WinFsp to enable streaming drives") if is_windows else
        _command("fusermount3", False, "Streaming unavailable", "Install fuse3 and permit access to /dev/fuse"),
        FeatureCheck("Finder integration", False, False, "Not included in the desktop package", "Use the TuxInDrive application controls") if is_macos else
        FeatureCheck("Explorer integration", False, False, "Not included in the first desktop package", "Use the TuxInDrive application controls") if is_windows else
        _command("nautilus", False, "Nautilus integration unavailable", "Install nautilus and python3-nautilus, or leave integration disabled"),
        FeatureCheck("signed updater", True, False, "Signed in-app platform update channel") if is_macos or is_windows else
        _command("pkexec", False, "In-app package installation unavailable", "Install the distribution's PolicyKit pkexec package"),
        FeatureCheck("desktop notifications", True, False, "Windows notification service") if is_windows else
        _command("osascript" if is_macos else "notify-send", False, "Desktop notifications unavailable", "Install libnotify-bin"),
        FeatureCheck(
            "proton-drive",
            ProtonDriveClient().available(),
            False,
            (
                shutil.which("proton-drive")
                or (str(ProtonDriveClient.managed_path()) if ProtonDriveClient.managed_path().is_file() else "Official Proton Drive synchronization unavailable")
            ),
            "Use Connect account → Proton Drive → Install CLI and connect",
        ),
        FeatureCheck("metered-network policy", False, False, "NetworkManager policy probe is Linux-only", "Use schedule/battery policies") if is_macos or is_windows else
        _command("nmcli", False, "Metered-network policies unavailable", "Install and enable NetworkManager"),
        _command("tor", False, "Onion transport unavailable", "Install tor and torsocks"),
        _command("obfs4proxy", False, "Obfs4 bridge profile unavailable", "Install obfs4proxy"),
        _command("upnpc", False, "UPnP NAT traversal unavailable", "Install miniupnpc"),
        _command("natpmpc", False, "NAT-PMP traversal unavailable", "Install natpmpc"),
        _command("qrencode", False, "QR invitation rendering unavailable", "Install qrencode"),
        _command("zbarimg", False, "QR invitation scanning unavailable", "Install zbar-tools"),
    ]
    try:
        crypto_version = importlib.metadata.version("cryptography")
    except importlib.metadata.PackageNotFoundError:
        crypto_version = "missing"
    checks.insert(0, FeatureCheck("cryptography", crypto_version != "missing", True, crypto_version, "Install python3-cryptography"))
    required_ok = supported_arch and all(item.available for item in checks if item.required)
    return {
        "schema": 1,
        "distribution": platform.mac_ver()[0] and f"macOS {platform.mac_ver()[0]}" if is_macos else platform.platform() if is_windows else release.get("PRETTY_NAME", release.get("ID", "unknown")),
        "distribution_id": "macos" if is_macos else "windows" if is_windows else release.get("ID", "unknown"),
        "distribution_like": release.get("ID_LIKE", ""),
        "architecture": machine,
        "architecture_supported": supported_arch,
        "desktop": desktop,
        "session": session,
        "installation": {
            "launcher": "%LOCALAPPDATA%\\Programs\\TuxInDrive\\TuxInDrive.exe" if is_windows else "/Applications/TuxInDrive.app/Contents/MacOS/tuxindrive" if is_macos else "/usr/bin/tuxindrive",
            "application": "%LOCALAPPDATA%\\Programs\\TuxInDrive" if is_windows else "/Applications/TuxInDrive.app" if is_macos else "/usr/lib/tuxindrive",
            "nautilus_extension": "unavailable" if is_macos or is_windows else "/usr/share/nautilus-python/extensions/tuxindrive.py",
            "machine_report": "user-session only" if is_macos or is_windows else "/var/lib/tuxindrive/install-capabilities.json",
            "user_configuration": "%APPDATA%\\tuxindrive" if is_windows else "~/Library/Application Support/tuxindrive" if is_macos else "${XDG_CONFIG_HOME:-~/.config}/tuxindrive",
        },
        "required_ready": required_ok,
        "features": [asdict(item) for item in checks],
    }


def format_report(report: dict[str, object]) -> str:
    status = "READY" if report["required_ready"] else "INCOMPLETE"
    lines = [
        f"TuxInDrive system check: {status}",
        f"Host: {report['distribution']} · {report['architecture']} · {report['desktop']} ({report['session']})",
        f"Installed application: {report['installation']['application']}",
    ]
    if not report["architecture_supported"]:
        lines.append("[required] architecture: unsupported (use amd64 or arm64)")
    for item in report["features"]:
        marker = "ok" if item["available"] else ("MISSING" if item["required"] else "optional")
        lines.append(f"[{marker}] {item['name']}: {item['detail']}")
        if not item["available"] and item["install_hint"]:
            lines.append(f"         {item['install_hint']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check TuxInDrive host integration support")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = inspect_host()
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["required_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
