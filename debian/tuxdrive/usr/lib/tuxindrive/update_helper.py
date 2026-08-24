"""Privileged, fail-closed installation of a signed TuxInDrive update.

The desktop process deliberately cannot tell this helper which digest to trust.
The helper retrieves and verifies the signed repository manifest again, copies
the untrusted user-owned package into a root-only directory, and verifies that
immutable copy before apt is allowed to process maintainer scripts.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from .updater import MANIFEST_URL, MAX_UPDATE_SIZE, UpdateManager, release_package_name


class PrivilegedUpdateError(RuntimeError):
    pass


def _signed_release():
    request = urllib.request.Request(MANIFEST_URL, headers={"User-Agent": "TuxInDrive-Privileged-Updater"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(128 * 1024)
    return UpdateManager.parse_manifest(payload)


def stage_verified_package(source: Path, destination: Path, release) -> Path:
    expected_name = release_package_name(release)
    if source.name != expected_name:
        raise PrivilegedUpdateError("The selected package is not the signed current TuxInDrive release")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        raise PrivilegedUpdateError("The update package could not be opened safely") from exc
    digest = hashlib.sha256()
    copied = 0
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > MAX_UPDATE_SIZE:
            raise PrivilegedUpdateError("The update package is not a safe regular file")
        invoking_uid = os.environ.get("PKEXEC_UID")
        if invoking_uid and source_stat.st_uid != int(invoking_uid):
            raise PrivilegedUpdateError("The update package is not owned by the requesting user")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            while chunk := os.read(source_fd, 1024 * 1024):
                copied += len(chunk)
                if copied > MAX_UPDATE_SIZE:
                    raise PrivilegedUpdateError("The update package exceeded its safety limit")
                digest.update(chunk)
                view = memoryview(chunk)
                while view:
                    written = os.write(destination_fd, view)
                    view = view[written:]
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)
    if copied == 0 or digest.hexdigest() != release.sha256:
        raise PrivilegedUpdateError("The privileged package digest does not match the signed manifest")
    return destination


def install(package: Path) -> None:
    if os.geteuid() != 0:
        raise PrivilegedUpdateError("The update helper must run through PolicyKit")
    release = _signed_release()
    with tempfile.TemporaryDirectory(prefix="tuxindrive-update-", dir="/var/tmp") as directory:
        root = Path(directory)
        os.chmod(root, 0o700)
        staged = stage_verified_package(package, root / release_package_name(release), release)
        metadata = subprocess.run(
            ["/usr/bin/dpkg-deb", "--show", "--showformat=${Package} ${Version}", str(staged)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
        )
        expected_metadata = {f"tuxindrive {release.version}", f"tuxdrive {release.version}"}
        if metadata.returncode or metadata.stdout.strip() not in expected_metadata:
            raise PrivilegedUpdateError("The signed file is not the expected TuxInDrive Debian package")
        result = subprocess.run(
            ["/usr/bin/apt-get", "install", "-y", str(staged)],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600, check=False,
        )
        if result.returncode:
            raise PrivilegedUpdateError(result.stdout.strip()[-2000:] or "Package installation failed")


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 1:
        print("Usage: tuxindrive-update-helper PACKAGE.deb", file=sys.stderr)
        return 2
    try:
        install(Path(values[0]))
    except (OSError, ValueError, PrivilegedUpdateError) as exc:
        print(f"TuxInDrive update refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
