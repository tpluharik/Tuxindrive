"""Native credential-store access for the optional TuxInDrive server token."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from urllib.parse import urlsplit


SERVICE = "io.github.tuxindrive.TuxInDrive"
SECRET_TOOL = "/usr/bin/secret-tool"
TIMEOUT = 10


def credential_account(url: str) -> str:
    parsed = urlsplit(url)
    authority = parsed.netloc.lower()
    if not authority:
        raise RuntimeError("The TuxInDrive server URL is invalid")
    return "server-api-" + hashlib.sha256(authority.encode("utf-8")).hexdigest()[:24]


def _keyring():
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - packaged desktop dependency
        raise RuntimeError("The native credential-store integration is unavailable") from exc
    return keyring


def load_server_token(url: str) -> str:
    account = credential_account(url)
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                [SECRET_TOOL, "lookup", "application", "tuxindrive", "purpose", account],
                check=False, capture_output=True, text=True, timeout=TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The native credential-store integration is unavailable") from exc
        if result.returncode == 0 and result.stdout.rstrip("\r\n"):
            return result.stdout.rstrip("\r\n")
        raise RuntimeError("No API token is stored for this TuxInDrive server")
    token = _keyring().get_password(SERVICE, account)
    if not token:
        raise RuntimeError("No API token is stored for this TuxInDrive server")
    return token


def store_server_token(url: str, token: str) -> None:
    if not token or len(token) > 4096 or any(ord(char) < 32 for char in token):
        raise RuntimeError("The TuxInDrive server token is invalid")
    account = credential_account(url)
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run(
                [SECRET_TOOL, "store", "--label=TuxInDrive server API", "application", "tuxindrive", "purpose", account],
                input=token, check=False, capture_output=True, text=True, timeout=TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The native credential-store integration is unavailable") from exc
        if result.returncode != 0:
            raise RuntimeError("The native credential-store integration is unavailable")
        return
    _keyring().set_password(SERVICE, account, token)
