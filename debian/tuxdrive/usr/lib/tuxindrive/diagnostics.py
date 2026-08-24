from __future__ import annotations

import faulthandler
import logging
import os
import platform
import sys
import threading
import traceback
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import branded_root


LOGGER_NAME = "tuxindrive"


def state_home() -> Path:
    system = platform.system()
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Logs"
    if system == "Darwin":
        return Path.home() / "Library" / "Logs"
    configured = os.environ.get("XDG_STATE_HOME")
    return Path(configured) if configured else Path.home() / ".local" / "state"


def log_directory() -> Path:
    return branded_root(state_home())


def crash_log_path() -> Path:
    return log_directory() / "crash.log"


def application_log_path() -> Path:
    return log_directory() / "tuxindrive.log"


def configure_logging(version: str) -> logging.Logger:
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            application_log_path(), maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s")
        )
        logger.addHandler(handler)
        os.chmod(application_log_path(), 0o600)
    logger.info(
        "Starting TuxInDrive %s; Python=%s; platform=%s; display=%s; desktop=%s",
        version,
        platform.python_version(),
        platform.platform(),
        os.environ.get("XDG_SESSION_TYPE", "unknown"),
        os.environ.get("XDG_CURRENT_DESKTOP", "unknown"),
    )
    return logger


def install_crash_handlers(logger: logging.Logger) -> None:
    crash_log_path().touch(mode=0o600, exist_ok=True)
    os.chmod(crash_log_path(), 0o600)
    crash_file = crash_log_path().open("a", encoding="utf-8", buffering=1)
    crash_file.write(
        f"\n=== TuxInDrive process started {datetime.now(timezone.utc).isoformat()} ===\n"
    )
    try:
        faulthandler.enable(crash_file, all_threads=True)
    except (RuntimeError, OSError):
        logger.exception("Could not enable faulthandler")

    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        logger.critical("Unhandled exception\n%s", formatted)
        crash_file.write(formatted)
        crash_file.flush()

    def handle_thread(args: threading.ExceptHookArgs) -> None:
        handle_exception(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = handle_exception
    threading.excepthook = handle_thread


def log_boot_failure(message: str) -> None:
    directory = log_directory()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    crash_log_path().touch(mode=0o600, exist_ok=True)
    os.chmod(crash_log_path(), 0o600)
    with crash_log_path().open("a", encoding="utf-8") as handle:
        handle.write(
            f"[{datetime.now(timezone.utc).isoformat()}] STARTUP FAILURE\n{message}\n"
        )
