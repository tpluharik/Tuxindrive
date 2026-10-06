"""Opt-in real GTK menu checks: TUXINDRIVE_GTK_TESTS=1 xvfb-run ..."""

import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tuxindrive.models import SyncJob
from tuxindrive.tray import MAX_VISIBLE_TRAY_ALERTS, TrayIconModel


@unittest.skipUnless(os.environ.get("TUXINDRIVE_GTK_TESTS") == "1", "Requires an isolated GTK display")
class TrayMenuGtkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {
            f"XDG_{kind}_HOME": f"{cls.temporary.name}/{kind.lower()}"
            for kind in ("CONFIG", "CACHE", "DATA", "STATE")
        })
        cls.environment.start()
        from tuxindrive import app
        cls.app = app
        app.Gtk.init([])

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temporary.cleanup()

    def setUp(self):
        self.jobs = [SyncJob("cloud", f"/tmp/folder-{i}", name=f"Folder {i}",
                             last_error=f"Access denied {i}") for i in range(7)]
        self.menus = [self.app.Gtk.Menu(), self.app.Gtk.Menu()]
        for menu in self.menus:
            menu.append(self.app.Gtk.MenuItem(label="Open TuxInDrive"))
        self.controller = SimpleNamespace(
            config=SimpleNamespace(jobs=self.jobs), _tray_runtime_error="",
            _tray_icon=TrayIconModel(state="error"), _tray_menu_signature=None,
            _tray_menu_sections=[(menu, []) for menu in self.menus],
            _open_tray_alert=Mock(), _refresh_tray_from_jobs=Mock(),
            activate=Mock(), window=Mock(), background=True,
        )

    def tearDown(self):
        for menu in self.menus:
            menu.destroy()

    def refresh(self):
        self.app.TuxInDriveApplication._refresh_tray_menus(self.controller)

    def test_both_real_menus_show_summaries_overflow_and_correct_activation(self):
        self.refresh()
        for menu in self.menus:
            children = menu.get_children()
            self.assertEqual(children[0].get_label(), "Needs attention (7)")
            self.assertFalse(children[0].get_sensitive())
            self.assertEqual(children[1].get_label(), "Folder 0 — Access denied 0")
            more = children[MAX_VISIBLE_TRAY_ALERTS + 1]
            self.assertEqual(more.get_label(), "More alerts (2)")
            remaining = more.get_submenu().get_children()
            remaining[1].activate()
            self.controller._open_tray_alert.assert_called_with(remaining[1], self.jobs[6].id)
            self.assertEqual(children[-1].get_label(), "Open TuxInDrive")

    def test_rename_resolution_and_cached_refresh_leave_no_stale_menu_items(self):
        self.refresh()
        old = self.menus[0].get_children()[1]
        self.refresh()
        self.assertEqual(self.menus[0].get_children()[1], old)
        self.jobs[0].name = "Renamed folder"
        self.refresh()
        self.assertIn("Renamed folder", self.menus[0].get_children()[1].get_label())
        for job in self.jobs:
            job.last_error = ""
        self.controller._tray_icon.set_state("ready")
        self.refresh()
        for menu in self.menus:
            self.assertEqual([child.get_label() for child in menu.get_children()],
                             ["No outstanding alerts", "", "Open TuxInDrive"])

    def test_alert_opens_the_selected_job_details_and_ignores_a_resolved_row(self):
        selected = self.jobs[4]
        with patch.object(self.app, "ErrorDetailsDialog") as dialog:
            self.app.TuxInDriveApplication._open_tray_alert(self.controller, None, selected.id)
            dialog.assert_called_once_with(self.controller.window, selected)
            self.controller.activate.assert_called_once()
            selected.last_error = ""
            self.app.TuxInDriveApplication._open_tray_alert(self.controller, None, selected.id)
            dialog.assert_called_once()
            self.controller._refresh_tray_from_jobs.assert_called_once()

    def test_runtime_failure_is_visible_without_a_sync_job(self):
        self.controller.config.jobs = []
        self.controller._tray_runtime_error = "Runtime preparation failed: engine unavailable"
        self.refresh()
        self.assertIn("engine unavailable", self.menus[1].get_children()[1].get_label())
        self.app.TuxInDriveApplication._open_tray_alert(self.controller, None, None)
        self.controller.window.message.assert_called_once_with(
            self.controller._tray_runtime_error, self.app.Gtk.MessageType.ERROR
        )


if __name__ == "__main__":
    unittest.main()
