"""Tests always install the fail-closed signal guard before app imports."""

from . import signal_safety  # noqa: F401
