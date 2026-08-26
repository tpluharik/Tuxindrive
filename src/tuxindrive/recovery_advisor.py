"""Deterministic, offline recovery guidance for synchronization failures."""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class RecoveryAdvice:
    code: str
    title: str
    explanation: str
    steps: tuple[str, ...]


_RULES: tuple[tuple[re.Pattern[str], RecoveryAdvice], ...] = (
    (
        re.compile(r"auth|token|credential|unauthori[sz]ed|access denied|invalid_grant", re.I),
        RecoveryAdvice(
            "authorization",
            "Reconnect the cloud account",
            "The provider rejected or could not refresh the stored authorization.",
            ("Open the account menu and choose Reconnect.", "Complete the provider's browser sign-in, then use Sync now."),
        ),
    ),
    (
        re.compile(r"bisync.*(?:resync|listing|state)|prior path.*missing|must run.*resync", re.I),
        RecoveryAdvice(
            "bisync-state",
            "Repair the two-way synchronization baseline",
            "The durable comparison state is missing or no longer matches the two endpoints.",
            ("Keep both endpoints unchanged while recovery runs.", "Re-enable the folder and use Sync now; TuxInDrive will perform its conservative recovery sync."),
        ),
    ),
    (
        re.compile(r"mass.change|ransomware|protection paused|too many (?:changes|deletions)", re.I),
        RecoveryAdvice(
            "bulk-protection",
            "Review the bulk change before retrying",
            "Safety protection stopped a large or ransomware-shaped change set.",
            ("Open the job log and verify that the listed changes are expected.", "Restore unexpected files, or re-enable the folder to approve one later retry."),
        ),
    ),
    (
        re.compile(r"network|timeout|timed out|connection reset|temporary failure|no route|dns", re.I),
        RecoveryAdvice(
            "network",
            "Retry after connectivity is stable",
            "The transfer ended before the provider returned a complete response.",
            ("Confirm that ordinary web access works and any VPN is connected.", "Use Sync now; TuxInDrive will reuse its existing baseline and transfer only remaining changes."),
        ),
    ),
    (
        re.compile(r"quota|insufficient storage|disk full|no space left", re.I),
        RecoveryAdvice(
            "capacity",
            "Free storage space",
            "The local disk or remote account has insufficient free capacity.",
            ("Free space on the endpoint named in the error.", "Use Verify, then Sync now."),
        ),
    ),
    (
        re.compile(r"permission denied|forbidden|read.only|operation not permitted", re.I),
        RecoveryAdvice(
            "permission",
            "Restore folder access",
            "The current account or local user cannot modify the reported path.",
            ("Check the local file permissions and the provider folder role.", "Reconnect the account if its permissions changed, then retry."),
        ),
    ),
    (
        re.compile(r"conflict|changed on both sides|overlap", re.I),
        RecoveryAdvice(
            "conflict",
            "Resolve the affected file",
            "Both endpoints contain changes that cannot be selected automatically.",
            ("Open Conflicts and choose the authoritative copy or Keep both.", "Run Verify after resolving the file."),
        ),
    ),
)


def advice_for_error(reason: str, excerpt: str = "") -> RecoveryAdvice:
    """Return bounded, provider-independent guidance without network access."""
    text = f"{reason}\n{excerpt}"[:32_000]
    for pattern, advice in _RULES:
        if pattern.search(text):
            return advice
    return RecoveryAdvice(
        "inspect",
        "Inspect the reported source and retry safely",
        "The failure does not match a known automatic recovery category.",
        ("Review the source path and recent error output shown above.", "Use Verify before choosing Sync now; reconnect the account if provider access also fails."),
    )
