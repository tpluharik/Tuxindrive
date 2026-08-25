from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import time
from typing import Any
from uuid import uuid4


def paths_overlap(first: str | Path, second: str | Path) -> bool:
    left = Path(first).expanduser().resolve(strict=False)
    right = Path(second).expanduser().resolve(strict=False)
    return left == right or left in right.parents or right in left.parents


def safe_streaming_overlap(first: "SyncJob", second: "SyncJob") -> bool:
    if not paths_overlap(first.local, second.local) or first.local == second.local:
        return False
    if first.mode is SyncMode.VIRTUAL_DRIVE and second.mode is not SyncMode.VIRTUAL_DRIVE:
        return second.local in first.local.parents
    if second.mode is SyncMode.VIRTUAL_DRIVE and first.mode is not SyncMode.VIRTUAL_DRIVE:
        return first.local in second.local.parents
    return False


class Provider(str, Enum):
    GOOGLE_DRIVE = "google_drive"
    ONEDRIVE = "onedrive"
    DROPBOX = "dropbox"
    BOX = "box"
    PCLOUD = "pcloud"
    MEGA = "mega"
    PROTON_DRIVE = "proton_drive"
    NEXTCLOUD = "nextcloud"
    S3 = "s3"
    WEBDAV = "webdav"
    SFTP = "sftp"
    GITHUB = "github"
    PEER = "peer"
    VAULT = "vault"

    @property
    def label(self) -> str:
        return {
            self.GOOGLE_DRIVE: "Google Drive",
            self.ONEDRIVE: "Microsoft OneDrive",
            self.DROPBOX: "Dropbox",
            self.BOX: "Box",
            self.PCLOUD: "pCloud",
            self.MEGA: "MEGA",
            self.PROTON_DRIVE: "Proton Drive",
            self.NEXTCLOUD: "Nextcloud",
            self.S3: "S3-compatible storage",
            self.WEBDAV: "WebDAV",
            self.SFTP: "SFTP server",
            self.GITHUB: "GitHub",
            self.PEER: "Peer-to-peer",
            self.VAULT: "Encrypted vault",
        }[self]

    @property
    def rclone_type(self) -> str:
        return {
            self.GOOGLE_DRIVE: "drive",
            self.ONEDRIVE: "onedrive",
            self.DROPBOX: "dropbox",
            self.BOX: "box",
            self.PCLOUD: "pcloud",
            self.MEGA: "mega",
            self.PROTON_DRIVE: "protondrive",
            self.NEXTCLOUD: "webdav",
            self.S3: "s3",
            self.WEBDAV: "webdav",
            self.SFTP: "sftp",
            self.GITHUB: "git",
            self.PEER: "sftp",
            self.VAULT: "crypt",
        }[self]

    @property
    def icon_name(self) -> str:
        if self is self.PEER:
            return "network-workgroup-symbolic"
        if self is self.VAULT:
            return "changes-prevent-symbolic"
        if self is self.GITHUB:
            return "tuxindrive-github"
        if self is self.S3:
            return "drive-harddisk-symbolic"
        if self in {self.WEBDAV, self.SFTP}:
            return "network-server-symbolic"
        return f"tuxindrive-{self.value.replace('_', '-')}"

    @property
    def key_prefix(self) -> str:
        return {
            self.GOOGLE_DRIVE: "google",
            self.ONEDRIVE: "onedrive",
            self.DROPBOX: "dropbox",
            self.BOX: "box",
            self.PCLOUD: "pcloud",
            self.MEGA: "mega",
            self.PROTON_DRIVE: "proton",
            self.NEXTCLOUD: "nextcloud",
            self.S3: "s3",
            self.WEBDAV: "webdav",
            self.SFTP: "sftp",
            self.GITHUB: "github",
            self.PEER: "peer",
            self.VAULT: "vault",
        }[self]

    @property
    def browser_oauth(self) -> bool:
        return self in {
            self.GOOGLE_DRIVE, self.ONEDRIVE, self.DROPBOX, self.BOX, self.PCLOUD,
        }

    @property
    def initial_options(self) -> tuple[str, ...]:
        if self is self.NEXTCLOUD:
            return ("vendor", "nextcloud")
        if self is self.WEBDAV:
            return ("vendor", "other")
        return ()

    @property
    def credential_defaults(self) -> dict[str, str]:
        return {
            self.S3: {"provider": "AWS", "region": "us-east-1"},
            self.SFTP: {"port": "22"},
        }.get(self, {})

    @property
    def credential_fields(self) -> tuple[tuple[str, str, bool, bool], ...]:
        """(config key, UI label, secret, required) for non-OAuth providers."""
        return {
            self.MEGA: (
                ("user", "MEGA email", False, True),
                ("pass", "MEGA password", True, True),
            ),
            self.NEXTCLOUD: (
                ("url", "Nextcloud WebDAV URL", False, True),
                ("user", "Nextcloud username", False, True),
                ("pass", "Nextcloud app password", True, True),
            ),
            self.S3: (
                ("provider", "S3 provider (AWS, Minio, Ceph, …)", False, True),
                ("access_key_id", "Access key ID", False, True),
                ("secret_access_key", "Secret access key", True, True),
                ("endpoint", "Custom endpoint URL (optional for AWS)", False, False),
                ("region", "Region", False, False),
            ),
            self.WEBDAV: (
                ("url", "WebDAV URL", False, True),
                ("user", "Username", False, False),
                ("pass", "Password / app password", True, False),
            ),
            self.SFTP: (
                ("host", "Server host", False, True),
                ("user", "Username", False, True),
                ("port", "Port", False, False),
                ("pass", "Password (optional when using an SSH agent)", True, False),
            ),
        }.get(self, ())

    @property
    def home_url(self) -> str:
        return {
            self.GOOGLE_DRIVE: "https://drive.google.com/drive/my-drive",
            self.ONEDRIVE: "https://onedrive.live.com/",
            self.DROPBOX: "https://www.dropbox.com/home",
            self.BOX: "https://app.box.com/folder/0",
            self.PCLOUD: "https://my.pcloud.com/",
            self.MEGA: "https://mega.nz/fm",
            self.PROTON_DRIVE: "https://drive.proton.me/",
            self.NEXTCLOUD: "",
            self.S3: "",
            self.WEBDAV: "",
            self.SFTP: "",
            self.GITHUB: "https://github.com/",
            self.PEER: "",
            self.VAULT: "",
        }[self]


class SyncMode(str, Enum):
    TWO_WAY = "two_way"
    DOWNLOAD_ONLY = "download_only"
    UPLOAD_ONLY = "upload_only"
    VIRTUAL_DRIVE = "virtual_drive"

    @property
    def label(self) -> str:
        return {
            self.TWO_WAY: "Two-way sync",
            self.DOWNLOAD_ONLY: "Download mirror",
            self.UPLOAD_ONLY: "Upload mirror",
            self.VIRTUAL_DRIVE: "Streaming drive (files on demand)",
        }[self]


class ConflictPolicy(str, Enum):
    KEEP_BOTH = "keep_both"
    NEWER_WINS = "newer_wins"
    LOCAL_WINS = "local_wins"
    CLOUD_WINS = "cloud_wins"


class PeerRole(str, Enum):
    READ_WRITE = "read_write"
    READ_ONLY = "read_only"
    SEND_ONLY = "send_only"
    RECEIVE_ONLY = "receive_only"

    @property
    def label(self) -> str:
        return {
            self.READ_WRITE: "Read and write",
            self.READ_ONLY: "Read-only",
            self.SEND_ONLY: "Send-only",
            self.RECEIVE_ONLY: "Receive-only",
        }[self]

    @property
    def sync_mode(self) -> SyncMode:
        return {
            self.READ_WRITE: SyncMode.TWO_WAY,
            self.READ_ONLY: SyncMode.DOWNLOAD_ONLY,
            self.SEND_ONLY: SyncMode.UPLOAD_ONLY,
            self.RECEIVE_ONLY: SyncMode.DOWNLOAD_ONLY,
        }[self]


class PeerTransportPolicy(str, Enum):
    DIRECT_ONLY = "direct_only"
    TOR_ONLY = "tor_only"
    AUTO = "auto"

@dataclass(slots=True)
class Account:
    remote: str
    provider: Provider
    display_name: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    peer_host: str = ""
    peer_port: int = 2022
    peer_host_key: str = ""
    vault_base_remote: str = ""
    vault_base_path: str = ""
    repository_url: str = ""
    repository_branch: str = "main"
    git_author_name: str = ""
    git_author_email: str = ""
    backend: str = "rclone"

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Account":
        provider = Provider(value["provider"])
        backend = value.get("backend", "rclone")
        if provider is not Provider.PROTON_DRIVE or backend != "proton_cli":
            backend = "rclone"
        return cls(
            remote=value["remote"],
            provider=provider,
            display_name=value.get("display_name", value["remote"]),
            created_at=value.get("created_at", datetime.now(timezone.utc).isoformat()),
            peer_host=value.get("peer_host", ""),
            peer_port=int(value.get("peer_port", 2022)),
            peer_host_key=value.get("peer_host_key", ""),
            vault_base_remote=value.get("vault_base_remote", ""),
            vault_base_path=value.get("vault_base_path", ""),
            repository_url=value.get("repository_url", ""),
            repository_branch=value.get("repository_branch", "main"),
            git_author_name=value.get("git_author_name", ""),
            git_author_email=value.get("git_author_email", ""),
            backend=backend,
        )


@dataclass(slots=True)
class FolderGroup:
    name: str
    id: str = field(default_factory=lambda: uuid4().hex)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    collapsed: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FolderGroup":
        allowed = set(cls.__dataclass_fields__)
        data = {key: item for key, item in value.items() if key in allowed}
        data["collapsed"] = value.get("collapsed") is True
        return cls(**data)


@dataclass(slots=True)
class AuthorizedPeer:
    name: str
    public_key: str
    enabled: bool = True
    role: PeerRole = PeerRole.READ_WRITE
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    onion_client_public_key: str = ""
    server_port: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AuthorizedPeer":
        value = dict(value)
        value["role"] = PeerRole(value.get("role", PeerRole.READ_WRITE.value))
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})


@dataclass(slots=True)
class OneTimeDrop:
    name: str
    public_key: str
    inbox_path: str
    expires_at: str
    id: str = field(default_factory=lambda: uuid4().hex)
    consumed: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    server_port: int = 0

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OneTimeDrop":
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in value.items() if key in allowed})

    @property
    def active(self) -> bool:
        try:
            return not self.consumed and datetime.fromisoformat(self.expires_at) > datetime.now(timezone.utc)
        except (TypeError, ValueError):
            return False


@dataclass(slots=True)
class PeerShare:
    name: str
    local_path: str
    advertised_host: str
    port: int = 2022
    allowed_peer_key: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    enabled: bool = True
    last_status: str = "Not started"
    authorized_peers: list[AuthorizedPeer] = field(default_factory=list)
    lan_discovery: bool = True
    lease_minutes: int = 10
    nat_traversal: bool = False
    relay_host: str = ""
    relay_user: str = ""
    relay_ssh_port: int = 22
    relay_public_port: int = 0
    one_time_drops: list[OneTimeDrop] = field(default_factory=list)
    transport_policy: PeerTransportPolicy = PeerTransportPolicy.AUTO
    no_relay: bool = False
    no_public_ip_discovery: bool = False
    never_use_provider_cloud: bool = True
    onion_enabled: bool = False
    onion_persistent: bool = True
    onion_address: str = ""
    onion_client_auth: bool = False
    tor_bridge_lines: list[str] = field(default_factory=list)
    tor_pluggable_transports: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PeerShare":
        data = dict(value)
        peers = [AuthorizedPeer.from_dict(item) for item in data.get("authorized_peers", [])]
        legacy = data.get("allowed_peer_key", "")
        if legacy and not peers:
            peers = [AuthorizedPeer("Legacy peer", legacy)]
        data["authorized_peers"] = peers
        data["one_time_drops"] = [OneTimeDrop.from_dict(item) for item in data.get("one_time_drops", [])]
        data["transport_policy"] = PeerTransportPolicy(data.get("transport_policy", PeerTransportPolicy.AUTO.value))
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})

    @property
    def active_peer_keys(self) -> list[str]:
        keys = [item.public_key for item in self.authorized_peers if item.enabled]
        if self.allowed_peer_key and self.allowed_peer_key not in keys:
            keys.append(self.allowed_peer_key)
        keys.extend(item.public_key for item in self.one_time_drops if item.active)
        return keys


@dataclass(slots=True)
class SyncJob:
    account_remote: str
    local_path: str
    remote_path: str = ""
    remote_scope: str = ""
    cloud_location_name: str = ""
    mode: SyncMode = SyncMode.TWO_WAY
    name: str = "Cloud files"
    enabled: bool = True
    interval_minutes: int = 5
    conflict_policy: ConflictPolicy = ConflictPolicy.KEEP_BOTH
    exclude_patterns: list[str] = field(default_factory=lambda: [".Trash-*/**", "*.part", "~$*"])
    selective_extensions: list[str] = field(default_factory=list)
    selective_max_size_mb: int = 0
    selective_max_age_days: int = 0
    max_delete: int = 100
    bandwidth_limit: str = ""
    acknowledge_google_abuse: bool = False
    realtime_sync: bool = True
    version_history: bool = True
    version_retention_days: int = 30
    ransomware_protection: bool = True
    mass_change_limit: int = 500
    mass_change_percent: int = 80
    peer_leases: bool = False
    peer_lease_minutes: int = 10
    block_delta_transfer: bool = True
    peer_delta: bool = False
    peer_role: PeerRole = PeerRole.READ_WRITE
    one_time_drop_id: str = ""
    offline_paths: list[str] = field(default_factory=list)
    online_only_paths: list[str] = field(default_factory=list)
    group_id: str = ""
    repository_url: str = ""
    repository_branch: str = "main"
    git_author_name: str = ""
    git_author_email: str = ""
    id: str = field(default_factory=lambda: uuid4().hex)
    initialized: bool = False
    last_run: str | None = None
    last_status: str = "Not synchronized yet"
    last_error: str = ""
    last_error_at: str = ""
    last_error_source: str = ""
    last_error_log: str = ""

    @property
    def remote_spec(self) -> str:
        remote_path = self.remote_path.strip("/")
        remote = self.remote_scope or self.account_remote
        return f"{remote}:{remote_path}" if remote_path else f"{remote}:"

    @property
    def local(self) -> Path:
        return Path(self.local_path).expanduser()

    @property
    def is_git(self) -> bool:
        return bool(self.repository_url)

    def selective_args(self) -> list[str]:
        """Return deterministic rclone selection flags without shell parsing."""
        args: list[str] = []
        extensions = []
        for raw in self.selective_extensions:
            value = raw.strip().lower().lstrip("*.")
            if value and value.replace("-", "").replace("_", "").isalnum():
                extensions.append(value)
        for value in dict.fromkeys(extensions):
            args.extend(["--include", f"*.{value}"])
        if self.selective_max_size_mb > 0:
            args.extend(["--max-size", f"{self.selective_max_size_mb}M"])
        if self.selective_max_age_days > 0:
            args.extend(["--max-age", f"{self.selective_max_age_days}d"])
        return args

    def selected_by_rules(
        self,
        relative_path: str,
        *,
        size: int | None = None,
        modified_timestamp: float | None = None,
    ) -> bool:
        extensions = set()
        for raw in self.selective_extensions:
            value = raw.strip().lower().lstrip("*.")
            if value and value.replace("-", "").replace("_", "").isalnum():
                extensions.add(value)
        if extensions and Path(relative_path).suffix.lower().lstrip(".") not in extensions:
            return False
        if size is not None and self.selective_max_size_mb > 0:
            if size > self.selective_max_size_mb * 1024 * 1024:
                return False
        if modified_timestamp is not None and self.selective_max_age_days > 0:
            cutoff = time.time() - self.selective_max_age_days * 86400
            if modified_timestamp < cutoff:
                return False
        return True

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SyncJob":
        data = dict(value)
        # Migrate the former highly sensitive defaults. Explicit non-default
        # operator thresholds remain untouched.
        if data.get("mass_change_limit", 200) == 200:
            data["mass_change_limit"] = 500
        if data.get("mass_change_percent", 25) == 25:
            data["mass_change_percent"] = 80
        data["mode"] = SyncMode(data.get("mode", SyncMode.TWO_WAY.value))
        data["conflict_policy"] = ConflictPolicy(
            data.get("conflict_policy", ConflictPolicy.KEEP_BOTH.value)
        )
        data["peer_role"] = PeerRole(data.get("peer_role", PeerRole.READ_WRITE.value))
        allowed = set(cls.__dataclass_fields__)
        return cls(**{key: item for key, item in data.items() if key in allowed})


@dataclass(slots=True)
class AppSettings:
    launch_at_login: bool = True
    notifications: bool = True
    start_minimized: bool = False
    rclone_path: str = "rclone"
    proton_drive_path: str = "proton-drive"
    nautilus_integration: bool = True
    language: str = "en"
    visual_theme: str = "nordic_glass"
    network_policy: str = "maximum"
    global_bandwidth_limit: str = "10M"
    automatic_bandwidth_control: bool = True
    bandwidth_headroom_percent: int = 20
    allow_metered_networks: bool = True
    pause_below_battery_percent: int = 0
    schedule_start: str = ""
    schedule_end: str = ""
    profile_remote: str = ""
    profile_last_backup: str = ""
    streaming_cache_max_gib: int = 20
    streaming_cache_min_free_gib: int = 5
    streaming_refresh_mode: str = "realtime"
    show_network_usage: bool = True
    show_live_activity_log: bool = True
    server_integration_enabled: bool = False
    server_url: str = "http://127.0.0.1:9443"
    server_ca_file: str = ""
    config_version: int = 1

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppSettings":
        from .bandwidth import normalize_bandwidth_limit
        from .themes import normalize_theme

        allowed = set(cls.__dataclass_fields__)
        data = {key: item for key, item in value.items() if key in allowed}
        data["visual_theme"] = normalize_theme(data.get("visual_theme"))
        try:
            data["global_bandwidth_limit"] = normalize_bandwidth_limit(
                data.get("global_bandwidth_limit", "10M")
            )
        except ValueError:
            data["global_bandwidth_limit"] = "10M"
        data["automatic_bandwidth_control"] = bool(
            data.get("automatic_bandwidth_control", True)
        )
        try:
            data["bandwidth_headroom_percent"] = min(
                80, max(0, int(data.get("bandwidth_headroom_percent", 20)))
            )
        except (TypeError, ValueError):
            data["bandwidth_headroom_percent"] = 20
        for key, default in (
            ("streaming_cache_max_gib", 20),
            ("streaming_cache_min_free_gib", 5),
        ):
            try:
                data[key] = min(1024, max(1, int(data.get(key, default))))
            except (TypeError, ValueError):
                data[key] = default
        if data.get("streaming_refresh_mode") not in {"realtime", "balanced", "low_traffic"}:
            data["streaming_refresh_mode"] = "realtime"
        from .server_client import normalize_server_url
        try:
            data["server_url"] = normalize_server_url(
                data.get("server_url", "http://127.0.0.1:9443")
            )
        except ValueError:
            data["server_url"] = "http://127.0.0.1:9443"
            data["server_integration_enabled"] = False
        return cls(**data)


@dataclass(slots=True)
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    jobs: list[SyncJob] = field(default_factory=list)
    folder_groups: list[FolderGroup] = field(default_factory=list)
    peer_shares: list[PeerShare] = field(default_factory=list)
    settings: AppSettings = field(default_factory=AppSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AppConfig":
        return cls(
            accounts=[Account.from_dict(item) for item in value.get("accounts", [])],
            jobs=[SyncJob.from_dict(item) for item in value.get("jobs", [])],
            folder_groups=[FolderGroup.from_dict(item) for item in value.get("folder_groups", [])],
            peer_shares=[PeerShare.from_dict(item) for item in value.get("peer_shares", [])],
            settings=AppSettings.from_dict(value.get("settings", {})),
        )
