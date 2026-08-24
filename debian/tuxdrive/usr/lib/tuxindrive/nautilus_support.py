"""Desktop-independent helpers for Nautilus availability actions."""

from __future__ import annotations

import os
from pathlib import Path


def command_line_path(arguments: list[str], name: str) -> str:
    """Read both ``--name PATH`` and ``--name=PATH`` fallback forms."""
    option_name = f"--{name}"
    for index, argument in enumerate(arguments):
        if argument == option_name and index + 1 < len(arguments):
            return arguments[index + 1]
        if argument.startswith(option_name + "="):
            return argument.split("=", 1)[1]
    return ""


def availability_route(*, mounted: bool, runtime_ready: bool, enabled: bool) -> str:
    """Choose immediate hydration, mount startup, or a cold-start queue."""
    if mounted:
        return "dispatch"
    if runtime_ready and enabled:
        return "start-mount"
    return "queue"


def lexical_relative_path(value: str | Path, root: str | Path) -> str:
    """Return a mount-relative path without resolving or statting a FUSE item.

    Nautilus already supplies a local path.  Resolving an individual streamed
    file here can block on the provider or fail with ``ENOTCONN`` while the
    containing mount is otherwise usable.  The engine performs the later
    no-symlink confinement check before it opens any selected item.
    """
    selected = Path(os.path.abspath(os.path.expanduser(os.fspath(value))))
    mount_root = Path(os.path.abspath(os.path.expanduser(os.fspath(root))))
    relative = selected.relative_to(mount_root).as_posix()
    return "." if relative in {"", "."} else relative.strip("/")


def rule_matches(relative: str, rule: str) -> bool:
    """Return whether *rule* applies to a mount-relative path."""
    return rule == "." or relative == rule or relative.startswith(rule.rstrip("/") + "/")


def is_available_offline(
    relative: str,
    offline_rules: list[str] | set[str],
    online_only_rules: list[str] | set[str] = (),
) -> bool:
    """Resolve nested offline/online-only rules using the most specific rule."""
    candidates: list[tuple[int, bool]] = []
    for rule in offline_rules:
        if rule_matches(relative, rule):
            candidates.append((0 if rule == "." else len(rule.split("/")), True))
    for rule in online_only_rules:
        if rule_matches(relative, rule):
            # An equally specific explicit online-only rule wins.
            candidates.append((0 if rule == "." else len(rule.split("/")), False))
    return max(candidates, default=(-1, False), key=lambda item: (item[0], not item[1]))[1]


def verified_rules_after(
    verified: set[str],
    configured: list[str],
    relative: str,
    available: bool,
) -> set[str]:
    """Return only offline rules whose latest hydration has completed."""
    result = set(verified)
    if available and relative in configured:
        if relative == ".":
            result.clear()
        else:
            result = {
                item for item in result
                if not item.startswith(relative.rstrip("/") + "/")
            }
        result.add(relative)
    elif not available:
        result.intersection_update(configured)
    return result
