from tests import signal_safety as _signal_safety  # noqa: F401

import json
import tempfile
import unittest
from pathlib import Path

from tuxindrive.managed_policy import ManagedPolicy, load_managed_policy
from tuxindrive.mail_auth import MailProvider
from tuxindrive.models import AppSettings, Provider


class ManagedPolicyTests(unittest.TestCase):
    def test_mail_allowlist_does_not_expand_existing_drive_policy(self):
        self.assertTrue(ManagedPolicy().mail_provider_allowed(MailProvider.GMAIL))
        restricted = ManagedPolicy(allowed_providers=(Provider.GOOGLE_DRIVE,))
        self.assertFalse(restricted.mail_provider_allowed(MailProvider.GMAIL))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            path.write_text(json.dumps({"allowed_providers": ["google_drive"],
                                       "allowed_mail_providers": ["microsoft365"]}))
            policy = load_managed_policy(path, require_root=False)
            self.assertTrue(policy.mail_provider_allowed("microsoft365"))
            self.assertFalse(policy.mail_provider_allowed("gmail"))
            path.write_text('{"allowed_mail_providers": []}')
            self.assertFalse(load_managed_policy(path, require_root=False).mail_provider_allowed("gmail"))
            for value in ('{"allowed_mail_providers": "gmail"}', '{"allowed_mail_providers": ["unknown"]}'):
                path.write_text(value)
                with self.assertRaises(RuntimeError):
                    load_managed_policy(path, require_root=False)

    def test_policy_constrains_features_and_bandwidth(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            path.write_text(json.dumps({
                "schema": 1,
                "allowed_providers": ["google_drive", "onedrive"],
                "global_bandwidth_ceiling": "2M:4M",
                "minimum_headroom_percent": 30,
                "allow_content_indexing": False,
                "allow_cloud_to_cloud": False,
            }), encoding="utf-8")
            policy = load_managed_policy(path, require_root=False)
        settings = AppSettings(global_bandwidth_limit="10M", bandwidth_headroom_percent=20, search_content_indexing=True)
        policy.apply(settings)
        self.assertTrue(policy.provider_allowed(Provider.ONEDRIVE))
        self.assertFalse(policy.provider_allowed(Provider.DROPBOX))
        self.assertEqual(settings.global_bandwidth_limit, "2M:4M")
        self.assertEqual(settings.bandwidth_headroom_percent, 30)
        self.assertFalse(settings.search_content_indexing)

    def test_symlinked_policy_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "real.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "policy.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symbolic"):
                load_managed_policy(link, require_root=False)
