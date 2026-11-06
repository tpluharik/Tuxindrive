#!/usr/bin/env python3
"""Opt-in native publisher verification; never provision or read private keys.

Production signing remains an external, protected operation. These gates stop
requested native-signing builds from silently shipping unsigned/ad-hoc files.
Unsigned local/development builds remain available with the default mode (0).
"""
import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile


def command(arguments, environment=None):
    result = subprocess.run(arguments, capture_output=True, text=True,
        timeout=120, check=False, env=environment)
    if result.returncode:
        raise ValueError("Native verification failed: " + arguments[0])
    return result.stdout + result.stderr


def required(environment, target):
    value = environment.get("TUXINDRIVE_REQUIRE_" + target + "_SIGNING", "0")
    if value not in {"0", "1"}:
        raise ValueError("Native signing mode must be exactly 0 or 1")
    return value == "1"


def verify_windows(directory, version, environment):
    expected = environment.get("TUXINDRIVE_WINDOWS_CERT_SHA256", "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Native Windows signing requires the approved certificate SHA-256")
    if platform.system() != "Windows":
        raise ValueError("Authenticode verification requires Windows")
    script = """+$ErrorActionPreference = 'Stop'
$s = Get-AuthenticodeSignature -LiteralPath $env:TUXINDRIVE_SIGNATURE_FILE
$hash = ''
if ($null -ne $s.SignerCertificate) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { $hash = [BitConverter]::ToString($sha.ComputeHash($s.SignerCertificate.RawData)).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
}
@{status=[string]$s.Status; sha256=$hash; timestamp=($null -ne $s.TimeStamperCertificate)} | ConvertTo-Json -Compress
"""

    def verify(path):
        result = json.loads(command(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            {**environment, "TUXINDRIVE_SIGNATURE_FILE": str(path.resolve())}))
        if (result.get("status") != "Valid" or result.get("sha256") != expected
                or result.get("timestamp") is not True):
            raise ValueError("Invalid, untimestamped or unexpected Windows publisher signature")

    verify(directory / ("TuxInDrive-" + version + "-windows-x64-setup.exe"))
    portable = directory / ("TuxInDrive-" + version + "-windows-x64-portable.zip")
    # Only our two entry points are extracted, to fixed private filenames.
    # Dependencies retain their upstream identities; never re-sign them as ours.
    with tempfile.TemporaryDirectory(prefix="tuxindrive-authenticode-") as temporary, zipfile.ZipFile(portable) as archive:
        for name in ("TuxInDrive.exe", "tuxindrive-rclone-password.exe"):
            matches = [member for member in archive.infolist() if member.filename == name]
            if len(matches) != 1 or not 0 < matches[0].file_size <= 256 * 1024**2:
                raise ValueError("Missing, ambiguous or oversized portable entry point")
            target = Path(temporary) / name
            with archive.open(matches[0]) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            verify(target)


def mac_identity(details, team, runtime):
    fields = details.splitlines()
    if ("TeamIdentifier=" + team not in fields
            or not any(line.startswith("Authority=Developer ID Application:") for line in fields)
            or any(line == "Signature=adhoc" for line in fields)):
        raise ValueError("Expected the approved Apple Developer ID Application identity")
    if runtime and not re.search(r"flags=0x[0-9a-fA-F]+\([^\n)]*\bruntime\b", details):
        raise ValueError("Apple executable is missing hardened runtime")


def verify_macos(directory, version, app, environment):
    team = environment.get("TUXINDRIVE_APPLE_TEAM_ID", "")
    if not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise ValueError("Native macOS signing requires the approved Apple Team ID")
    if platform.system() != "Darwin":
        raise ValueError("Developer ID/notarization verification requires macOS")
    images = list(directory.glob("TuxInDrive-" + version + "-macos-*.dmg"))
    if len(images) != 1:
        raise ValueError("Expected exactly one macOS disk image")
    for target, runtime in ((app, True), (app / "Contents/Resources/rclone-password", True), (images[0], False)):
        command(["codesign", "--verify", "--deep", "--strict", str(target)])
        mac_identity(command(["codesign", "--display", "--verbose=4", str(target)]), team, runtime)
    command(["xcrun", "stapler", "validate", str(images[0])])
    command(["spctl", "--assess", "--type", "execute", "--verbose=2", str(app)])
    command(["spctl", "--assess", "--type", "open", "--context", "context:primary-signature", str(images[0])])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("windows", "macos"), required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--directory", type=Path, default=Path("dist"))
    parser.add_argument("--app", type=Path, default=Path("build/macos/TuxInDrive.app"))
    args = parser.parse_args()
    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error("Expected an exact product version")
    enabled = required(os.environ, args.platform.upper())
    if enabled:
        if args.platform == "windows":
            verify_windows(args.directory, args.version, os.environ)
        else:
            verify_macos(args.directory, args.version, args.app, os.environ)
    print(json.dumps({"platform": args.platform, "native_signing_required": enabled,
        "native_signature_verified": enabled, "status": "verified" if enabled else "pending-not-configured"}))


if __name__ == "__main__":
    main()
