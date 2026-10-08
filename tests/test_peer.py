from tests import signal_safety as _signal_safety  # noqa: F401

import json
import os
import tempfile
import unittest
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxindrive.models import AuthorizedPeer, PeerRole, PeerShare, PeerTransportPolicy, SyncJob
from tuxindrive.peer import (
    DiscoveredPeer, FileLease, LanDiscovery, PeerError, PeerInvitation, PeerLeaseManager,
    PeerManager, PendingPeerRequest, key_fingerprint, normalize_public_key, validate_port,
)
from tuxindrive.security import sign_json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIK7mfakebutsyntacticallyvalidkey1234567890"


class PeerSharingTests(unittest.TestCase):
    def test_lan_discovery_queries_instead_of_waiting_for_frequent_beacons(self):
        invitation = PeerInvitation("Project", "192.0.2.10", 22022, KEY, "share")

        class FakeSocket:
            def __init__(self):
                self.sent = []
                self.delivered = False

            def setsockopt(self, *_args):
                pass

            def bind(self, *_args):
                pass

            def settimeout(self, *_args):
                pass

            def sendto(self, payload, address):
                self.sent.append((json.loads(payload), address))

            def recvfrom(self, _size):
                if not self.delivered:
                    self.delivered = True
                    return (
                        json.dumps({
                            "tuxindrive_lan": 1,
                            **json.loads(invitation.encode()),
                        }).encode("utf-8"),
                        ("192.0.2.10", 47777),
                    )
                raise socket.timeout

            def close(self):
                pass

        fake = FakeSocket()
        with patch("tuxindrive.peer.socket.socket", return_value=fake):
            found = LanDiscovery.discover(0.2)
        self.assertEqual(found[0].share_id, "share")
        self.assertEqual(fake.sent[0][0], {"tuxindrive_lan_query": 1})

    def test_invitation_round_trip_keeps_pinned_host_key(self):
        encoded = PeerInvitation("Project", "198.51.100.20", 22022, KEY).encode()
        decoded = PeerInvitation.decode(encoded)
        self.assertEqual(decoded.host, "198.51.100.20")
        self.assertEqual(decoded.port, 22022)
        self.assertEqual(decoded.host_key, KEY)
        self.assertEqual(json.loads(encoded)["tuxindrive_peer"], 6)

    def test_non_object_or_malformed_recipient_invitation_is_rejected(self):
        with self.assertRaises(PeerError):
            PeerInvitation.decode("[]")
        encoded = json.loads(PeerInvitation("Project", "192.0.2.10", 22022, KEY).encode())
        encoded["recipient_token"] = "not-a-recipient-token"
        with self.assertRaises(PeerError):
            PeerInvitation.decode(json.dumps(encoded))

    def test_unapproved_lan_share_can_be_discovered_without_exposing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Team folder", str(folder), "192.0.2.10", 22022, id="team")
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            manager = PeerManager(root=root)
            with patch.object(manager.discovery, "start"):
                manager.start(share)
            announcements = manager._discovery_invitations()
            self.assertIn(share.id, manager.shared_ids)
            self.assertFalse(manager.running_shares)
            self.assertEqual(len(announcements), 1)
            self.assertTrue(announcements[0].approval_required)
            with self.assertRaisesRegex(PeerError, "Request access"):
                DiscoveredPeer(
                    share.name, "192.0.2.10", share.port, KEY, share.id,
                    approval_required=True,
                ).invitation()

    def test_lan_access_request_is_rate_limited_deduplicated_and_never_auto_approved(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Team", str(folder), "192.0.2.10", id="team")
            manager = PeerManager(root=Path(temporary) / "peer")
            manager._advertised_shares[share.id] = share
            request = {
                "tuxindrive_lan_request": 1,
                "request_id": "a" * 32,
                "share_id": share.id,
                "device_name": "Alice laptop",
                "public_key": KEY,
            }
            manager._receive_access_request(request, "192.0.2.55")
            manager._receive_access_request({**request, "request_id": "b" * 32}, "192.0.2.55")
            pending = manager.pending_requests(share.id)
            self.assertEqual(len(pending), 1)
            self.assertIsInstance(pending[0], PendingPeerRequest)
            self.assertEqual(pending[0].fingerprint, key_fingerprint(KEY))
            self.assertEqual(share.authorized_peers, [])

    def test_authorized_lan_announcement_is_scoped_to_recipient(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare(
                "Team", str(folder), "192.0.2.10", 22022,
                authorized_peers=[AuthorizedPeer("Alice", KEY)], id="team",
            )
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            manager = PeerManager(root=root)
            manager._advertised_shares[share.id] = share
            announcements = manager._discovery_invitations()
            self.assertEqual(len(announcements), 2)
            public, authorized = announcements
            self.assertTrue(public.approval_required)
            self.assertFalse(authorized.approval_required)
            self.assertTrue(authorized.recipient_token)

    def test_onion_invitation_is_v3_and_never_contains_direct_fallback(self):
        onion = "a" * 56 + ".onion"
        encoded = PeerInvitation("Private", "hidden.invalid", 22022, KEY, transport="tor", onion_address=onion).encode()
        decoded = PeerInvitation.decode(encoded)
        self.assertEqual(decoded.transport, "tor")
        self.assertEqual(decoded.onion_address, onion)
        with self.assertRaises(PeerError):
            PeerInvitation.decode(json.dumps({**json.loads(encoded), "onion_address": "invalid.onion"}))

    def test_tor_only_share_fails_closed_when_tor_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Private", str(folder), "", 22022, authorized_peers=[AuthorizedPeer("Laptop", KEY)], transport_policy=PeerTransportPolicy.TOR_ONLY, onion_enabled=False)
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary, "XDG_DATA_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"):
                manager = PeerManager(root=Path(temporary) / "peer")
                with self.assertRaisesRegex(PeerError, "Tor-only"):
                    manager.start(share)

    def test_tor_only_server_binds_only_to_loopback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Private", str(folder), "", 22022, authorized_peers=[AuthorizedPeer("Laptop", KEY)], transport_policy=PeerTransportPolicy.TOR_ONLY, onion_enabled=True, id="private")
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8"); host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            process = MagicMock(); process.poll.return_value = None
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary, "XDG_DATA_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch("tuxindrive.peer.subprocess.Popen", return_value=process) as popen, patch.object(PeerManager(root=root).tor.__class__, "start", return_value="a" * 56 + ".onion"):
                manager = PeerManager(root=root); manager.start(share); manager._servers.clear()
            command = popen.call_args.args[0]
            self.assertEqual(command[command.index("--addr") + 1], "127.0.0.1:22022")

    def test_role_and_one_time_drop_scope_round_trip(self):
        encoded = PeerInvitation(
            "Drop", "198.51.100.20", 22022, KEY,
            role=PeerRole.SEND_ONLY,
            remote_path=".tuxdrive-drops/drop-1",
            one_time_drop_id="drop-1",
            expires_at="2999-01-01T00:00:00+00:00",
        ).encode()
        decoded = PeerInvitation.decode(encoded)
        decoded.assert_usable()
        self.assertEqual(decoded.role, PeerRole.SEND_ONLY)
        self.assertEqual(decoded.remote_path, ".tuxdrive-drops/drop-1")
        self.assertEqual(decoded.one_time_drop_id, "drop-1")

    def test_expired_file_drop_is_rejected(self):
        invitation = PeerInvitation(
            "Old drop", "198.51.100.20", 22022, KEY,
            role=PeerRole.SEND_ONLY, expires_at="2000-01-01T00:00:00+00:00",
        )
        with self.assertRaises(PeerError):
            invitation.assert_usable()

    def test_one_time_drop_invitation_uses_dedicated_server_root(self):
        from tuxindrive.models import OneTimeDrop
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Drop host", str(folder), "192.0.2.10", 22022, authorized_peers=[AuthorizedPeer("Owner peer", KEY)], id="drop-host")
            drop = OneTimeDrop("Sender", KEY, ".tuxdrive-drops/drop-id", "2999-01-01T00:00:00+00:00")
            share.one_time_drops.append(drop)
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            invitation = PeerInvitation.decode(PeerManager(root=root).one_time_invitation(share, drop))
            self.assertEqual(invitation.remote_path, "")
            self.assertNotEqual(invitation.port, share.authorized_peers[0].server_port)

    def test_invitation_preserves_optional_no_storage_relay(self):
        encoded = PeerInvitation(
            "Project", "198.51.100.20", 22022, KEY,
            relay_host="relay.example.net", relay_port=32022,
        ).encode()
        decoded = PeerInvitation.decode(encoded)
        self.assertEqual(decoded.relay_host, "relay.example.net")
        self.assertEqual(decoded.relay_port, 32022)

    def test_peer_applies_verified_changed_block_transaction_atomically(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "project.bin"
            target.write_bytes(b"A" * 8 + b"B" * 8)
            transaction = root / ".tuxdrive-delta" / "tx1"
            blocks = transaction / "blocks"
            blocks.mkdir(parents=True)
            replacement = b"X" * 8
            (blocks / "0000000000000008.block").write_bytes(replacement)
            expected = b"A" * 8 + replacement
            instruction = {
                "version": 1, "path": "project.bin", "size": len(expected),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "blocks": [{
                    "offset": 8, "size": 8,
                    "digest": hashlib.blake2b(replacement, digest_size=32).hexdigest(),
                }],
            }
            private = Ed25519PrivateKey.generate()
            private_path = root / "identity"
            private_path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            signer, signature = sign_json(instruction, private_path)
            (transaction / "instruction.json").write_text(json.dumps({**instruction, "signer": signer, "signature": signature}), encoding="utf-8")
            PeerManager._apply_delta_transaction(root, transaction, [signer])
            self.assertEqual(target.read_bytes(), expected)
            self.assertFalse(transaction.exists())

    def test_peer_applies_verified_changed_block_transaction_on_windows(self):
        import hashlib
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.peer.platform.system", return_value="Windows"
        ), patch("tuxindrive.security.platform.system", return_value="Windows"):
            root = Path(temporary)
            target = root / "project.bin"
            target.write_bytes(b"A" * 8 + b"B" * 8)
            transaction = root / ".tuxdrive-delta" / "tx1"
            blocks = transaction / "blocks"
            blocks.mkdir(parents=True)
            replacement = b"X" * 8
            (blocks / "0000000000000008.block").write_bytes(replacement)
            expected = b"A" * 8 + replacement
            instruction = {
                "version": 1, "path": "project.bin", "size": len(expected),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "blocks": [{
                    "offset": 8, "size": 8,
                    "digest": hashlib.blake2b(replacement, digest_size=32).hexdigest(),
                }],
            }
            private = Ed25519PrivateKey.generate()
            private_path = root / "identity"
            private_path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            signer, signature = sign_json(instruction, private_path)
            (transaction / "instruction.json").write_text(json.dumps({**instruction, "signer": signer, "signature": signature}), encoding="utf-8")
            PeerManager._apply_delta_transaction(root, transaction, [signer])
            self.assertEqual(target.read_bytes(), expected)
            self.assertFalse(transaction.exists())

    def test_legacy_invitation_and_share_configuration_remain_compatible(self):
        legacy = json.dumps({"tuxdrive_peer": 1, "name": "Old", "host": "192.0.2.5", "port": 22022, "host_key": KEY})
        self.assertEqual(PeerInvitation.decode(legacy).name, "Old")
        share = PeerShare.from_dict({"name": "Old", "local_path": "/tmp", "advertised_host": "192.0.2.5", "allowed_peer_key": KEY})
        self.assertEqual(share.active_peer_keys, [KEY])
        self.assertEqual(share.authorized_peers[0].name, "Legacy peer")

    def test_discovered_peer_requires_same_pinned_fingerprint(self):
        peer = DiscoveredPeer(
            "Team", "192.0.2.8", 22022, KEY, "share-1", 15,
            role=PeerRole.READ_ONLY,
        )
        self.assertEqual(peer.fingerprint, key_fingerprint(KEY))
        self.assertEqual(peer.invitation().lease_minutes, 15)
        self.assertEqual(peer.invitation().role, PeerRole.READ_ONLY)

    def test_tor_only_share_is_never_announced_on_lan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare(
                "Private", str(folder), "", 22022,
                authorized_peers=[AuthorizedPeer("Alice", KEY)], id="private",
                transport_policy=PeerTransportPolicy.TOR_ONLY, onion_enabled=True,
            )
            manager = PeerManager(root=root)
            manager._advertised_shares[share.id] = share
            self.assertEqual(manager._discovery_invitations(), [])

    def test_public_key_rejects_authorized_keys_options_and_multiline_input(self):
        self.assertEqual(normalize_public_key(KEY + " laptop"), KEY)
        with self.assertRaises(PeerError):
            normalize_public_key('command="bad" ' + KEY)
        with self.assertRaises(PeerError):
            normalize_public_key(KEY + "\n" + KEY)

    def test_privileged_peer_port_is_rejected(self):
        with self.assertRaises(PeerError):
            validate_port(22)

    def test_router_port_mapping_is_opt_in(self):
        share = PeerShare("Project", "/data/project", "192.0.2.10")
        self.assertFalse(share.nat_traversal)

    def test_server_uses_authorized_peer_key_and_explicit_host_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            folder = Path(temporary) / "shared"
            folder.mkdir()
            share = PeerShare("Project", str(folder), "192.0.2.10", 22022, KEY, id="share1")
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            process = MagicMock()
            process.poll.return_value = None
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}), patch(
                "tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"
            ), patch(
                "tuxindrive.peer.subprocess.Popen", return_value=process
            ) as popen:
                manager = PeerManager(root=root)
                manager.start(share)
                command = popen.call_args.args[0]
                manager._servers.clear()  # prevent teardown signals against the mock
            self.assertEqual(command[:4], ["/usr/bin/rclone", "serve", "sftp", f":local:{folder}"])
            self.assertIn("--authorized-keys", command)
            self.assertEqual(command[command.index("--key") + 1], str(host))
            authorized = root / "authorized" / "share1-0.keys"
            self.assertEqual(authorized.read_text(encoding="utf-8").strip(), KEY)

    def test_server_authorizes_multiple_named_devices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            folder = Path(temporary) / "shared"
            folder.mkdir()
            second = "ssh-ed25519 QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
            share = PeerShare("Team", str(folder), "192.0.2.10", 22022, authorized_peers=[AuthorizedPeer("Laptop", KEY), AuthorizedPeer("Desktop", second)], id="multi")
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            process = MagicMock()
            process.poll.return_value = None
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch("tuxindrive.peer.subprocess.Popen", return_value=process):
                manager = PeerManager(root=root)
                manager.start(share)
                manager._servers.clear()
            key_files = sorted((root / "authorized").glob("multi-*.keys"))
            self.assertEqual(len(key_files), 2)
            self.assertEqual({path.read_text(encoding="utf-8").strip() for path in key_files}, {KEY, second})

    def test_server_enforces_per_device_roles_and_roots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root, folder = Path(temporary) / "peer", Path(temporary) / "shared"
            folder.mkdir()
            second = "ssh-ed25519 QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="
            share = PeerShare(
                "Team", str(folder), "192.0.2.10", 22022,
                authorized_peers=[
                    AuthorizedPeer("Reader", KEY, role=PeerRole.READ_ONLY),
                    AuthorizedPeer("Sender", second, role=PeerRole.SEND_ONLY),
                ], id="roles",
            )
            host = root / "hosts" / share.id
            host.parent.mkdir(parents=True)
            host.write_text("private", encoding="utf-8")
            host.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            processes = [MagicMock(), MagicMock()]
            for process in processes:
                process.poll.return_value = None
            with patch.dict(os.environ, {"XDG_CACHE_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch("tuxindrive.peer.subprocess.Popen", side_effect=processes) as popen:
                manager = PeerManager(root=root)
                manager.start(share)
                manager._servers.clear()
            commands = [call.args[0] for call in popen.call_args_list]
            self.assertIn("--read-only", commands[0])
            self.assertNotIn("--read-only", commands[1])
            self.assertEqual(commands[0][3], f":local:{folder}")
            self.assertIn(".tuxdrive-peer-inboxes", commands[1][3])
            self.assertNotEqual(commands[0][commands[0].index("--addr") + 1], commands[1][commands[1].index("--addr") + 1])

    def test_foreign_unexpired_lease_blocks_acquisition(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = PeerLeaseManager(root=Path(temporary))
            manager._owner = "this-device"
            job = SyncJob("peer", temporary, peer_leases=True)
            foreign = FileLease("draft.odt", "other-device", "token", "2999-01-01T00:00:00+00:00")
            with patch.object(manager, "read", return_value=foreign):
                with self.assertRaises(PeerError):
                    manager.acquire(job, "draft.odt")

    def test_client_configuration_pins_host_and_uses_private_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            root.mkdir()
            private = root / "identity_ed25519"
            private.write_text("private", encoding="utf-8")
            private.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            invitation = PeerInvitation("Project", "203.0.113.4", 22022, KEY)
            with patch.dict(os.environ, {"XDG_DATA_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch(
                "tuxindrive.peer.subprocess.run",
                return_value=MagicMock(returncode=0, stdout="", stderr=""),
            ) as run:
                PeerManager(root=root).configure_connection("peer-project", invitation)
            command = run.call_args.args[0]
            self.assertIn("key_file", command)
            self.assertEqual(command[command.index("key_file") + 1], str(private))
            self.assertEqual(command[command.index("host_keys") + 1], KEY)

    def test_onion_connection_configures_only_onion_endpoint(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "peer"
            root.mkdir()
            private = root / "identity_ed25519"
            private.write_text("private", encoding="utf-8")
            private.with_suffix(".pub").write_text(KEY, encoding="utf-8")
            onion = "a" * 56 + ".onion"
            invitation = PeerInvitation("Private", onion, 22, KEY, transport="tor", onion_address=onion, onion_client_auth="A" * 52)
            with patch.dict(os.environ, {"XDG_DATA_HOME": temporary}), patch("tuxindrive.peer.resolve_rclone", return_value="/usr/bin/rclone"), patch(
                "tuxindrive.peer.shutil.which", side_effect=lambda value: f"/usr/bin/{value}"
            ), patch("tuxindrive.peer.subprocess.run", return_value=MagicMock(returncode=0, stdout="", stderr="")) as run, patch.object(
                PeerManager(root=root).tor.__class__, "install_client_credential"
            ), patch.object(
                PeerManager(root=root).tor.__class__, "start_client", return_value=root / "tor" / "torsocks.conf"
            ):
                manager = PeerManager(root=root)
                manager.configure_connection("peer-private", invitation)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("host") + 1], onion)
            self.assertNotIn("198.51.100.1", command)
            self.assertIn("ssh", command)


if __name__ == "__main__":
    unittest.main()
