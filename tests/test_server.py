import base64
import http.client
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tuxindrive.models import AppConfig, AppSettings
from tuxindrive.server import (
    HeadlessAgent,
    ServerConfig,
    ServerError,
    TuxInDriveServer,
    _private_write,
    hash_token,
    initialize,
)
from tuxindrive.server_client import ServerClient, ServerClientError, normalize_server_url
from tuxindrive.server_credentials import credential_account
from tuxindrive.server_store import ServerStore, ServerStoreError
from tuxindrive.server_admin import _read_owned_source


class ServerStoreTests(unittest.TestCase):
    def test_opaque_mailbox_round_trip_and_acknowledgement(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ServerStore(Path(folder) / "store.sqlite3")
            created = store.put_mail("tenant", "device", b"ciphertext", 3600)
            items = store.list_mail("tenant", "device")
            self.assertEqual(items[0]["body"], b"ciphertext")
            self.assertTrue(store.acknowledge_mail("tenant", "device", created["id"]))
            self.assertEqual(store.list_mail("tenant", "device"), [])
        store.close()

    def test_object_is_content_addressed_and_tenant_isolated(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ServerStore(Path(folder) / "store.sqlite3")
            result = store.put_object("one", b"encrypted block", 3600)
            self.assertEqual(store.get_object("one", result["digest"]), b"encrypted block")
            self.assertIsNone(store.get_object("two", result["digest"]))
            second = store.put_object("two", b"encrypted block", 3600)
            self.assertFalse(second["existing"])
            self.assertEqual(store.get_object("two", result["digest"]), b"encrypted block")
            store.close()

    def test_rendezvous_replacement_and_collaboration_delivery(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ServerStore(Path(folder) / "store.sqlite3")
            store.put_rendezvous("tenant", "phone", b"signed-1", 3600)
            store.put_rendezvous("tenant", "phone", b"signed-2", 3600)
            self.assertEqual(store.get_rendezvous("tenant", "phone"), b"signed-2")
            store.put_collaboration("tenant", "workspace", b"encrypted-op", 3600)
            self.assertEqual(store.list_collaboration("tenant", "workspace")[0]["body"], b"encrypted-op")
            store.close()

    def test_collaboration_preserves_insertion_order_within_one_second(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch("tuxindrive.server_store.time.time", return_value=1000):
            store = ServerStore(Path(folder) / "store.sqlite3")
            store.put_collaboration("tenant", "workspace", b"first", 3600)
            store.put_collaboration("tenant", "workspace", b"second", 3600)
            self.assertEqual(
                [item["body"] for item in store.list_collaboration("tenant", "workspace")],
                [b"first", b"second"],
            )
            store.close()

    def test_quota_and_identifiers_are_bounded(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ServerStore(Path(folder) / "store.sqlite3", quota_bytes=1024 * 1024)
            with self.assertRaises(ServerStoreError):
                store.put_mail("../tenant", "device", b"x", 3600)
            with self.assertRaises(ServerStoreError):
                store.put_object("tenant", b"x" * (1024 * 1024 + 1), 3600)
            store.close()

    def test_expired_rows_are_purged(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ServerStore(Path(folder) / "store.sqlite3")
            item = store.put_mail("tenant", "device", b"x", 60)
            store._connection.execute("UPDATE mailbox SET expires=? WHERE id=?", (int(time.time()) - 1, item["id"]))
            store._connection.commit()
            self.assertEqual(store.list_mail("tenant", "device"), [])
            store.close()


class ServerBandwidthTests(unittest.TestCase):
    def test_headless_agent_can_share_the_server_bandwidth_controller(self):
        from tuxindrive.bandwidth import GlobalBandwidthController

        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": folder, "XDG_DATA_HOME": folder, "XDG_CACHE_HOME": folder},
        ):
            controller = GlobalBandwidthController(
                "10M", automatic=True, headroom_percent=20
            )
            agent = HeadlessAgent("", "10M", bandwidth=controller)
            self.assertIs(agent.bandwidth, controller)
            self.assertIs(agent.engine.bandwidth, controller)


class ServerConfigurationTests(unittest.TestCase):
    def test_initialization_creates_private_config_and_one_time_token_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = root / "server.json"; token_file = root / "token"
            token = initialize(config, root / "state", token_file)
            raw = json.loads(config.read_text())
            self.assertEqual(raw["token_hashes"], {hash_token(token): "owner"})
            self.assertEqual(token_file.read_text().strip(), token)
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
            repository = Path(__file__).resolve().parents[1]
            self.assertIn("Package: tuxindrive-server", (repository / "packaging/server/DEBIAN/control").read_text())
            self.assertIn("ProtectSystem=strict", (repository / "packaging/server/tuxindrive-server.service").read_text())
            self.assertTrue((repository / "scripts/build-server-deb.sh").is_file())

    def test_private_write_refuses_precreated_temporary_symlink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            victim = root / "victim"
            victim.write_text("unchanged", encoding="utf-8")
            hostile = root / ".server.json.known.tmp"
            hostile.symlink_to(victim)
            with mock.patch("tuxindrive.server.secrets.token_hex", return_value="known"):
                with self.assertRaises(FileExistsError):
                    _private_write(root / "server.json", "replacement")
            self.assertEqual(victim.read_text(encoding="utf-8"), "unchanged")
            self.assertFalse(hostile.exists())

    def test_server_package_keeps_configuration_root_owned_and_read_only(self):
        repository = Path(__file__).resolve().parents[1]
        postinst = (repository / "packaging/server/DEBIAN/postinst").read_text(encoding="utf-8")
        service = (repository / "packaging/server/tuxindrive-server.service").read_text(encoding="utf-8")
        self.assertIn("-o root -g tuxindrive-server /etc/tuxindrive-server", postinst)
        self.assertIn("chown root:tuxindrive-server /etc/tuxindrive-server/server.json", postinst)
        self.assertIn("chmod 0640 /etc/tuxindrive-server/server.json", postinst)
        self.assertNotIn("runuser -u tuxindrive-server", postinst)
        self.assertIn("ReadWritePaths=/var/lib/tuxindrive-server\n", service)
        self.assertNotIn("ReadWritePaths=/var/lib/tuxindrive-server /etc", service)
        self.assertIn("TasksMax=128", service)
        self.assertIn("MemoryMax=768M", service)

    def test_server_launcher_preserves_only_user_cli_arguments(self):
        repository = Path(__file__).resolve().parents[1]
        launcher = repository / "packaging/server/tuxindrive-server"
        source = launcher.read_text(encoding="utf-8")
        self.assertIn("' \"$@\"", source)
        self.assertNotIn("' tuxindrive-server \"$@\"", source)
        self.assertIn('sys.path.insert(0,"/usr/lib/tuxindrive-server")', source)
        subprocess.run(["sh", "-n", str(launcher)], check=True)

    def test_server_package_uses_a_private_library_root(self):
        repository = Path(__file__).resolve().parents[1]
        build_script = (repository / "scripts/build-server-deb.sh").read_text(encoding="utf-8")
        self.assertIn("usr/lib/tuxindrive-server/tuxindrive", build_script)
        self.assertNotIn('$PACKAGE_ROOT/usr/lib/tuxindrive"', build_script)

    def test_server_gui_is_packaged_and_uses_narrow_privileged_actions(self):
        repository = Path(__file__).resolve().parents[1]
        gui = (repository / "src/tuxindrive/server_gui.py").read_text(encoding="utf-8")
        build = (repository / "scripts/build-server-deb.sh").read_text(encoding="utf-8")
        control = (repository / "packaging/server/DEBIAN/control").read_text(encoding="utf-8")
        desktop = (repository / "packaging/server/tuxindrive-server.desktop").read_text(encoding="utf-8")
        self.assertIn('["/usr/bin/pkexec"]', gui)
        self.assertNotIn("shell=True", gui)
        self.assertIn('PACKAGED_LAUNCHER, "admin"', gui)
        self.assertIn('"start": ["start", SERVICE]', gui)
        self.assertIn("write-config", gui)
        self.assertIn("tuxindrive-server.desktop", build)
        self.assertIn("tuxindrive-server.svg", build)
        self.assertIn("python3-gi", control)
        self.assertIn("gir1.2-gtk-3.0", control)
        self.assertIn("pkexec", control)
        self.assertIn("Exec=tuxindrive-server gui", desktop)
        self.assertIn("Terminal=false", desktop)

    def test_privileged_config_staging_rejects_wrong_permissions(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "server.json"
            source.write_text(json.dumps({"token_hashes": {"0" * 64: "owner"}}), encoding="utf-8")
            source.chmod(0o600)
            with mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid())}):
                self.assertEqual(_read_owned_source(source)["token_hashes"], {"0" * 64: "owner"})
                source.chmod(0o644)
                with self.assertRaises(ServerError):
                    _read_owned_source(source)

    def test_remote_bind_requires_tls(self):
        raw = {"bind": "0.0.0.0", "token_hashes": {"0" * 64: "owner"}}
        with self.assertRaises(ServerError):
            ServerConfig.from_dict(raw)

    def test_unknown_role_and_bad_token_mapping_fail_closed(self):
        with self.assertRaises(ServerError):
            ServerConfig.from_dict({"enabled_roles": ["shell"], "token_hashes": {"0" * 64: "owner"}})
        with self.assertRaises(ServerError):
            ServerConfig.from_dict({"token_hashes": {"short": "owner"}})

    def test_server_resource_limits_are_bounded(self):
        config = ServerConfig.from_dict({
            "token_hashes": {"0" * 64: "owner"},
            "max_concurrent_requests": 9999,
            "max_requests_per_source": 9999,
            "request_timeout_seconds": 0,
            "max_relay_connections": 9999,
            "max_relay_connections_per_tenant": 9999,
            "relay_idle_timeout_seconds": 0,
        })
        self.assertEqual(config.max_concurrent_requests, 256)
        self.assertEqual(config.max_requests_per_source, 256)
        self.assertEqual(config.request_timeout_seconds, 5)
        self.assertEqual(config.max_relay_connections, 64)
        self.assertEqual(config.max_relay_connections_per_tenant, 64)
        self.assertEqual(config.relay_idle_timeout_seconds, 5)

    def test_client_feature_flag_defaults_off_and_round_trips(self):
        self.assertFalse(AppSettings().server_integration_enabled)
        config = AppConfig.from_dict({"settings": {"server_integration_enabled": True, "server_url": "https://example.test:9443"}})
        self.assertTrue(config.settings.server_integration_enabled)
        self.assertEqual(config.to_dict()["settings"]["server_url"], "https://example.test:9443")

    def test_server_url_rejects_remote_plaintext_and_credentials(self):
        self.assertEqual(normalize_server_url("http://127.0.0.1:9443/"), "http://127.0.0.1:9443")
        with self.assertRaises(ValueError): normalize_server_url("http://example.test:9443")
        with self.assertRaises(ValueError): normalize_server_url("https://user:pass@example.test")
        with self.assertRaises(ValueError): normalize_server_url("https://example.test/path")
        self.assertEqual(credential_account("https://EXAMPLE.test:9443"), credential_account("https://example.test:9443"))


class ServerApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.token = "correct-token"
        self.guest_token = "guest-token"
        config = ServerConfig(
            bind="127.0.0.1", port=0,
            database=str(Path(self.temporary.name) / "server.sqlite3"),
            enabled_roles=["mailbox", "rendezvous", "objects", "collaboration", "attestation", "mcp", "relay"],
            token_hashes={hash_token(self.token): "owner", hash_token(self.guest_token): "guest"},
        )
        self.server = TuxInDriveServer(config)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_health_requires_token_but_healthz_is_minimal_public_probe(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("GET", "/healthz"); response = connection.getresponse(); self.assertEqual(response.status, 200); response.read()
        connection.request("GET", "/v1/health"); response = connection.getresponse(); self.assertEqual(response.status, 401); response.read(); connection.close()
        self.assertEqual(ServerClient(self.url, token=self.token).health()["status"], "ok")

    def test_mailbox_api_never_requires_plaintext_structure(self):
        client = ServerClient(self.url, token=self.token)
        body = base64.b64encode(os.urandom(64)).decode("ascii")
        created = client.request("/v1/mailbox", "POST", {"recipient": "phone", "body": body, "ttl": 3600})
        listed = client.request("/v1/mailbox?recipient=phone")
        self.assertEqual(listed["messages"][0]["body"], body)
        acknowledged = client.request(f"/v1/mailbox/{created['id']}?recipient=phone", "DELETE")
        self.assertTrue(acknowledged["acknowledged"])

    def test_object_rendezvous_and_collaboration_endpoints(self):
        client = ServerClient(self.url, token=self.token)
        opaque = base64.b64encode(b"encrypted").decode("ascii")
        obj = client.request("/v1/objects", "POST", {"body": opaque})
        self.assertEqual(client.request(f"/v1/objects/{obj['digest']}")["body"], opaque)
        client.request("/v1/rendezvous", "POST", {"device": "phone", "envelope": opaque})
        self.assertEqual(client.request("/v1/rendezvous/phone")["envelope"], opaque)
        client.request("/v1/collaboration", "POST", {"workspace": "work", "body": opaque})
        self.assertEqual(client.request("/v1/collaboration?workspace=work")["operations"][0]["body"], opaque)

    def test_bad_token_and_oversized_response_contract_fail(self):
        with self.assertRaises(ServerClientError): ServerClient(self.url, token="wrong").health()
        guest = ServerClient(self.url, token=self.guest_token)
        self.assertEqual(guest.request("/v1/stats")["storage"]["objects"]["items"], 0)
        with self.assertRaises(ServerClientError): guest.request("/v1/jobs")

    def test_mcp_is_read_only_and_unknown_mutation_is_rejected(self):
        client = ServerClient(self.url, token=self.token)
        tools = client.request("/v1/mcp", "POST", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {item["name"] for item in tools["result"]["tools"]}
        self.assertEqual(names, {"health", "list_jobs", "recent_audit"})
        denied = client.request("/v1/mcp", "POST", {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "delete"}})
        self.assertIn("error", denied)

    def test_relay_rejects_non_allowlisted_target(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        connection.request("CONNECT", "example.test:22", headers={"Authorization": f"Bearer {self.token}"})
        response = connection.getresponse(); self.assertEqual(response.status, 403); response.read(); connection.close()

    def test_relay_admission_is_global_and_tenant_bounded(self):
        self.assertTrue(self.server.reserve_relay("owner"))
        self.assertTrue(self.server.reserve_relay("owner"))
        self.assertFalse(self.server.reserve_relay("owner"))
        self.server.release_relay("owner")
        self.server.release_relay("owner")


if __name__ == "__main__":
    unittest.main()
