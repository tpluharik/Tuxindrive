from tests import signal_safety as _signal_safety  # noqa: F401

import json
import unittest

from tuxindrive.control import _public_job_id, _resolve_job, status_document
from tuxindrive.models import Account, AppConfig, Provider, SyncJob


class ControlInterfaceTests(unittest.TestCase):
    def test_status_is_versioned_and_omits_names_and_paths(self):
        job = SyncJob("private-remote", "/home/alice/Confidential", name="Secret merger")
        config = AppConfig(
            accounts=[Account("private-remote", Provider.GOOGLE_DRIVE, "Personal")],
            jobs=[job],
        )
        payload = status_document(config)
        encoded = json.dumps(payload)
        self.assertEqual(payload["schema"], 1)
        self.assertIn(_public_job_id(job.id), encoded)
        self.assertNotIn("Secret merger", encoded)
        self.assertNotIn("/home/alice", encoded)
        self.assertNotIn("private-remote", encoded)

    def test_job_can_be_selected_by_public_identifier(self):
        job = SyncJob("cloud", "/data", id="private-id")
        config = AppConfig(jobs=[job])
        self.assertIs(_resolve_job(config, _public_job_id(job.id)), job)


if __name__ == "__main__":
    unittest.main()
