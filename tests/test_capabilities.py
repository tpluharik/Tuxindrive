import unittest

from tuxindrive.capabilities import CAPABILITIES, capabilities_for
from tuxindrive.models import Provider, SyncMode


class ProviderCapabilityTests(unittest.TestCase):
    def test_every_provider_has_an_explicit_capability_record(self):
        self.assertEqual(set(CAPABILITIES), set(Provider))

    def test_adaptive_modes_hide_peer_streaming(self):
        self.assertFalse(capabilities_for(Provider.PEER).supports_mode(SyncMode.VIRTUAL_DRIVE))
        self.assertTrue(capabilities_for(Provider.GOOGLE_DRIVE).supports_mode(SyncMode.VIRTUAL_DRIVE))

    def test_proton_limits_unsafe_ui_actions(self):
        proton = capabilities_for(Provider.PROTON_DRIVE)
        self.assertTrue(proton.browser_oauth)
        self.assertFalse(proton.streaming)
        self.assertFalse(proton.share_links)
        self.assertFalse(proton.hashes)

    def test_protocol_backends_have_conservative_share_capabilities(self):
        self.assertTrue(capabilities_for(Provider.S3).share_links)
        self.assertFalse(capabilities_for(Provider.WEBDAV).share_links)
        self.assertFalse(capabilities_for(Provider.SFTP).share_links)
