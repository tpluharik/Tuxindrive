from tests import signal_safety as _signal_safety  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxindrive.models import AuthorizedPeer, PeerShare, PeerTransportPolicy
from tuxindrive.tor import TorError, TorServiceManager, enforce_transport_policy


class TorTransportTests(unittest.TestCase):
    def test_client_authorization_is_private_and_revocable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = PeerShare("Private", temporary, "", onion_enabled=True, onion_client_auth=True, onion_address="a" * 56 + ".onion")
            peer = AuthorizedPeer("Alice laptop", "ssh-ed25519 QUJD")
            manager = TorServiceManager(root)
            credential = manager.issue_client_credential(share, peer)
            auth = root / "services" / share.id / "authorized_clients" / "Alice_laptop.auth"
            self.assertTrue(auth.is_file())
            self.assertEqual(auth.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(credential.private_key, auth.read_text(encoding="utf-8"))
            manager.revoke_client(share, peer)
            self.assertFalse(auth.exists())
            self.assertEqual(peer.onion_client_public_key, "")

    def test_client_secret_is_validated_and_stored_privately(self):
        with tempfile.TemporaryDirectory() as temporary:
            manager = TorServiceManager(Path(temporary))
            path = manager.install_client_credential("a" * 56 + ".onion", "A" * 52)
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
            file = next(path.iterdir())
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(TorError):
                manager.install_client_credential("bad.onion", "secret")

    def test_fail_closed_policy_rejects_forbidden_transport(self):
        share = PeerShare("Private", "/tmp", "", transport_policy=PeerTransportPolicy.TOR_ONLY)
        with self.assertRaisesRegex(TorError, "Tor"):
            enforce_transport_policy(share, "direct")
        enforce_transport_policy(share, "tor")
        share.no_relay = True
        share.transport_policy = PeerTransportPolicy.AUTO
        with self.assertRaisesRegex(TorError, "relays"):
            enforce_transport_policy(share, "relay")

    def test_bridge_secrets_do_not_reach_process_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            share = PeerShare("Private", temporary, "", onion_enabled=True, tor_bridge_lines=["obfs4 192.0.2.1:443 SECRET"])
            service = root / "services" / share.id
            service.mkdir(parents=True)
            (service / "hostname").write_text("a" * 56 + ".onion\n", encoding="ascii")
            process = MagicMock()
            process.poll.return_value = None
            with patch("tuxindrive.tor.shutil.which", return_value="/usr/bin/tor"), patch("tuxindrive.tor.subprocess.Popen", return_value=process) as popen:
                TorServiceManager(root).start(share, 22022)
            command = popen.call_args.args[0]
            self.assertNotIn("SECRET", " ".join(command))
            torrc = root / "instances" / share.id / "torrc"
            self.assertEqual(torrc.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
