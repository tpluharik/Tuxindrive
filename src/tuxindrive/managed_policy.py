"""Root-controlled optional desktop policy with a deliberately small schema."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat

from .bandwidth import effective_rclone_limit, normalize_bandwidth_limit
from .models import AppSettings, Provider


DEFAULT_POLICY_PATH = Path("/etc/tuxindrive/policy.json")
MAX_POLICY_BYTES = 64 * 1024


@dataclass(frozen=True, slots=True)
class ManagedPolicy:
    active: bool = False
    source: str = ""
    allowed_providers: tuple[Provider, ...] = ()
    global_bandwidth_ceiling: str = ""
    minimum_headroom_percent: int = 0
    allow_content_indexing: bool = True
    allow_cloud_to_cloud: bool = True
    allow_audit_export: bool = True

    def provider_allowed(self, provider: Provider) -> bool:
        return not self.allowed_providers or provider in self.allowed_providers

    def apply(self, settings: AppSettings) -> None:
        if not self.active:
            return
        if self.global_bandwidth_ceiling:
            settings.global_bandwidth_limit = effective_rclone_limit(
                self.global_bandwidth_ceiling, settings.global_bandwidth_limit
            )
            settings.automatic_bandwidth_control = True
        settings.bandwidth_headroom_percent = max(
            settings.bandwidth_headroom_percent, self.minimum_headroom_percent
        )
        if not self.allow_content_indexing:
            settings.search_content_indexing = False

    @property
    def summary(self) -> str:
        if not self.active:
            return "No managed desktop policy is active."
        providers = ", ".join(item.label for item in self.allowed_providers) or "all providers"
        ceiling = self.global_bandwidth_ceiling or "user setting"
        return (
            f"Managed policy: providers={providers}; bandwidth ceiling={ceiling}; "
            f"minimum headroom={self.minimum_headroom_percent}%; "
            f"content indexing={'allowed' if self.allow_content_indexing else 'blocked'}; "
            f"cloud copy={'allowed' if self.allow_cloud_to_cloud else 'blocked'}; "
            f"audit export={'allowed' if self.allow_audit_export else 'blocked'}."
        )


def load_managed_policy(path: Path = DEFAULT_POLICY_PATH, *, require_root: bool = True) -> ManagedPolicy:
    path = Path(path)
    if not path.exists():
        return ManagedPolicy()
    if path.is_symlink():
        raise RuntimeError("Managed policy must not be a symbolic link")
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_POLICY_BYTES:
        raise RuntimeError("Managed policy must be a small regular file")
    if require_root and os.name != "nt":
        if details.st_uid != 0 or details.st_mode & 0o022:
            raise RuntimeError("Managed policy must be root-owned and not group/world writable")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Managed policy is not valid JSON") from exc
    if not isinstance(value, dict) or value.get("schema", 1) != 1:
        raise RuntimeError("Unsupported managed policy schema")
    raw_providers = value.get("allowed_providers", [])
    if not isinstance(raw_providers, list):
        raise RuntimeError("allowed_providers must be a list")
    try:
        providers = tuple(dict.fromkeys(Provider(str(item)) for item in raw_providers))
    except ValueError as exc:
        raise RuntimeError("Managed policy contains an unknown provider") from exc
    try:
        ceiling = normalize_bandwidth_limit(value.get("global_bandwidth_ceiling", ""))
        headroom = min(80, max(0, int(value.get("minimum_headroom_percent", 0))))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Managed policy contains an invalid bandwidth limit") from exc
    return ManagedPolicy(
        active=True, source=str(path), allowed_providers=providers,
        global_bandwidth_ceiling=ceiling, minimum_headroom_percent=headroom,
        allow_content_indexing=value.get("allow_content_indexing", True) is True,
        allow_cloud_to_cloud=value.get("allow_cloud_to_cloud", True) is True,
        allow_audit_export=value.get("allow_audit_export", True) is True,
    )
