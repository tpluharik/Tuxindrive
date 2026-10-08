"""Unit tests may mock signals, but may never send real terminating signals.

Import this before application modules. There is intentionally no environment
variable or context manager to disable it. Real lifecycle checks live outside
this package and run only in an explicitly opted-in disposable container.
"""

import os
import signal
import sys


class RealSignalBlocked(RuntimeError):
    pass


def _deny(*args, **kwargs):
    raise RealSignalBlocked("Real process signals are forbidden in unit tests; mock the endpoint")


_original_kill = os.kill


def _probe_only(pid, sig):
    if type(pid) is int and pid > 1 and type(sig) is int and sig == 0:
        return _original_kill(pid, sig)
    return _deny()


def _audit(event, arguments):
    if event == "os.kill":
        if (len(arguments) == 2 and type(arguments[0]) is int
                and arguments[0] > 1 and type(arguments[1]) is int and arguments[1] == 0):
            return
        _deny()
    if event in ("os.killpg", "signal.pthread_kill", "signal.raise_signal", "signal.pidfd_send_signal"):
        _deny()


# Auditing also catches an os.kill/killpg alias cached before monkey-patching.
sys.addaudithook(_audit)
os.kill = _probe_only
if hasattr(os, "killpg"):
    os.killpg = _deny
for _name in ("pidfd_send_signal", "pthread_kill", "raise_signal"):
    if hasattr(signal, _name):
        setattr(signal, _name, _deny)
if sys.platform == "win32":
    import _winapi

    _winapi.TerminateProcess = _deny
