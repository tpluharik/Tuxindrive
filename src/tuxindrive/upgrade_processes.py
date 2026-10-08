"""Exact, pidfd-pinned Linux application shutdown during package upgrades."""

from __future__ import annotations

import os
from pathlib import Path
import re
import select
import signal
import time

from .process_control import _linux_identity, _valid_pid


_LAUNCH_CODES = frozenset(
    f'import runpy,sys; sys.path.insert(0,"/usr/lib"); {prefix}'
    f'runpy.run_module("{module}.app",run_name="__main__")'
    for module in ("tuxindrive", "tuxdrive")
    for prefix in ("", f'sys.argv[0]="{module}"; ')
)
_PYTHON = re.compile(r"/usr/bin/python3(?:\.\d+)?\Z")


def _is_application(pid: int) -> bool:
    if not _valid_pid(pid) or pid == os.getpid():
        return False
    try:
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        executable = os.readlink(f"/proc/{pid}/exe")
        return (len(arguments) >= 4 and _PYTHON.fullmatch(executable) is not None
                and _PYTHON.fullmatch(os.fsdecode(arguments[0])) is not None
                and arguments[1:3] == [b"-I", b"-c"]
                and os.fsdecode(arguments[3]) in _LAUNCH_CODES)
    except (OSError, UnicodeError):
        return False


def stop_previous_applications(*, grace: float = 5.0) -> int:
    """Never fall back to substring matching, cached numeric PIDs or killall."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return 0
    descriptors = []
    stopped = 0
    try:
        for name in os.listdir("/proc"):
            if not name.isdecimal():
                continue
            pid = int(name)
            if not _is_application(pid):
                continue
            identity = _linux_identity(pid)
            if identity is None:
                continue
            try:
                descriptor = os.pidfd_open(pid, 0)
            except OSError:
                continue
            # A PID might have been reused between discovery and opening.
            if _linux_identity(pid) != identity or not _is_application(pid):
                os.close(descriptor)
                continue
            descriptors.append(descriptor)
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGINT, None, 0)
                stopped += 1
            except OSError:
                pass
        deadline = time.monotonic() + max(0.0, grace)
        pending = list(descriptors)
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            exited, _, _ = select.select(pending, [], [], remaining)
            pending = [descriptor for descriptor in pending if descriptor not in exited]
        for descriptor in pending:
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM, None, 0)
            except OSError:
                pass
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    return stopped
