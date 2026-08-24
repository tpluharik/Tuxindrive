"""Portable child-process lifecycle helpers."""

from __future__ import annotations

import os
import platform
import signal
import subprocess


def new_process_group() -> dict[str, object]:
    if platform.system() == "Windows":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        }
    return {"start_new_session": True}


def terminate_process(process: subprocess.Popen, *, force: bool = False) -> bool:
    if process.poll() is not None:
        return False
    try:
        if platform.system() == "Windows":
            process.kill() if force else process.terminate()
        else:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return False
    return True


def reload_process(process: subprocess.Popen) -> bool:
    if process.poll() is not None or platform.system() == "Windows":
        return False
    try:
        os.killpg(process.pid, signal.SIGHUP)
    except (ProcessLookupError, OSError):
        return False
    return True
