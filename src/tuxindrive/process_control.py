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
    if process.poll() is not None and (not force or platform.system() == "Windows"):
        return False
    try:
        if platform.system() == "Windows":
            process.kill() if force else process.terminate()
        else:
            if not isinstance(process.pid, int) or process.pid <= 1:
                return False
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
    except (ProcessLookupError, OSError):
        return False
    return True


def stop_process(process: subprocess.Popen, *, grace: float = 5) -> int:
    """Bound shutdown and reap helpers even if their group leader exits first."""
    terminate_process(process)
    try:
        return process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        terminate_process(process, force=True)
        return process.wait(timeout=grace)
    finally:
        # A helper may ignore SIGTERM after rclone has already exited.
        terminate_process(process, force=True)


def run_process(command, *, timeout=None, check=False, capture_output=False, input=None, **kwargs):
    """Like subprocess.run, but a timeout also kills owned POSIX descendants."""
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    with subprocess.Popen(command, **kwargs, **new_process_group()) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process(process, force=True)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # Do not wait forever on inherited pipes on Windows either.
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                process.wait(timeout=5)
            raise
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result


def reload_process(process: subprocess.Popen) -> bool:
    if process.poll() is not None or platform.system() == "Windows":
        return False
    try:
        os.killpg(process.pid, signal.SIGHUP)
    except (ProcessLookupError, OSError):
        return False
    return True
