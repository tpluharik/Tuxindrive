import json
import tempfile
import unittest
from pathlib import Path

from tuxindrive.managed_policy import load_managed_policy
from tuxindrive.models import AppSettings, Provider


class ManagedPolicyTests(unittest.TestCase):
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
