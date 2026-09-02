"""Loopback-only automated networking scenarios using fictional data.

The lab deliberately does not load the desktop configuration, cloud accounts or
the headless synchronization agent.  It exercises the production HTTP server
and client against an ephemeral private database bound to 127.0.0.1.
"""

from __future__ import annotations

import argparse
import base64
import http.client
import json
import os
import secrets
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .server import ServerConfig, TuxInDriveServer, hash_token
from .server_client import ServerClient, ServerClientError


LAB_RELEASE_CHANNEL = "network-lab"
LAB_SCHEMA = 1
ProgressCallback = Callable[["ScenarioResult", str], None]


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    status: str
    duration_ms: int
    detail: str


class NetworkLabRunner:
    """Run bounded production-protocol tests without touching real user data."""

    SCENARIOS = (
        ("sandbox-boundary", "Loopback and production-data isolation", "_scenario_boundary"),
        ("public-probe", "Public health probe and security headers", "_scenario_public_probe"),
        ("authentication", "Authentication and capabilities", "_scenario_authentication"),
        ("mailbox", "Encrypted mailbox delivery and acknowledgement", "_scenario_mailbox"),
        ("mailbox-routing", "Mailbox device routing and missing acknowledgement", "_scenario_mailbox_routing"),
        ("objects", "Content-addressed objects and tenant isolation", "_scenario_objects"),
        ("object-deduplication", "Object deduplication and digest validation", "_scenario_object_deduplication"),
        ("rendezvous", "Device rendezvous replacement", "_scenario_rendezvous"),
        ("collaboration", "Collaborative operation delivery", "_scenario_collaboration"),
        ("tenant-isolation", "Cross-service tenant isolation", "_scenario_tenant_isolation"),
        ("functional-workflow", "Two-client collaboration workflow", "_scenario_functional_workflow"),
        ("invalid-input", "Malformed and unsafe input rejection", "_scenario_invalid_input"),
        ("disabled-roles", "Disabled production roles stay unavailable", "_scenario_disabled_roles"),
        ("mcp-read-only", "Read-only MCP protocol boundary", "_scenario_mcp_read_only"),
        ("concurrency", "Concurrent fictional clients", "_scenario_concurrency"),
        ("loopback-traffic", "Multi-address loopback traffic", "_scenario_loopback_traffic"),
        ("observability", "Audit and storage statistics", "_scenario_observability"),
        ("quota", "Tenant quota rejection and continued health", "_scenario_quota"),
        ("restart", "Server restart and durable opaque data", "_scenario_restart"),
    )

    def __init__(
        self,
        output_dir: Path | None = None,
        keep_sandbox: bool = False,
        pace_seconds: float = 0.0,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        state_root = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        self.output_dir = Path(output_dir or state_root / "tuxindrive/network-lab" / timestamp).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.output_dir, 0o700)
        self.keep_sandbox = bool(keep_sandbox)
        self.pace_seconds = max(0.0, min(2.0, float(pace_seconds)))
        self.jsonl_path = self.output_dir / "network-lab.jsonl"
        self.log_path = self.output_dir / "network-lab.log"
        self.summary_path = self.output_dir / "summary.json"
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.sandbox: Path | None = None
        self.server: TuxInDriveServer | None = None
        self.server_thread: threading.Thread | None = None
        self.owner_token = ""
        self.member_token = ""
        self.guest_token = ""
        self.owner: ServerClient | None = None
        self.member: ServerClient | None = None
        self.guest: ServerClient | None = None
        self.results: list[ScenarioResult] = []
        self._log_lock = threading.Lock()
        self._durable_digest = ""
        self.loopback_connections = 0
        self.loopback_bytes = 0

    def _private_append(self, path: Path, text: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, text.encode("utf-8"))
        finally:
            os.close(descriptor)

    def _event(self, level: str, message: str, scenario: str = "runner") -> None:
        clean = " ".join(str(message).replace("\x00", "").splitlines())[:1000]
        event = {
            "schema": LAB_SCHEMA,
            "time": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "scenario": scenario,
            "message": clean,
        }
        with self._log_lock:
            self._private_append(self.jsonl_path, json.dumps(event, separators=(",", ":")) + "\n")
            self._private_append(self.log_path, f"{event['time']} {level.upper():7} {scenario}: {clean}\n")

    def _start_server(self) -> None:
        if self.sandbox is None:
            raise RuntimeError("Sandbox has not been created")
        config = ServerConfig(
            bind="127.0.0.1",
            port=0,
            database=str(self.sandbox / "fictional-server.sqlite3"),
            client_config="",
            enabled_roles=["mailbox", "rendezvous", "objects", "collaboration", "mcp"],
            token_hashes={
                hash_token(self.owner_token): "owner",
                hash_token(self.member_token): "owner",
                hash_token(self.guest_token): "guest",
            },
            quota_mib_per_tenant=1,
            global_bandwidth_limit="10M",
            automatic_bandwidth_control=False,
            max_concurrent_requests=16,
            max_requests_per_source=16,
        )
        self.server = TuxInDriveServer(config)
        host, port = self.server.server_address[:2]
        if host != "127.0.0.1" or not port or self.server.agent is not None:
            self.server.server_close()
            raise RuntimeError("Network Lab isolation boundary could not be established")
        self.server_thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.server_thread.start()
        url = f"http://127.0.0.1:{port}"
        self.owner = ServerClient(url, token=self.owner_token, timeout=3)
        self.member = ServerClient(url, token=self.member_token, timeout=3)
        self.guest = ServerClient(url, token=self.guest_token, timeout=3)
        self.owner.health()

    def _stop_server(self) -> None:
        server, thread = self.server, self.server_thread
        self.server = None
        self.server_thread = None
        self.owner = None
        self.member = None
        self.guest = None
        if server is not None:
            server.shutdown()
            if thread is not None:
                thread.join(timeout=3)
            server.server_close()

    @staticmethod
    def _opaque(data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    def _request(self, client: ServerClient | None, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        if client is None:
            raise RuntimeError("Fictional client is not connected")
        return client.request(path, method, payload)

    def _scenario_boundary(self) -> str:
        assert self.server is not None and self.sandbox is not None
        assert self.server.server_address[0] == "127.0.0.1"
        assert self.server.agent is None
        assert self.server.config.client_config == ""
        assert Path(self.server.config.database).parent == self.sandbox
        return "Loopback-only ephemeral server; cloud accounts and synchronization agent are disabled"

    def _scenario_public_probe(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address[:2]
        connection = http.client.HTTPConnection(host, port, timeout=3)
        try:
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            public_body = json.loads(response.read().decode("utf-8"))
            assert response.status == 200 and public_body == {"status": "ok"}
            assert response.getheader("Cache-Control") == "no-store"
            assert response.getheader("Content-Security-Policy") == "default-src 'none'"
            connection.request("GET", "/v1/health")
            private_response = connection.getresponse()
            private_response.read()
            assert private_response.status == 401
        finally:
            connection.close()
        return "Minimal public probe succeeded, private health required a token, and security headers were present"

    def _scenario_authentication(self) -> str:
        health = self._request(self.owner, "/v1/health")
        capabilities = self._request(self.owner, "/v1/capabilities")
        assert health["status"] == "ok" and "agent" not in capabilities["roles"]
        bad = ServerClient(self.owner.url, token="fictional-invalid-token", timeout=3)  # type: ignore[union-attr]
        try:
            bad.health()
        except ServerClientError as exc:
            assert "403" in str(exc)
        else:
            raise AssertionError("Invalid token was accepted")
        return "Valid clients accepted; invalid bearer token rejected; agent role absent"

    def _scenario_mailbox(self) -> str:
        created = self._request(self.owner, "/v1/mailbox", "POST", {"recipient": "alice-device", "body": self._opaque(b"fictional encrypted hello"), "ttl": 3600})
        inbox = self._request(self.owner, "/v1/mailbox?recipient=alice-device")
        assert len(inbox["messages"]) == 1
        assert base64.b64decode(inbox["messages"][0]["body"]) == b"fictional encrypted hello"
        ack = self._request(self.owner, f"/v1/mailbox/{created['id']}?recipient=alice-device", "DELETE")
        assert ack["acknowledged"] is True
        return "Fictional opaque message delivered, decoded by client and acknowledged"

    def _scenario_mailbox_routing(self) -> str:
        created = self._request(self.owner, "/v1/mailbox", "POST", {
            "recipient": "bob-tablet", "body": self._opaque(b"fictional routed message"), "ttl": 3600,
        })
        wrong_device = self._request(self.member, "/v1/mailbox?recipient=alice-phone")
        correct_device = self._request(self.member, "/v1/mailbox?recipient=bob-tablet")
        assert wrong_device["messages"] == [] and len(correct_device["messages"]) == 1
        missing = self._request(
            self.member,
            "/v1/mailbox/00000000000000000000000000000000?recipient=bob-tablet",
            "DELETE",
        )
        assert missing["acknowledged"] is False
        acknowledged = self._request(
            self.member, f"/v1/mailbox/{created['id']}?recipient=bob-tablet", "DELETE"
        )
        assert acknowledged["acknowledged"] is True
        return "Only the addressed fictional device received the message; missing and valid acknowledgements were distinguished"

    def _scenario_objects(self) -> str:
        payload = b"fictional encrypted project block v1"
        created = self._request(self.owner, "/v1/objects", "POST", {"body": self._opaque(payload), "ttl": 3600})
        self._durable_digest = created["digest"]
        fetched = self._request(self.owner, f"/v1/objects/{created['digest']}")
        assert base64.b64decode(fetched["body"]) == payload
        try:
            self._request(self.guest, f"/v1/objects/{created['digest']}")
        except ServerClientError as exc:
            assert "404" in str(exc)
        else:
            raise AssertionError("Object crossed tenant boundary")
        return "Content digest verified and second fictional tenant could not read the object"

    def _scenario_object_deduplication(self) -> str:
        payload = b"fictional duplicate encrypted block"
        first = self._request(self.owner, "/v1/objects", "POST", {
            "body": self._opaque(payload), "ttl": 3600,
        })
        second = self._request(self.member, "/v1/objects", "POST", {
            "body": self._opaque(payload), "ttl": 3600,
        })
        assert first["digest"] == second["digest"] and second["existing"] is True
        try:
            self._request(self.owner, "/v1/objects/not-a-sha256")
        except ServerClientError as exc:
            assert "400" in str(exc)
        else:
            raise AssertionError("Malformed digest was accepted")
        return "Same-tenant duplicate reused one object and malformed digest lookup was rejected"

    def _scenario_rendezvous(self) -> str:
        for value in (b"fictional-envelope-1", b"fictional-envelope-2"):
            self._request(self.owner, "/v1/rendezvous", "POST", {"device": "alice-laptop", "envelope": self._opaque(value), "ttl": 3600})
        fetched = self._request(self.owner, "/v1/rendezvous/alice-laptop")
        assert base64.b64decode(fetched["envelope"]) == b"fictional-envelope-2"
        return "Latest device envelope safely replaced the prior fictional envelope"

    def _scenario_collaboration(self) -> str:
        operations = [b"fictional-create-document", b"fictional-edit-line-1"]
        for operation in operations:
            self._request(self.owner, "/v1/collaboration", "POST", {"workspace": "demo-team", "body": self._opaque(operation), "ttl": 3600})
        fetched = self._request(self.owner, "/v1/collaboration?workspace=demo-team")
        assert [base64.b64decode(item["body"]) for item in fetched["operations"]] == operations
        return "Two fictional collaboration operations retained deterministic order"

    def _scenario_tenant_isolation(self) -> str:
        assert self._request(self.guest, "/v1/mailbox?recipient=alice-device")["messages"] == []
        assert self._request(self.guest, "/v1/collaboration?workspace=demo-team")["operations"] == []
        try:
            self._request(self.guest, "/v1/rendezvous/alice-laptop")
        except ServerClientError as exc:
            assert "404" in str(exc)
        else:
            raise AssertionError("Rendezvous envelope crossed tenant boundary")
        return "Guest tenant could not see owner mailbox, collaboration operations or rendezvous envelope"

    def _scenario_functional_workflow(self) -> str:
        self._request(self.owner, "/v1/rendezvous", "POST", {
            "device": "workflow-alice", "envelope": self._opaque(b"fictional-alice-presence"), "ttl": 3600,
        })
        presence = self._request(self.member, "/v1/rendezvous/workflow-alice")
        assert base64.b64decode(presence["envelope"]) == b"fictional-alice-presence"
        message = self._request(self.owner, "/v1/mailbox", "POST", {
            "recipient": "workflow-bob", "body": self._opaque(b"fictional-workspace-invitation"), "ttl": 3600,
        })
        inbox = self._request(self.member, "/v1/mailbox?recipient=workflow-bob")
        assert base64.b64decode(inbox["messages"][0]["body"]) == b"fictional-workspace-invitation"
        shared = self._request(self.owner, "/v1/objects", "POST", {
            "body": self._opaque(b"fictional-shared-document"), "ttl": 3600,
        })
        downloaded = self._request(self.member, f"/v1/objects/{shared['digest']}")
        assert base64.b64decode(downloaded["body"]) == b"fictional-shared-document"
        self._request(self.member, "/v1/collaboration", "POST", {
            "workspace": "workflow-project", "body": self._opaque(b"fictional-bob-edit"), "ttl": 3600,
        })
        edits = self._request(self.owner, "/v1/collaboration?workspace=workflow-project")
        assert base64.b64decode(edits["operations"][0]["body"]) == b"fictional-bob-edit"
        ack = self._request(
            self.member, f"/v1/mailbox/{message['id']}?recipient=workflow-bob", "DELETE"
        )
        assert ack["acknowledged"] is True
        return "Alice advertised, invited Bob, shared an object, received Bob's edit and observed acknowledgement"

    def _scenario_invalid_input(self) -> str:
        rejected = 0
        for payload in (
            {"recipient": "../unsafe", "body": self._opaque(b"x")},
            {"recipient": "device", "body": "not-base64!"},
            {"recipient": "device", "body": ""},
        ):
            try:
                self._request(self.owner, "/v1/mailbox", "POST", payload)
            except ServerClientError as exc:
                assert "400" in str(exc)
                rejected += 1
        assert rejected == 3
        return "Traversal-like identifier, malformed base64 and empty payload were rejected"

    def _scenario_disabled_roles(self) -> str:
        for path in ("/v1/jobs", "/v1/attestation"):
            try:
                self._request(self.owner, path)
            except ServerClientError as exc:
                assert "404" in str(exc)
            else:
                raise AssertionError(f"Disabled endpoint was available: {path}")
        assert self.server is not None
        assert not ({"agent", "relay", "attestation"} & set(self.server.config.enabled_roles))
        return "Agent, relay and attestation roles remained disabled throughout the local lab"

    def _scenario_mcp_read_only(self) -> str:
        initialize = self._request(self.owner, "/v1/mcp", "POST", {
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {},
        })
        tools = self._request(self.owner, "/v1/mcp", "POST", {
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        health = self._request(self.member, "/v1/mcp", "POST", {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "health", "arguments": {}},
        })
        mutation = self._request(self.owner, "/v1/mcp", "POST", {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "delete_everything", "arguments": {}},
        })
        assert initialize["result"]["serverInfo"]["name"] == "tuxindrive-server"
        assert all(
            item["name"] in {"health", "list_jobs", "recent_audit"}
            for item in tools["result"]["tools"]
        )
        assert health["result"]["content"]
        assert mutation["error"]["code"] == -32602
        return "Read-only MCP tools initialized successfully and an invented mutation was rejected"

    def _scenario_concurrency(self) -> str:
        def upload(index: int) -> str:
            result = self._request(self.owner, "/v1/objects", "POST", {"body": self._opaque(f"fictional-concurrent-{index}".encode()), "ttl": 3600})
            return str(result["digest"])
        with ThreadPoolExecutor(max_workers=6) as pool:
            digests = list(pool.map(upload, range(12)))
        assert len(set(digests)) == 12
        return "12 concurrent bounded client operations completed with unique verified digests"

    def _scenario_loopback_traffic(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address[:2]

        def exchange(source: str, token: str, marker: bytes) -> tuple[int, str]:
            payload = (marker * ((128 * 1024 // len(marker)) + 1))[:128 * 1024]
            request_body = json.dumps(
                {"body": self._opaque(payload), "ttl": 3600}, separators=(",", ":")
            ).encode("utf-8")
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Content-Length": str(len(request_body)),
                "User-Agent": "TuxInDrive-Network-Lab/1",
            }
            connection = http.client.HTTPConnection(
                host, port, timeout=5, source_address=(source, 0)
            )
            try:
                connection.request("POST", "/v1/objects", body=request_body, headers=headers)
                response = connection.getresponse()
                response_body = response.read()
                assert response.status == 201
                created = json.loads(response_body.decode("utf-8"))
                connection.request("GET", f"/v1/objects/{created['digest']}", headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "User-Agent": "TuxInDrive-Network-Lab/1",
                })
                fetched_response = connection.getresponse()
                fetched_body = fetched_response.read()
                assert fetched_response.status == 200
                fetched = json.loads(fetched_body.decode("utf-8"))
                assert base64.b64decode(fetched["body"]) == payload
                return len(request_body) + len(response_body) + len(fetched_body), created["digest"]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            alice = pool.submit(exchange, "127.0.0.2", self.owner_token, b"alice-traffic-")
            bob = pool.submit(exchange, "127.0.0.3", self.member_token, b"bob-traffic-")
            transfers = [alice.result(), bob.result()]
        assert transfers[0][1] != transfers[1][1]
        self.loopback_connections = 2
        self.loopback_bytes = sum(item[0] for item in transfers)
        return (
            f"2 real HTTP connections from 127.0.0.2 and 127.0.0.3 transferred "
            f"{self.loopback_bytes} bytes through 127.0.0.1"
        )

    def _scenario_observability(self) -> str:
        stats = self._request(self.owner, "/v1/stats")["storage"]
        audit = self._request(self.owner, "/v1/audit?limit=100")["events"]
        assert stats["objects"]["items"] >= 13
        assert any(event["result"] == "rejected" for event in audit)
        return f"Statistics reported {stats['objects']['items']} objects; audit includes rejected and successful operations"

    def _scenario_quota(self) -> str:
        self._request(self.owner, "/v1/objects", "POST", {
            "body": self._opaque(b"q" * (700 * 1024)), "ttl": 3600,
        })
        try:
            self._request(self.owner, "/v1/objects", "POST", {
                "body": self._opaque(b"r" * (400 * 1024)), "ttl": 3600,
            })
        except ServerClientError as exc:
            assert "400" in str(exc) and "quota" in str(exc).lower()
        else:
            raise AssertionError("Tenant quota was not enforced")
        assert self._request(self.owner, "/v1/health")["status"] == "ok"
        guest = self._request(self.guest, "/v1/objects", "POST", {
            "body": self._opaque(b"fictional-guest-after-owner-quota"), "ttl": 3600,
        })
        assert guest["digest"]
        return "Owner quota rejected excess data while server health and an independent tenant remained operational"

    def _scenario_restart(self) -> str:
        digest = self._durable_digest
        assert digest
        self._stop_server()
        self._start_server()
        fetched = self._request(self.owner, f"/v1/objects/{digest}")
        assert base64.b64decode(fetched["body"]) == b"fictional encrypted project block v1"
        return "Opaque fictional object remained valid after a clean local server restart"

    def run(self, progress: ProgressCallback | None = None, cancel: threading.Event | None = None) -> list[ScenarioResult]:
        self.results = []
        cancel = cancel or threading.Event()
        self.owner_token = secrets.token_urlsafe(48)
        self.member_token = secrets.token_urlsafe(48)
        self.guest_token = secrets.token_urlsafe(48)
        if self.keep_sandbox:
            self.sandbox = self.output_dir / "sandbox"
            self.sandbox.mkdir(mode=0o700, exist_ok=True)
        else:
            self._temporary = tempfile.TemporaryDirectory(prefix="tuxindrive-network-lab-")
            self.sandbox = Path(self._temporary.name)
        os.chmod(self.sandbox, 0o700)
        self._event("info", f"Starting TuxInDrive {__version__} local scenario run")
        try:
            self._start_server()
            for identifier, title, method_name in self.SCENARIOS:
                if cancel.is_set():
                    result = ScenarioResult(title, "cancelled", 0, "Run cancelled by user")
                    self.results.append(result)
                    if progress: progress(result, identifier)
                    break
                if progress:
                    progress(ScenarioResult(title, "running", 0, "Scenario is running"), identifier)
                self._event("info", "started", identifier)
                started = time.monotonic()
                try:
                    detail = str(getattr(self, method_name)())
                    status = "passed"
                    level = "info"
                except Exception as exc:  # scenario runner must retain subsequent diagnostics
                    detail = f"{type(exc).__name__}: {exc}"[:500]
                    status = "failed"
                    level = "error"
                result = ScenarioResult(title, status, int((time.monotonic() - started) * 1000), detail)
                self.results.append(result)
                self._event(level, f"{status}: {detail}", identifier)
                if progress: progress(result, identifier)
                if self.pace_seconds and not cancel.is_set():
                    cancel.wait(self.pace_seconds)
        except Exception as exc:
            result = ScenarioResult("Lab startup", "failed", 0, f"{type(exc).__name__}: {exc}"[:500])
            self.results.append(result)
            self._event("error", result.detail, "startup")
            if progress: progress(result, "startup")
        finally:
            self._stop_server()
            self.owner_token = ""
            self.member_token = ""
            self.guest_token = ""
            if self._temporary is not None:
                self._temporary.cleanup()
                self._temporary = None
            summary = {
                "schema": LAB_SCHEMA,
                "release_channel": LAB_RELEASE_CHANNEL,
                "tuxindrive_version": __version__,
                "fictional_data_only": True,
                "external_network_used": False,
                "loopback_connections": self.loopback_connections,
                "loopback_bytes": self.loopback_bytes,
                "loopback_sources": ["127.0.0.2", "127.0.0.3"] if self.loopback_connections else [],
                "passed": sum(item.status == "passed" for item in self.results),
                "failed": sum(item.status == "failed" for item in self.results),
                "results": [asdict(item) for item in self.results],
            }
            self.summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            os.chmod(self.summary_path, 0o600)
            self._event("info", f"Completed: {summary['passed']} passed, {summary['failed']} failed")
        return list(self.results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated TuxInDrive server/client networking scenarios")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--keep-sandbox", action="store_true", help="retain fictional sandbox data for inspection")
    parser.add_argument("--json", action="store_true", help="print the machine-readable summary")
    args = parser.parse_args(argv)
    runner = NetworkLabRunner(args.output_dir, args.keep_sandbox)
    results = runner.run()
    if args.json:
        print(runner.summary_path.read_text(encoding="utf-8"), end="")
    else:
        for result in results:
            print(f"{result.status.upper():9} {result.duration_ms:5} ms  {result.name}: {result.detail}")
        print(f"Logs: {runner.output_dir}")
    return 1 if any(result.status == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
