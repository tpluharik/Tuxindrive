"""Narrow privileged operations used by the server administration GUI.

The module deliberately exposes no shell or arbitrary destination path.  It is
invoked through pkexec by the unprivileged GUI and always operates on the
package-owned server configuration and bootstrap-token locations.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import stat
import sys
from dataclasses import asdict
from pathlib import Path

from .server import ServerConfig, ServerError, _private_write, load_config


CONFIG_PATH = Path("/etc/tuxindrive-server/server.json")
STATE_PATH = Path("/var/lib/tuxindrive-server")
BOOTSTRAP_TOKEN_PATH = STATE_PATH / "bootstrap-token"
MAX_CONFIG_BYTES = 256 * 1024


def _require_root() -> None:
    if os.geteuid() != 0:
        raise ServerError("Administrative server operation requires root authorization")


def _calling_uid() -> int:
    raw = os.environ.get("PKEXEC_UID", "")
    if not raw.isdecimal():
        raise ServerError("Administrative operation must be started through pkexec")
    return int(raw)


def _read_owned_source(path: Path) -> dict:
    """Read a bounded, non-symlink staging file owned by the pkexec caller."""
    uid = _calling_uid()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ServerError("Configuration source must be a regular file")
        if metadata.st_uid != uid:
            raise ServerError("Configuration source is not owned by the authorizing user")
        if metadata.st_mode & 0o077:
            raise ServerError("Configuration source must have mode 0600")
        if metadata.st_size > MAX_CONFIG_BYTES:
            raise ServerError("Configuration source is too large")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ServerError(f"Configuration is not valid JSON: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(raw, dict):
        raise ServerError("Server configuration must be a JSON object")
    return raw


def _service_identity() -> tuple[int, int]:
    try:
        account = pwd.getpwnam("tuxindrive-server")
    except KeyError as exc:
        raise ServerError("The tuxindrive-server system account is missing") from exc
    return account.pw_uid, account.pw_gid


def write_configuration(source: Path) -> None:
    _require_root()
    raw = _read_owned_source(source)
    validated = ServerConfig.from_dict(raw)
    _uid, gid = _service_identity()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    _private_write(
        CONFIG_PATH,
        json.dumps(asdict(validated), indent=2) + "\n",
        mode=0o640,
        uid=0,
        gid=gid,
        require_root_parent=True,
    )


def read_configuration() -> dict:
    _require_root()
    return asdict(load_config(CONFIG_PATH))


def read_bootstrap_token() -> str:
    _require_root()
    try:
        return BOOTSTRAP_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise ServerError("The bootstrap token has already been removed") from exc


def delete_bootstrap_token() -> None:
    _require_root()
    try:
        BOOTSTRAP_TOKEN_PATH.unlink()
    except FileNotFoundError:
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TuxInDrive privileged GUI helper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("read-config")
    write = sub.add_parser("write-config")
    write.add_argument("--source", type=Path, required=True)
    sub.add_parser("read-bootstrap-token")
    sub.add_parser("delete-bootstrap-token")
    args = parser.parse_args(argv)
    try:
        if args.command == "read-config":
            print(json.dumps(read_configuration(), indent=2))
        elif args.command == "write-config":
            write_configuration(args.source)
        elif args.command == "read-bootstrap-token":
            print(read_bootstrap_token())
        elif args.command == "delete-bootstrap-token":
            delete_bootstrap_token()
        return 0
    except (OSError, ServerError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
