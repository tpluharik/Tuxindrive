from tests import signal_safety as _signal_safety  # noqa: F401

import unittest
import json
from subprocess import CompletedProcess
from unittest.mock import Mock

from tuxindrive.capabilities import CAPABILITIES, capabilities_for
from tuxindrive.models import Account, Provider, SyncMode
from tuxindrive.provider_probe import ProviderCapabilityProbe


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

    def test_runtime_probe_is_bounded_cached_and_never_expands_declared_features(self):
        runner = Mock(return_value=CompletedProcess(
            [], 0, json.dumps({"Hashes": ["MD5"], "Features": {
                "Move": True, "Copy": True, "ChangeNotify": True,
            }}), "",
        ))
        account = Account("drive", Provider.GOOGLE_DRIVE, "Drive")
        probe = ProviderCapabilityProbe(runner=runner)
        first = probe.probe(account, now=100)
        second = probe.probe(account, now=101)
        self.assertTrue(first.verified)
        self.assertTrue(first.hashes)
        self.assertIs(first, second)
        self.assertEqual(runner.call_count, 1)
        self.assertEqual(runner.call_args.kwargs["timeout"], 15)

    def test_failed_runtime_probe_falls_back_to_conservative_declaration(self):
        runner = Mock(return_value=CompletedProcess([], 1, "", "authentication failed token=secret"))
        account = Account("drive", Provider.GOOGLE_DRIVE, "Drive")
        result = ProviderCapabilityProbe(runner=runner).probe(account)
        self.assertFalse(result.verified)
        self.assertNotIn("secret", result.detail)
