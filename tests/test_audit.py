import os
import tempfile
import unittest
import csv
import json
from pathlib import Path

from tuxindrive.audit import AuditTimeline


class AuditTimelineTests(unittest.TestCase):
    def test_private_timeline_records_and_filters_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            timeline = AuditTimeline(path)
            timeline.record("sync", "started", "running", job_id="one")
            timeline.record("peer", "drop received", "success", job_id="two", peer="Laptop", path="inbox/a.txt")
            self.assertEqual(timeline.recent(10, job_id="two")[0].peer, "Laptop")
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_malformed_history_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "audit.jsonl"
            path.write_text("not json\n", encoding="utf-8")
            self.assertEqual(AuditTimeline(path).recent(), [])

    def test_exports_csv_and_jsonl_as_private_operator_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            timeline = AuditTimeline(root / "audit.jsonl")
            timeline.record("sync", "completed", "success", job_id="one", detail="ok")
            csv_path = root / "export.csv"
            json_path = root / "export.jsonl"
            self.assertEqual(timeline.export(csv_path), 1)
            self.assertEqual(timeline.export(json_path, format="jsonl"), 1)
            with csv_path.open(encoding="utf-8") as handle:
                self.assertEqual(list(csv.DictReader(handle))[0]["job_id"], "one")
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["outcome"], "success")
            if os.name != "nt":
                self.assertEqual(csv_path.stat().st_mode & 0o777, 0o600)
