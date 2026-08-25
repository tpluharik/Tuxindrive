"""First self-hosted TuxInDrive server and headless agent.

The server stores only opaque client-encrypted payloads for mailbox, object,
rendezvous and collaboration roles.  Existing synchronization and peer code is
reused by the optional headless agent.  Every network role is independently
enabled and all API requests are bounded and authenticated.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import selectors
import signal
import socket
import ssl
import stat
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .bandwidth import GlobalBandwidthController, normalize_bandwidth_limit
from .config import ConfigStore
from .engine import JobResult, SyncEngine
from .models import AppConfig, SyncMode
from .peer import PeerManager
from .policies import TransferPolicy
from .proton import ProtonDriveClient
from .server_store import ServerStore, ServerStoreError


SERVER_SCHEMA = 1
DEFAULT_ROLES = (
    "agent", "mailbox", "rendezvous", "objects", "collaboration",
    "relay", "attestation", "mcp",
)
MAX_JSON = 16 * 1024 * 1024
MAX_OPAQUE = 12 * 1024 * 1024
MAX_RELAY_BYTES = 1024 * 1024 * 1024
MAX_RELAY_SECONDS = 3600


class ServerError(RuntimeError):
    pass


@dataclass(slots=True)
class ServerConfig:
    schema: int = SERVER_SCHEMA
    bind: str = "127.0.0.1"
    port: int = 9443
    tls_certificate: str = ""
    tls_private_key: str = ""
    database: str = "server.sqlite3"
    client_config: str = ""
    enabled_roles: list[str] = field(default_factory=lambda: list(DEFAULT_ROLES))
    token_hashes: dict[str, str] = field(default_factory=dict)
    quota_mib_per_tenant: int = 512
    default_ttl_seconds: int = 86400
    global_bandwidth_limit: str = "10M"
    automatic_bandwidth_control: bool = True
    bandwidth_headroom_percent: int = 20
    max_concurrent_requests: int = 16
    max_requests_per_source: int = 4
    request_timeout_seconds: int = 30
    max_relay_connections: int = 4
    max_relay_connections_per_tenant: int = 2
    relay_idle_timeout_seconds: int = 30
    relay_targets: list[str] = field(default_factory=list)
    update_manifests: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ServerConfig":
        allowed = set(cls.__dataclass_fields__)
        data = {key: value for key, value in raw.items() if key in allowed}
        result = cls(**data)
        if result.schema != SERVER_SCHEMA:
            raise ServerError("Unsupported TuxInDrive server configuration schema")
        try:
            ipaddress.ip_address(result.bind)
        except ValueError:
            if result.bind != "localhost":
                raise ServerError("Server bind must be a literal IP address or localhost")
        result.port = max(1, min(65535, int(result.port)))
        result.quota_mib_per_tenant = max(16, min(1024 * 1024, int(result.quota_mib_per_tenant)))
        result.default_ttl_seconds = max(60, min(30 * 86400, int(result.default_ttl_seconds)))
        result.global_bandwidth_limit = normalize_bandwidth_limit(result.global_bandwidth_limit)
        result.automatic_bandwidth_control = bool(result.automatic_bandwidth_control)
        result.bandwidth_headroom_percent = min(
            80, max(0, int(result.bandwidth_headroom_percent))
        )
        result.max_concurrent_requests = max(4, min(256, int(result.max_concurrent_requests)))
        result.max_requests_per_source = max(
            1,
            min(result.max_concurrent_requests, int(result.max_requests_per_source)),
        )
        result.request_timeout_seconds = max(5, min(300, int(result.request_timeout_seconds)))
        result.max_relay_connections = max(1, min(64, int(result.max_relay_connections)))
        result.max_relay_connections_per_tenant = max(
            1,
            min(result.max_relay_connections, int(result.max_relay_connections_per_tenant)),
        )
        result.relay_idle_timeout_seconds = max(5, min(300, int(result.relay_idle_timeout_seconds)))
        unknown = set(result.enabled_roles) - set(DEFAULT_ROLES)
        if unknown:
            raise ServerError("Unknown server role(s): " + ", ".join(sorted(unknown)))
        if not isinstance(result.token_hashes, dict) or not result.token_hashes:
            raise ServerError("At least one hashed API token is required")
        for digest, tenant in result.token_hashes.items():
            if (
                len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or not tenant
                or len(tenant) > 128
                or any(not (char.isalnum() or char in "-_.:@") for char in tenant)
            ):
                raise ServerError("Invalid API token mapping")
        if bool(result.tls_certificate) != bool(result.tls_private_key):
            raise ServerError("Both TLS certificate and private key are required together")
        _validate_regular_file(result.tls_certificate, "TLS certificate")
        _validate_regular_file(result.tls_private_key, "TLS private key", private=True)
        _validate_regular_file(result.client_config, "Headless client configuration", private=True)
        _validate_regular_file(result.database, "Server database", allow_missing=True, private=True)
        loopback = result.bind == "localhost"
        if not loopback:
            loopback = ipaddress.ip_address(result.bind).is_loopback
        if not loopback and not (result.tls_certificate and result.tls_private_key):
            raise ServerError("A remotely reachable server requires TLS certificate and private key")
        return result


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _validate_regular_file(
    value: str,
    label: str,
    *,
    allow_missing: bool = False,
    private: bool = False,
) -> None:
    if not value:
        return
    path = Path(value).expanduser()
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            parent = path.parent
            try:
                parent_metadata = parent.lstat()
            except FileNotFoundError as exc:
                raise ServerError(f"{label} parent does not exist: {parent}") from exc
            if not stat.S_ISDIR(parent_metadata.st_mode) or stat.S_ISLNK(parent_metadata.st_mode):
                raise ServerError(f"{label} parent must be a real directory")
            return
        raise ServerError(f"{label} does not exist: {path}")
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ServerError(f"{label} must be a regular non-symlink file")
    allowed_owners = {0, os.geteuid()}
    if os.name == "posix":
        try:
            import pwd
            allowed_owners.add(pwd.getpwnam("tuxindrive-server").pw_uid)
        except (ImportError, KeyError):
            pass
    if metadata.st_uid not in allowed_owners:
        raise ServerError(f"{label} has an unexpected owner")
    if metadata.st_mode & 0o022:
        raise ServerError(f"{label} must not be writable by group or other users")
    if private and metadata.st_mode & 0o007:
        raise ServerError(f"{label} must not be accessible to other users")


def _private_write(
    path: Path,
    data: str,
    *,
    mode: int = 0o600,
    uid: int | None = None,
    gid: int | None = None,
    require_root_parent: bool = False,
) -> None:
    """Atomically replace a private file without following a temporary symlink."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent_metadata = path.parent.lstat()
    if stat.S_ISLNK(parent_metadata.st_mode) or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ServerError("Private file parent must be a real directory")
    if require_root_parent and (
        parent_metadata.st_uid != 0 or parent_metadata.st_mode & 0o022
    ):
        raise ServerError("Server configuration directory must be root-owned and non-writable by the service")

    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(path.parent, directory_flags)
    temporary = f".{path.name}.{secrets.token_hex(16)}.tmp"
    descriptor = -1
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, mode, dir_fd=directory)
        os.fchmod(descriptor, mode)
        if uid is not None or gid is not None:
            os.fchown(descriptor, -1 if uid is None else uid, -1 if gid is None else gid)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def initialize(config_path: Path, state_path: Path, token_file: Path | None = None) -> str:
    if config_path.exists():
        raise ServerError(f"Configuration already exists: {config_path}")
    state_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state_path, 0o700)
    token = secrets.token_urlsafe(48)
    config = ServerConfig(database=str(state_path / "server.sqlite3"), token_hashes={hash_token(token): "owner"})
    _private_write(config_path, json.dumps(asdict(config), indent=2) + "\n")
    if token_file:
        _private_write(token_file, token + "\n")
    return token


def load_config(path: Path) -> ServerConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServerError(f"Could not read server configuration: {exc}") from exc
    if not isinstance(raw, dict):
        raise ServerError("Server configuration must be a JSON object")
    return ServerConfig.from_dict(raw)


class HeadlessAgent:
    """Reuse the production sync/peer engines without importing GTK."""

    def __init__(
        self,
        client_config: str,
        bandwidth_limit: str,
        bandwidth: GlobalBandwidthController | None = None,
    ) -> None:
        self.store = ConfigStore(Path(client_config).expanduser()) if client_config else ConfigStore()
        try:
            self.config = self.store.load()
        except RuntimeError:
            self.config = AppConfig()
        self.bandwidth = bandwidth or GlobalBandwidthController(bandwidth_limit)
        self.proton = ProtonDriveClient(self.config.settings.proton_drive_path)
        self.engine = SyncEngine(self.config.settings.rclone_path, proton=self.proton, bandwidth=self.bandwidth)
        self.peers = PeerManager(self.config.settings.rclone_path)
        self._lock = threading.RLock()
        self._last_started: dict[str, float] = {}
        self._results: dict[str, dict] = {}
        self._stop = threading.Event()

    def start(self) -> None:
        self.engine.configure_jobs(self.config.jobs, self.config.accounts)
        for share in self.config.peer_shares:
            if share.enabled:
                try: self.peers.start(share)
                except Exception as exc: self._results[f"peer:{share.id}"] = {"success": False, "message": str(exc)}
        threading.Thread(target=self._scheduler, name="tuxindrive-server-scheduler", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        for job_id in list(self.engine.running_jobs): self.engine.cancel(job_id)
        for share in self.config.peer_shares:
            try: self.peers.stop(share.id)
            except Exception: pass

    def _scheduler(self) -> None:
        while not self._stop.wait(30):
            now = time.time()
            for job in self.config.jobs:
                if not job.enabled or job.mode is SyncMode.VIRTUAL_DRIVE:
                    continue
                if now - self._last_started.get(job.id, 0) >= max(1, job.interval_minutes) * 60:
                    self.run(job.id)

    def _finished(self, result: JobResult) -> None:
        with self._lock:
            job = next((item for item in self.config.jobs if item.id == result.job_id), None)
            if job:
                finished_at = datetime.now(timezone.utc).isoformat()
                job.last_run = finished_at
                job.last_status = result.message
                job.last_error = "" if result.success else result.message
                job.last_error_at = "" if result.success else finished_at
                job.last_error_source = "" if result.success else result.blocked_path
                job.last_error_log = "" if result.success else str(result.log_path)
                self.store.save(self.config)
            self._results[result.job_id] = {
                "success": result.success, "message": result.message,
                "cancelled": result.cancelled, "finished": int(time.time()),
            }

    def run(self, job_id: str, dry_run: bool = False) -> bool:
        with self._lock:
            job = next((item for item in self.config.jobs if item.id == job_id), None)
            if not job: raise ServerError("Unknown synchronization job")
            decision = TransferPolicy(self.config.settings).evaluate()
            if not decision.allowed: raise ServerError(decision.reason)
            self.engine.configure_jobs(self.config.jobs, self.config.accounts)
            started = self.engine.run_async(job, self._finished, dry_run=dry_run)
            if started: self._last_started[job.id] = time.time()
            return started

    def cancel(self, job_id: str) -> bool:
        return self.engine.cancel(job_id)

    def jobs(self) -> list[dict]:
        running = self.engine.running_jobs
        return [{
            "id": job.id, "name": job.name, "mode": job.mode.value,
            "enabled": job.enabled, "running": job.id in running,
            "last_run": job.last_run, "status": job.last_status,
            "result": self._results.get(job.id),
        } for job in self.config.jobs]


class RateLimiter:
    def __init__(self, maximum: int = 240, window: int = 60, maximum_sources: int = 4096) -> None:
        self.maximum = maximum; self.window = window; self.maximum_sources = maximum_sources
        self._lock = threading.Lock(); self._hits: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if key not in self._hits and len(self._hits) >= self.maximum_sources:
                self._hits = {
                    source: hits for source, hits in self._hits.items()
                    if hits and now - hits[-1] < self.window
                }
                if len(self._hits) >= self.maximum_sources:
                    return False
            values = [item for item in self._hits.get(key, []) if now - item < self.window]
            if len(values) >= self.maximum:
                self._hits[key] = values; return False
            values.append(now); self._hits[key] = values; return True


class TuxInDriveServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.store = ServerStore(Path(config.database).expanduser(), config.quota_mib_per_tenant * 1024 * 1024)
        self.bandwidth = GlobalBandwidthController(
            config.global_bandwidth_limit,
            automatic=config.automatic_bandwidth_control,
            headroom_percent=config.bandwidth_headroom_percent,
        )
        # Relay and agent traffic must share one clock; independent controllers
        # would each permit the complete configured ceiling.
        self.agent = (
            HeadlessAgent(
                config.client_config,
                config.global_bandwidth_limit,
                bandwidth=self.bandwidth,
            )
            if "agent" in config.enabled_roles
            else None
        )
        self.limiter = RateLimiter()
        self._request_slots = threading.BoundedSemaphore(config.max_concurrent_requests)
        self._request_lock = threading.Lock()
        self._requests_by_source: dict[str, int] = {}
        self._relay_slots = threading.BoundedSemaphore(config.max_relay_connections)
        self._relay_lock = threading.Lock()
        self._relays_by_tenant: dict[str, int] = {}
        self.address_family = socket.AF_INET6 if ":" in config.bind else socket.AF_INET
        super().__init__((config.bind, config.port), RequestHandler)
        if config.tls_certificate:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(config.tls_certificate, config.tls_private_key)
            self.socket = context.wrap_socket(self.socket, server_side=True)

    def get_request(self):
        request, address = super().get_request()
        request.settimeout(self.config.request_timeout_seconds)
        return request, address

    def process_request(self, request, client_address) -> None:
        source = str(client_address[0])
        if not self._request_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        with self._request_lock:
            active = self._requests_by_source.get(source, 0)
            if active >= self.config.max_requests_per_source:
                self._request_slots.release()
                self.shutdown_request(request)
                return
            self._requests_by_source[source] = active + 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_request(source)
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._release_request(str(client_address[0]))

    def _release_request(self, source: str) -> None:
        with self._request_lock:
            active = self._requests_by_source.get(source, 0)
            if active <= 1:
                self._requests_by_source.pop(source, None)
            else:
                self._requests_by_source[source] = active - 1
        self._request_slots.release()

    def reserve_relay(self, tenant: str) -> bool:
        if not self._relay_slots.acquire(blocking=False):
            return False
        with self._relay_lock:
            active = self._relays_by_tenant.get(tenant, 0)
            if active >= self.config.max_relay_connections_per_tenant:
                self._relay_slots.release()
                return False
            self._relays_by_tenant[tenant] = active + 1
        return True

    def release_relay(self, tenant: str) -> None:
        with self._relay_lock:
            active = self._relays_by_tenant.get(tenant, 0)
            if active <= 1:
                self._relays_by_tenant.pop(tenant, None)
            else:
                self._relays_by_tenant[tenant] = active - 1
        self._relay_slots.release()

    def start_roles(self) -> None:
        if self.agent: self.agent.start()

    def server_close(self) -> None:
        if self.agent: self.agent.stop()
        self.store.close()
        super().server_close()


class RequestHandler(BaseHTTPRequestHandler):
    server: TuxInDriveServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        # BaseHTTPRequestHandler includes the full request target, which may
        # contain private routing identifiers. Structured, redacted events are
        # available through the tenant-scoped audit endpoint instead.
        return

    def _headers(self, status: int, content_type: str, length: int) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def _json(self, value: dict | list, status: int = 200) -> None:
        data = (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
        self._headers(status, "application/json", len(data)); self.wfile.write(data)

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _tenant(self) -> str | None:
        if not self.server.limiter.allow(self.client_address[0]):
            self._error(429, "Request rate limit exceeded"); return None
        value = self.headers.get("Authorization", "")
        if not value.startswith("Bearer ") or len(value) > 8192:
            self._error(401, "Bearer token required"); return None
        digest = hash_token(value[7:])
        for expected, tenant in self.server.config.token_hashes.items():
            if hmac.compare_digest(digest, expected): return tenant
        self._error(403, "Invalid server token"); return None

    def _role(self, role: str) -> bool:
        return role in self.server.config.enabled_roles

    @staticmethod
    def _admin(tenant: str) -> bool:
        # The bootstrap token is deliberately the only administrative token.
        # Additional token mappings are tenant-scoped storage/coordination
        # identities and cannot start local synchronization jobs.
        return tenant == "owner"

    def _body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise ServerError("Transfer-Encoding is not supported")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise ServerError("Content-Length is required")
        try: length = int(raw_length)
        except ValueError: raise ServerError("Invalid Content-Length")
        if length < 0 or length > MAX_JSON: raise ServerError("Request body is too large")
        raw = self.rfile.read(length)
        if len(raw) != length: raise ServerError("Request body ended before Content-Length")
        try: value = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ServerError("Request body is invalid JSON") from exc
        if not isinstance(value, dict): raise ServerError("Request body must be a JSON object")
        return value

    @staticmethod
    def _opaque(value: Any) -> bytes:
        if not isinstance(value, str) or len(value) > (MAX_OPAQUE * 4 // 3 + 8): raise ServerError("Opaque payload is invalid")
        try: data = base64.b64decode(value, validate=True)
        except ValueError as exc: raise ServerError("Opaque payload is not valid base64") from exc
        if not data or len(data) > MAX_OPAQUE: raise ServerError("Opaque payload size is invalid")
        return data

    def _route(self):
        parsed = urlsplit(self.path)
        return parsed.path.rstrip("/") or "/", parse_qs(parsed.query, keep_blank_values=False)

    def do_GET(self) -> None:
        path, query = self._route()
        if path == "/healthz":
            self._json({"status": "ok"}); return
        tenant = self._tenant()
        if tenant is None: return
        try:
            if path == "/v1/health":
                self._json({"status": "ok", "version": __version__, "schema": SERVER_SCHEMA, "roles": self.server.config.enabled_roles}); return
            if path == "/v1/capabilities":
                self._json({"roles": self.server.config.enabled_roles, "opaque_storage": True, "remote_tls_required": True, "mcp_mutations": False, "max_payload_bytes": MAX_OPAQUE}); return
            if path == "/v1/jobs" and self._role("agent") and self._admin(tenant):
                self._json({"jobs": self.server.agent.jobs() if self.server.agent else []}); return
            if path == "/v1/audit":
                self._json({"events": self.server.store.recent_audit(tenant, int(query.get("limit", ["100"])[0]))}); return
            if path == "/v1/stats":
                self._json({"storage": self.server.store.stats(tenant)}); return
            if path == "/v1/mailbox" and self._role("mailbox"):
                recipient = query.get("recipient", [""])[0]
                items = self.server.store.list_mail(tenant, recipient, int(query.get("limit", ["100"])[0]))
                for item in items: item["body"] = base64.b64encode(item["body"]).decode("ascii")
                self._json({"messages": items}); return
            if path.startswith("/v1/objects/") and self._role("objects"):
                data = self.server.store.get_object(tenant, path.rsplit("/", 1)[-1])
                if data is None: self._error(404, "Object not found")
                else: self._json({"body": base64.b64encode(data).decode("ascii"), "bytes": len(data)})
                return
            if path.startswith("/v1/rendezvous/") and self._role("rendezvous"):
                data = self.server.store.get_rendezvous(tenant, path.rsplit("/", 1)[-1])
                if data is None: self._error(404, "Rendezvous envelope not found")
                else: self._json({"envelope": base64.b64encode(data).decode("ascii")})
                return
            if path == "/v1/collaboration" and self._role("collaboration"):
                items = self.server.store.list_collaboration(tenant, query.get("workspace", [""])[0], int(query.get("after", ["0"])[0]), int(query.get("limit", ["100"])[0]))
                for item in items: item["body"] = base64.b64encode(item["body"]).decode("ascii")
                self._json({"operations": items}); return
            if path == "/v1/attestation" and self._role("attestation"):
                manifests=[]
                for name in self.server.config.update_manifests:
                    candidate=Path(name).expanduser()
                    if candidate.is_file() and candidate.stat().st_size <= 128*1024:
                        manifests.append(json.loads(candidate.read_text(encoding="utf-8")))
                self._json({"server_version": __version__, "manifests": manifests}); return
            self._error(404, "Endpoint not found")
        except (ServerError, ServerStoreError, ValueError, OSError, json.JSONDecodeError) as exc:
            self.server.store.audit(tenant, "GET " + path, "rejected", str(exc)); self._error(400, str(exc))

    def do_POST(self) -> None:
        path, _query = self._route(); tenant = self._tenant()
        if tenant is None: return
        try:
            body = self._body()
            if path == "/v1/mailbox" and self._role("mailbox"):
                result = self.server.store.put_mail(tenant, str(body.get("recipient", "")), self._opaque(body.get("body")), int(body.get("ttl", self.server.config.default_ttl_seconds)))
            elif path == "/v1/objects" and self._role("objects"):
                result = self.server.store.put_object(tenant, self._opaque(body.get("body")), int(body.get("ttl", self.server.config.default_ttl_seconds)))
            elif path == "/v1/rendezvous" and self._role("rendezvous"):
                result = self.server.store.put_rendezvous(tenant, str(body.get("device", "")), self._opaque(body.get("envelope")), int(body.get("ttl", 3600)))
            elif path == "/v1/collaboration" and self._role("collaboration"):
                result = self.server.store.put_collaboration(tenant, str(body.get("workspace", "")), self._opaque(body.get("body")), int(body.get("ttl", self.server.config.default_ttl_seconds)))
            elif path.startswith("/v1/jobs/") and self._role("agent") and self._admin(tenant):
                parts = path.split("/"); job_id = parts[3] if len(parts) > 3 else ""; action = parts[4] if len(parts) > 4 else ""
                if not self.server.agent: raise ServerError("Headless agent is unavailable")
                if action in {"sync", "dry-run"}: result = {"started": self.server.agent.run(job_id, dry_run=action == "dry-run")}
                elif action == "cancel": result = {"cancelled": self.server.agent.cancel(job_id)}
                else: raise ServerError("Unknown job action")
            elif path == "/v1/mcp" and self._role("mcp"):
                self._mcp(body, tenant); return
            else:
                self._error(404, "Endpoint not found"); return
            self.server.store.audit(tenant, "POST " + path, "success")
            self._json(result, 201)
        except (ServerError, ServerStoreError, ValueError, OSError) as exc:
            self.server.store.audit(tenant, "POST " + path, "rejected", str(exc)); self._error(400, str(exc))

    def do_DELETE(self) -> None:
        path, query = self._route(); tenant = self._tenant()
        if tenant is None: return
        try:
            if path.startswith("/v1/mailbox/") and self._role("mailbox"):
                removed = self.server.store.acknowledge_mail(tenant, query.get("recipient", [""])[0], path.rsplit("/", 1)[-1])
                self.server.store.audit(tenant, "DELETE mailbox", "success" if removed else "missing")
                self._json({"acknowledged": removed}); return
            self._error(404, "Endpoint not found")
        except (ServerError, ServerStoreError, ValueError) as exc: self._error(400, str(exc))

    def do_CONNECT(self) -> None:
        tenant = self._tenant()
        if tenant is None: return
        if not self._role("relay"):
            self._error(404, "Endpoint not found"); return
        if not self.server.reserve_relay(tenant):
            self._error(429, "Relay connection limit exceeded"); return
        target = self.path.strip()
        upstream = None
        try:
            if target not in self.server.config.relay_targets:
                self.server.store.audit(tenant, "CONNECT relay", "rejected", "target not allowlisted")
                self._error(403, "Relay target is not allowlisted"); return
            try:
                host, port_text = target.rsplit(":", 1)
                upstream = socket.create_connection((host, int(port_text)), timeout=10)
            except (OSError, ValueError) as exc:
                self._error(502, f"Relay connection failed: {exc}"); return
            self.send_response(200, "Connection established"); self.send_header("Cache-Control", "no-store"); self.end_headers()
            idle_timeout = self.server.config.relay_idle_timeout_seconds
            self.connection.settimeout(idle_timeout); upstream.settimeout(idle_timeout)
            selector = selectors.DefaultSelector(); selector.register(self.connection, selectors.EVENT_READ, upstream); selector.register(upstream, selectors.EVENT_READ, self.connection)
            deadline = time.monotonic() + MAX_RELAY_SECONDS; last_activity = time.monotonic(); transferred = 0
            try:
                while time.monotonic() < deadline and transferred < MAX_RELAY_BYTES:
                    events = selector.select(min(5, idle_timeout))
                    if not events:
                        if time.monotonic() - last_activity >= idle_timeout: return
                        continue
                    for key, _mask in events:
                        chunk = key.fileobj.recv(65536)
                        if not chunk: return
                        if key.fileobj is self.connection:
                            self.server.bandwidth.throttle_upload(len(chunk))
                        else:
                            self.server.bandwidth.throttle_download(len(chunk))
                        key.data.sendall(chunk); transferred += len(chunk); last_activity = time.monotonic()
            finally:
                selector.close()
        finally:
            if upstream is not None:
                upstream.close()
            self.server.release_relay(tenant)
            self.server.store.audit(tenant, "CONNECT relay", "closed")

    def _mcp(self, request: dict, tenant: str) -> None:
        request_id = request.get("id")
        method = request.get("method")
        if method == "initialize":
            result = {"protocolVersion": "2025-11-25", "serverInfo": {"name": "tuxindrive-server", "version": __version__}, "capabilities": {"tools": {}}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": "health", "description": "Return redacted server health", "inputSchema": {"type": "object", "additionalProperties": False}},
                {"name": "list_jobs", "description": "List redacted configured jobs", "inputSchema": {"type": "object", "additionalProperties": False}},
                {"name": "recent_audit", "description": "Return bounded redacted audit events", "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
            ]}
        elif method == "tools/call":
            params = request.get("params") if isinstance(request.get("params"), dict) else {}; name = params.get("name"); args = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            if name == "health": value = {"status": "ok", "roles": self.server.config.enabled_roles}
            elif name == "list_jobs" and self._admin(tenant): value = {"jobs": self.server.agent.jobs() if self.server.agent else []}
            elif name == "recent_audit": value = {"events": self.server.store.recent_audit(tenant, int(args.get("limit", 25)))}
            else:
                self._json({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32602, "message": "Unknown or disabled read-only tool"}}); return
            result = {"content": [{"type": "text", "text": json.dumps(value, separators=(",", ":"))}]}
        else:
            self._json({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}); return
        self._json({"jsonrpc": "2.0", "id": request_id, "result": result})


def serve(config_path: Path) -> None:
    config = load_config(config_path)
    server = TuxInDriveServer(config); server.start_roles()
    stopping = threading.Event()
    def stop(_signum=None, _frame=None):
        if not stopping.is_set(): stopping.set(); threading.Thread(target=server.shutdown, daemon=True).start()
    for name in (signal.SIGINT, signal.SIGTERM): signal.signal(name, stop)
    scheme = "https" if config.tls_certificate else "http"
    print(f"TuxInDrive server {__version__} listening on {scheme}://{config.bind}:{config.port}", flush=True)
    try: server.serve_forever(poll_interval=0.5)
    finally: server.server_close()


def main(argv: list[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv[:1] == ["admin"]:
        from .server_admin import main as admin_main
        return admin_main(effective_argv[1:])
    parser = argparse.ArgumentParser(description="TuxInDrive self-hosted server")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("gui", help="open the graphical server administration application")
    init = sub.add_parser("init", help="create private server configuration and API token")
    init.add_argument("--config", type=Path, required=True); init.add_argument("--state", type=Path, required=True); init.add_argument("--token-file", type=Path)
    run = sub.add_parser("serve", help="run the server"); run.add_argument("--config", type=Path, required=True)
    check = sub.add_parser("check", help="validate configuration"); check.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(effective_argv)
    try:
        if args.command in (None, "gui"):
            from .server_gui import main as gui_main
            return gui_main()
        if args.command == "init":
            token = initialize(args.config, args.state, args.token_file)
            if not args.token_file: print(token)
            return 0
        if args.command == "check": load_config(args.config); print("Configuration is valid"); return 0
        serve(args.config); return 0
    except (ServerError, ServerStoreError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
