from tests import signal_safety as _signal_safety  # noqa: F401

import os
import tempfile
import unittest
import zipfile
import json
from pathlib import Path
from unittest.mock import patch

from tuxindrive.diagnostics import (
    application_log_path,
    crash_log_path,
    create_diagnostic_bundle,
    log_boot_failure,
)
from tuxindrive.models import Account, AppConfig, Provider, SyncJob


class DiagnosticsTests(unittest.TestCase):
    def test_boot_failure_is_persisted_before_gui_import(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ, {"XDG_STATE_HOME": temporary}
        ):
            log_boot_failure("GTK import failed for test")
            log = crash_log_path()
            self.assertTrue(log.exists())
            self.assertIn("GTK import failed for test", log.read_text(encoding="utf-8"))
            self.assertEqual(log.parent.stat().st_mode & 0o777, 0o700)

    def test_support_bundle_is_private_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {"XDG_STATE_HOME": temporary, "XDG_CACHE_HOME": temporary},
        ):
            application_log_path().parent.mkdir(parents=True)
            application_log_path().write_text(
                "token=very-secret /home/alice/private/report.txt\n", encoding="utf-8"
            )
            config = AppConfig(
                accounts=[Account("work", Provider.GOOGLE_DRIVE, "Personal account")],
                jobs=[SyncJob("work", "/home/alice/private", remote_path="Drive/Secret")],
            )
            target = create_diagnostic_bundle(config, Path(temporary) / "support")
            with zipfile.ZipFile(target) as archive:
                summary = json.loads(archive.read("summary.json"))
                combined = "\n".join(
                    archive.read(name).decode("utf-8")
                    for name in archive.namelist() if name.startswith("logs/")
                )
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertFalse(summary["privacy"]["paths_included"])
            self.assertNotIn("Personal account", json.dumps(summary))
            self.assertNotIn("/home/alice", combined)
            self.assertNotIn("very-secret", combined)


if __name__ == "__main__":
    unittest.main()
