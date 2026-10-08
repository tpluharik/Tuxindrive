"""Portable child-process lifecycle helpers."""

from __future__ import annotations

import os
import platform
import select
import signal
import subprocess
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path


# Keep the real class: a patched Popen factory or a Mock(spec=Popen) is not an
# OS process. Never trust __index__, __class__ spoofing, or an arbitrary PID.
_POPEN_TYPE = subprocess.Popen
_OWNED_LOCK = threading.RLock()
_OWNED: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


@dataclass(frozen=True)
class _Identity:
    pid: int
    group: int
    session: int
    started: int


@dataclass
class _Ownership:
    pid: int
    system: str
    members: dict[int, tuple[int, _Identity]] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)

    def close(self) -> None:
        with self.lock:
            for descriptor, _identity in self.members.values():
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            self.members.clear()


def _valid_pid(pid) -> bool:
    return type(pid) is int and 1 < pid <= 2**31 - 1


def _native_process(process) -> bool:
    return type(process) is _POPEN_TYPE and _valid_pid(process.pid)


def _linux_identity(pid: int) -> _Identity | None:
    if not _valid_pid(pid):
        return None
    try:
        # comm can contain spaces and closing parentheses; fields after its
        # final ')' start at field 3 (state), not at the beginning of the file.
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="surrogateescape")
        head, separator, tail = raw.rpartition(")")
        fields = tail.split()
        if not separator or int(head.split("(", 1)[0]) != pid:
            return None
        return _Identity(pid, int(fields[2]), int(fields[3]), int(fields[19]))
    except (OSError, ValueError, IndexError, UnicodeError):
        return None


def _anchor_matches(owner: _Ownership) -> bool:
    for pid, (descriptor, identity) in owner.members.items():
        try:
            poller = select.poll()
            poller.register(descriptor, select.POLLIN)
            if (not poller.poll(0)
                    and _linux_identity(pid) == identity
                    and identity.group == owner.pid == identity.session):
                return True
        except (OSError, ValueError):
            continue
    return False


def _remember_linux_members(owner: _Ownership) -> None:
    """Pin members by pidfd while an original session member proves ownership."""
    if not owner.members or not _anchor_matches(owner):
        return
    try:
        candidates = os.listdir("/proc")
    except OSError:
        return
    for name in candidates:
        if not name.isdecimal():
            continue
        pid = int(name)
        identity = _linux_identity(pid)
        if identity is None or identity.group != owner.pid or identity.session != owner.pid:
            continue
        existing = owner.members.get(pid)
        if existing is not None and existing[1] == identity:
            continue
        try:
            descriptor = os.pidfd_open(pid, 0)
        except OSError:
            continue
        # Opening a descriptor must not race PID/session reuse. Verify both
        # the target's birth identity and the original session anchor again.
        if _linux_identity(pid) != identity or not _anchor_matches(owner):
            os.close(descriptor)
            continue
        if existing is not None:
            os.close(existing[0])
        owner.members[pid] = (descriptor, identity)


def _register_process(process) -> None:
    if not _native_process(process):
        return
    owner = _Ownership(process.pid, platform.system())
    if owner.system != "Windows":
        # Popen's wait/poll lock keeps the unreaped child's PID reserved while
        # its session is checked. An already reaped leader is never trusted.
        with process._waitpid_lock:
            if process.returncode is not None:
                return
            try:
                if (os.getpgid(owner.pid) != owner.pid
                        or os.getsid(owner.pid) != owner.pid
                        or owner.pid == os.getpgrp()):
                    return
                if (owner.system == "Linux" and hasattr(os, "pidfd_open")
                        and hasattr(signal, "pidfd_send_signal")):
                    identity = _linux_identity(owner.pid)
                    if identity is not None:
                        descriptor = os.pidfd_open(owner.pid, 0)
                        if _linux_identity(owner.pid) == identity:
                            owner.members[owner.pid] = (descriptor, identity)
                        else:
                            os.close(descriptor)
            except OSError:
                # Old kernels may lack pidfds. Only the still-unreaped owned
                # leader/group fallback below is allowed in that case.
                pass
    with _OWNED_LOCK:
        _OWNED[process] = owner
    weakref.finalize(process, owner.close)


def spawn_process(command, **kwargs):
    """Start and register an application-owned, isolated process group."""
    kwargs.update(new_process_group())
    process = subprocess.Popen(command, **kwargs)
    _register_process(process)
    return process


def _signal_owned(process, sig: int) -> bool:
    if not _native_process(process):
        return False
    with _OWNED_LOCK:
        owner = _OWNED.get(process)
    if owner is None or owner.pid != process.pid:
        return False
    with owner.lock:
        if owner.system == "Windows":
            if process.poll() is not None or sig == getattr(signal, "SIGHUP", None):
                return False
            try:
                process.kill() if sig == getattr(signal, "SIGKILL", 9) else process.terminate()
                return True
            except OSError:
                return False
        if owner.members:
            _remember_linux_members(owner)
            sent = False
            # Children first, then the leader. Stable descriptors cannot be
            # redirected at a different process even after wait()/PID reuse.
            for pid in sorted(owner.members, key=lambda value: value == owner.pid):
                descriptor, _identity = owner.members[pid]
                try:
                    signal.pidfd_send_signal(descriptor, sig, None, 0)
                    sent = True
                except OSError:
                    pass
            return sent
        # Portable POSIX fallback: never signal a group after its leader has
        # been reaped. Holding Popen's lock prevents concurrent wait()/poll()
        # from making this PID available to an unrelated process.
        if not process._waitpid_lock.acquire(blocking=False):
            return False
        try:
            if process.returncode is not None:
                return False
            try:
                if (os.getpgid(owner.pid) != owner.pid
                        or os.getsid(owner.pid) != owner.pid
                        or owner.pid == os.getpgrp()):
                    return False
                os.killpg(owner.pid, sig)
                return True
            except OSError:
                return False
        finally:
            process._waitpid_lock.release()


def new_process_group() -> dict[str, object]:
    if platform.system() == "Windows":
        return {
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        }
    return {"start_new_session": True}


def terminate_process(process: subprocess.Popen, *, force: bool = False) -> bool:
    return _signal_owned(process, getattr(signal, "SIGKILL", 9) if force else signal.SIGTERM)


def wait_process(process, *, timeout=None):
    """Portable waiters must not hold Popen's PID-reservation lock indefinitely."""
    if timeout is not None:
        return process.wait(timeout=timeout)
    if not _native_process(process):
        return process.wait()
    with _OWNED_LOCK:
        owner = _OWNED.get(process)
    if owner is None or owner.system == "Windows" or owner.members:
        return process.wait()
    while True:
        try:
            return process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            continue


def stop_process(process: subprocess.Popen, *, grace: float = 5) -> int:
    """Bound shutdown and reap helpers even if their group leader exits first."""
    terminate_process(process)
    try:
        return process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        terminate_process(process, force=True)
        return process.wait(timeout=grace)
    finally:
        # Only pinned Linux descendants can be signalled after leader reaping;
        # portable group signalling refuses that case even with force=True.
        terminate_process(process, force=True)


def run_process(command, *, timeout=None, check=False, capture_output=False, input=None, **kwargs):
    """Like subprocess.run, but a timeout also kills owned POSIX descendants."""
    if capture_output:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    process = spawn_process(command, **kwargs)
    try:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            terminate_process(process, force=True)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.wait(timeout=5)
            raise
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        if check:
            result.check_returncode()
        return result
    finally:
        # Popen.__exit__ calls an unbounded wait(). Do not enter that context
        # manager when the child could remain stuck even after a force signal.
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def reload_process(process: subprocess.Popen) -> bool:
    if not _native_process(process) or platform.system() == "Windows":
        return False
    if process.poll() is not None:
        return False
    return _signal_owned(process, signal.SIGHUP)
