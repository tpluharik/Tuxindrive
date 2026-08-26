import json
import tempfile
import unittest
from pathlib import Path

from tuxindrive.reliability import run_scenarios


class ReliabilityTests(unittest.TestCase):
    def test_matrix_records_every_scenario_and_failure(self):
        def failure():
            raise RuntimeError("offline")

        report = run_scenarios((("ok", lambda: "ready"), ("failure", failure)))
        self.assertFalse(report.success)
        self.assertEqual([item.name for item in report.results], ["ok", "failure"])
        self.assertIn("offline", report.results[1].detail)

    def test_report_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "report.json"
            report = run_scenarios((("ok", lambda: None),))
            report.write(target)
            saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema"], 1)
        self.assertTrue(saved["success"])
