from __future__ import annotations

import base64
import os
import re
import shutil
import signal
import subprocess
import time
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from .models import AuthorizedPeer, PeerShare, PeerTransportPolicy
from .process_control import new_process_group, reload_process, terminate_process


ONION_V3 = re.compile(r"^[a-z2-7]{56}\.onion$")


class TorError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OnionClientCredential:
    device: str
    onion: str
    public_key: str
    private_key: str

    def invitation_value(self) -> str:
        return f"descriptor:x25519:{self.private_key}"


class TorServiceManager:
    """Run isolated Tor v3 services without writing secrets to application logs."""

    def __init__(self, root: Path, tor_path: str = "tor") -> None:
        self.root = root
        self.tor_path = tor_path
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._client_processes: dict[str, subprocess.Popen[str]] = {}
        self._client_ports: dict[str, int] = {}

    def available(self) -> bool:
        return bool(shutil.which(self.tor_path))

    def issue_client_credential(self, share: PeerShare, peer: AuthorizedPeer) -> OnionClientCredential:
        if not share.onion_address or not ONION_V3.fullmatch(share.onion_address):
            raise TorError("Start the Onion Service before issuing client authorization")
        private = X25519PrivateKey.generate()
        private_raw = private.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        encode = lambda value: base64.b32encode(value).decode("ascii").rstrip("=")
        public, secret = encode(public_raw), encode(private_raw)
        peer.onion_client_public_key = public
        self._write_authorized_client(share, peer)
        self.reload(share.id)
        return OnionClientCredential(peer.name, share.onion_address, public, secret)

    def revoke_client(self, share: PeerShare, peer: AuthorizedPeer) -> None:
        path = self._service_dir(share) / "authorized_clients" / f"{self._safe_name(peer.name)}.auth"
        path.unlink(missing_ok=True)
        peer.onion_client_public_key = ""
        self.reload(share.id)

    def install_client_credential(self, onion: str, private_key: str) -> Path:
        onion = onion.lower()
        if not ONION_V3.fullmatch(onion) or not re.fullmatch(r"[A-Z2-7]{52}", private_key):
            raise TorError("Invalid Tor v3 client-authorization material")
        target = self.root / "client-auth"
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = target / f"{onion[:-6]}.auth_private"
        self._private_write(path, f"{onion}:descriptor:x25519:{private_key}\n")
        return target

    def start(self, share: PeerShare, target_port: int | Iterable[int], timeout: float = 20.0) -> str:
        if not share.onion_enabled:
            raise TorError("Onion Service is not enabled for this workspace")
        binary = shutil.which(self.tor_path)
        if not binary:
            raise TorError("Tor is not installed; install Tor or disable the Tor-only policy")
        service = self._service_dir(share)
        data = self.root / "instances" / share.id
        for directory in (service, data, service / "authorized_clients"):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        for peer in share.authorized_peers:
            if peer.enabled and peer.onion_client_public_key:
                self._write_authorized_client(share, peer)
        config = data / "torrc"
        target_ports = [target_port] if isinstance(target_port, int) else list(dict.fromkeys(target_port))
        if not target_ports:
            raise TorError("Onion Service has no authorized peer endpoint")
        lines = [
            f"DataDirectory {data}", "SocksPort auto", "AvoidDiskWrites 1",
            f"HiddenServiceDir {service}", "HiddenServiceVersion 3",
            f"ClientOnionAuthDir {self.root / 'client-auth'}",
        ]
        lines.extend(f"HiddenServicePort {port} 127.0.0.1:{port}" for port in target_ports)
        if share.tor_bridge_lines:
            lines.append("UseBridges 1")
            lines.extend(f"Bridge {self._safe_profile(value)}" for value in share.tor_bridge_lines)
            lines.extend(f"ClientTransportPlugin {self._safe_transport_plugin(value)}" for value in share.tor_pluggable_transports)
        self._private_write(config, "\n".join(lines) + "\n")
        process = subprocess.Popen(
            [binary, "-f", str(config)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, **new_process_group(),
        )
        self._processes[share.id] = process
        hostname = service / "hostname"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and process.poll() is None:
            if hostname.is_file():
                address = hostname.read_text(encoding="ascii").strip().lower()
                if ONION_V3.fullmatch(address):
                    share.onion_address = address
                    return address
            time.sleep(0.1)
        self.stop(share.id)
        raise TorError("Tor did not publish the Onion Service before the timeout")

    def start_client(self, remote: str) -> Path:
        """Start a private SOCKS instance that knows TuxInDrive client auth."""
        binary = shutil.which(self.tor_path)
        if not binary:
            raise TorError("Tor is not installed; no clearnet fallback was attempted")
        safe = self._safe_name(remote)
        data = self.root / "clients" / safe
        data.mkdir(parents=True, exist_ok=True, mode=0o700)
        current = self._client_processes.get(remote)
        if current and current.poll() is None and remote in self._client_ports:
            port = self._client_ports[remote]
            torsocks = data / "torsocks.conf"
            if torsocks.is_file():
                return torsocks
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        torrc = data / "torrc"
        self._private_write(torrc, "\n".join((
            f"DataDirectory {data}", f"SocksPort 127.0.0.1:{port}", "AvoidDiskWrites 1",
            f"ClientOnionAuthDir {self.root / 'client-auth'}",
        )) + "\n")
        process = subprocess.Popen(
            [binary, "-f", str(torrc)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, **new_process_group(),
        )
        self._client_processes[remote] = process
        self._client_ports[remote] = port
        torsocks = data / "torsocks.conf"
        self._private_write(torsocks, f"TorAddress 127.0.0.1\nTorPort {port}\nOnionAddrRange 127.42.42.0/24\n")
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline and process.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    return torsocks
            except OSError:
                time.sleep(0.1)
        self._client_processes.pop(remote, None)
        self._client_ports.pop(remote, None)
        raise TorError("Tor client did not establish a private SOCKS listener; no clearnet fallback was attempted")

    def reload(self, share_id: str) -> None:
        process = self._processes.get(share_id)
        if process and process.poll() is None:
            reload_process(process)

    def stop(self, share_id: str) -> None:
        process = self._processes.pop(share_id, None)
        if process and process.poll() is None:
            try:
                terminate_process(process)
            except ProcessLookupError:
                pass
        shutil.rmtree(self.root / "ephemeral" / share_id, ignore_errors=True)

    def shutdown(self) -> None:
        for share_id in list(self._processes):
            self.stop(share_id)
        for remote, process in list(self._client_processes.items()):
            if process.poll() is None:
                try:
                    terminate_process(process)
                except ProcessLookupError:
                    pass
            self._client_processes.pop(remote, None)
            self._client_ports.pop(remote, None)

    def _service_dir(self, share: PeerShare) -> Path:
        base = self.root / ("services" if share.onion_persistent else "ephemeral") / share.id
        return base

    def _write_authorized_client(self, share: PeerShare, peer: AuthorizedPeer) -> None:
        if not re.fullmatch(r"[A-Z2-7]{52}", peer.onion_client_public_key):
            raise TorError(f"Invalid Onion authorization key for {peer.name}")
        path = self._service_dir(share) / "authorized_clients" / f"{self._safe_name(peer.name)}.auth"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._private_write(path, f"descriptor:x25519:{peer.onion_client_public_key}\n")

    @staticmethod
    def _private_write(path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(value, encoding="utf-8")
        os.chmod(path, 0o600)

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:64] or "device"

    @staticmethod
    def _safe_profile(value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise TorError("Invalid bridge or pluggable-transport profile")
        return value

    @staticmethod
    def _safe_transport_plugin(value: str) -> str:
        value = TorServiceManager._safe_profile(value)
        fields = value.split()
        allowed = {"obfs4": "/usr/bin/obfs4proxy", "snowflake": "/usr/bin/snowflake-client"}
        if len(fields) < 3 or fields[1] != "exec" or fields[0] not in allowed:
            raise TorError("Only packaged obfs4 or snowflake pluggable transports are allowed")
        executable = str(Path(fields[2]).resolve(strict=False))
        if executable != allowed[fields[0]]:
            raise TorError("Pluggable transport must use its packaged executable")
        return " ".join((fields[0], "exec", executable, *fields[3:]))


def enforce_transport_policy(share: PeerShare, transport: str) -> None:
    policy = share.transport_policy
    if policy is PeerTransportPolicy.TOR_ONLY and transport != "tor":
        raise TorError("Policy violation: this workspace permits Tor transport only")
    if policy is PeerTransportPolicy.DIRECT_ONLY and transport != "direct":
        raise TorError("Policy violation: this workspace permits direct transport only")
    if share.no_relay and transport == "relay":
        raise TorError("Policy violation: relays are disabled for this workspace")
    if share.no_public_ip_discovery and transport in {"direct", "relay"}:
        raise TorError("Policy violation: public IP discovery is disabled; use Tor")
