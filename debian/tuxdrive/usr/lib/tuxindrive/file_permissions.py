"""Best-effort POSIX modes without breaking native Windows storage ACLs."""

from __future__ import annotations

import os


def private_descriptor(descriptor: int, mode: int = 0o600) -> None:
    fchmod = getattr(os, "fchmod", None)
    if fchmod is not None:
        fchmod(descriptor, mode)
