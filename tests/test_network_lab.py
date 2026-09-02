import json
import tempfile
import unittest
from pathlib import Path

from tuxindrive.network_lab import LAB_RELEASE_CHANNEL, NetworkLabRunner


class NetworkLabTests(unittest.TestCase):
    def test_complete_loopback_scenario_run_uses_fictional_data(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = NetworkLabRunner(Path(folder) / "results")
            results = runner.run()
            self.assertEqual(len(results), len(runner.SCENARIOS))
            self.assertEqual(len(results), 19)
            self.assertTrue(all(result.status == "passed" for result in results), results)
            names = {result.name for result in results}
            self.assertIn("Two-client collaboration workflow", names)
            self.assertIn("Tenant quota rejection and continued health", names)
            self.assertIn("Read-only MCP protocol boundary", names)
            self.assertIn("Multi-address loopback traffic", names)
            summary = json.loads(runner.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["release_channel"], LAB_RELEASE_CHANNEL)
            self.assertTrue(summary["fictional_data_only"])
            self.assertFalse(summary["external_network_used"])
            self.assertEqual(summary["loopback_connections"], 2)
            self.assertGreater(summary["loopback_bytes"], 256 * 1024)
            self.assertEqual(summary["loopback_sources"], ["127.0.0.2", "127.0.0.3"])
            self.assertEqual(runner.summary_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(runner.log_path.stat().st_mode & 0o777, 0o600)
            combined = runner.log_path.read_text(encoding="utf-8") + runner.jsonl_path.read_text(encoding="utf-8")
            self.assertNotIn(str(Path.home()), combined)

    def test_cancel_stops_before_next_scenario_and_still_writes_summary(self):
        import threading
        with tempfile.TemporaryDirectory() as folder:
            cancel = threading.Event(); cancel.set()
            runner = NetworkLabRunner(Path(folder) / "results")
            results = runner.run(cancel=cancel)
            self.assertEqual(results[0].status, "cancelled")
            self.assertTrue(runner.summary_path.is_file())

    def test_package_and_release_are_separate_from_product_channel(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/network-lab-release.yml").read_text(encoding="utf-8")
        build = (root / "scripts/build-network-lab-deb.sh").read_text(encoding="utf-8")
        control = (root / "packaging/network-lab/DEBIAN/control").read_text(encoding="utf-8")
        self.assertIn('tags: ["network-lab-v*"]', workflow)
        self.assertIn("+lab", build)
        self.assertIn("TUXINDRIVE_LAB_REVISION:-5", build)
        self.assertIn("Package: tuxindrive-network-lab", control)
        self.assertIn("Version: 0.26.31+lab5", control)
        self.assertNotIn("tuxindrive-network-lab", (root / ".github/workflows/platform-packages.yml").read_text(encoding="utf-8"))

    def test_gui_reports_scenario_progress_without_blocking_the_window(self):
        root = Path(__file__).resolve().parents[1]
        gui = (root / "src/tuxindrive/network_lab_gui.py").read_text(encoding="utf-8")
        self.assertIn("Gtk.ProgressBar()", gui)
        self.assertIn("self.progress.set_fraction", gui)
        self.assertIn("self.completed_scenarios", gui)
        self.assertIn("threading.Thread(target=self._worker, daemon=True)", gui)
        self.assertIn("window.show_all()", gui)
        self.assertIn("Gtk.DrawingArea()", gui)
        self.assertIn("127.0.0.2", gui)
        self.assertIn("127.0.0.3", gui)
        self.assertIn("pace_seconds=0.35", gui)


if __name__ == "__main__":
    unittest.main()
