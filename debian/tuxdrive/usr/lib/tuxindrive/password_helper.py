"""Store the rclone configuration password in the native desktop key store."""

from __future__ import annotations

import argparse
import secrets
import subprocess
import sys


SERVICE = "io.github.tuxindrive.TuxInDrive"
LEGACY_SERVICE = "io.github.tuxdrive.TuxDrive"
ACCOUNT = "rclone-config"
SECRET_TOOL = "/usr/bin/secret-tool"
SECRET_TOOL_TIMEOUT = 10


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - desktop package dependency
        raise RuntimeError("The native credential-store integration is unavailable") from exc
    return keyring


def _uses_secret_tool() -> bool:
    return sys.platform.startswith("linux")


def _secret_tool_application(service: str) -> str:
    if service == SERVICE:
        return "tuxindrive"
    if service == LEGACY_SERVICE:
        return "tuxdrive"
    raise RuntimeError("The native credential-store request is invalid")


def _secret_tool_lookup(service: str) -> str | None:
    try:
        result = subprocess.run(
            [
                SECRET_TOOL,
                "lookup",
                "application",
                _secret_tool_application(service),
                "purpose",
                ACCOUNT,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=SECRET_TOOL_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("The native credential-store integration is unavailable") from exc
    if result.returncode == 0:
        return result.stdout.rstrip("\r\n") or None
    if result.returncode == 1 and not result.stderr.strip():
        return None
    raise RuntimeError("The native credential-store integration is unavailable")


def _secret_tool_store(password: str) -> None:
    try:
        result = subprocess.run(
            [
                SECRET_TOOL,
                "store",
                "--label=TuxInDrive rclone configuration",
                "application",
                "tuxindrive",
                "purpose",
                ACCOUNT,
            ],
            input=password,
            check=False,
            capture_output=True,
            text=True,
            timeout=SECRET_TOOL_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("The native credential-store integration is unavailable") from exc
    if result.returncode != 0:
        raise RuntimeError("The native credential-store integration is unavailable")


def _get_password(service: str) -> str | None:
    if _uses_secret_tool():
        return _secret_tool_lookup(service)
    return _keyring().get_password(service, ACCOUNT)


def _set_password(password: str) -> None:
    if _uses_secret_tool():
        _secret_tool_store(password)
        return
    _keyring().set_password(SERVICE, ACCOUNT, password)


def configuration_password(ensure: bool = False) -> str:
    password = _get_password(SERVICE)
    if not password:
        password = _get_password(LEGACY_SERVICE)
    if not password and ensure:
        password = secrets.token_urlsafe(48)
        _set_password(password)
    if not password:
        raise RuntimeError("TuxInDrive configuration key is unavailable")
    return password


def store_configuration_password(password: str) -> None:
    if not password or len(password) > 1024:
        raise RuntimeError("The TuxInDrive configuration key is invalid")
    _set_password(password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--ensure", action="store_true")
    args = parser.parse_args(argv)
    try:
        print(configuration_password(args.ensure))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
