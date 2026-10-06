import unittest

from tuxindrive.models import SyncJob
from tuxindrive.tray import (
    SYNC_ANIMATION_ICONS, TrayAlert, TrayIconModel, alerts_for_jobs,
    compact_tray_text, tray_state_for_jobs,
)


class TrayIconModelTests(unittest.TestCase):
    def test_ready_and_error_have_stable_accessible_presentations(self):
        model = TrayIconModel()
        self.assertEqual(model.icon_name, "tuxindrive")
        self.assertFalse(model.animated)
        self.assertFalse(model.attention)

        model.set_state("error", "Cloud login expired")
        self.assertEqual(model.icon_name, "tuxindrive-error")
        self.assertTrue(model.attention)
        self.assertIn("Cloud login expired", model.accessible_label)

    def test_sync_animation_advances_and_wraps_all_packaged_frames(self):
        model = TrayIconModel()
        model.set_state("syncing", "Documents")
        observed = []
        for _ in SYNC_ANIMATION_ICONS:
            observed.append(model.icon_name)
            model.advance()
        self.assertEqual(tuple(observed), SYNC_ANIMATION_ICONS)
        self.assertEqual(model.icon_name, SYNC_ANIMATION_ICONS[0])

    def test_unknown_state_falls_back_to_ready(self):
        model = TrayIconModel(state="syncing", frame=4)
        model.set_state("unexpected")
        self.assertEqual(model.state, "ready")
        self.assertEqual(model.frame, 0)
        self.assertEqual(model.accessible_label, "TuxInDrive: ready")


class TrayAlertTests(unittest.TestCase):
    def test_menu_keeps_each_failed_folder_including_automatically_paused_jobs(self):
        failed = SyncJob("drive", "/tmp/cloud", name="Documents", last_error="Access denied")
        paused = SyncJob("backup", "/tmp/backup", name="Codex backup", enabled=False,
                         last_error="Automatic sync paused after 3 identical failures")
        healthy = SyncJob("other", "/tmp/healthy", name="Photos", last_status="Synchronized")
        alerts = alerts_for_jobs([healthy, failed, paused])
        self.assertEqual([alert.job_id for alert in alerts], [failed.id, paused.id])
        self.assertEqual(alerts[0].menu_label, "Documents — Access denied")

    def test_success_or_another_active_transfer_cannot_replace_an_unresolved_error(self):
        failed = SyncJob("drive", "/tmp/cloud", name="Documents", last_error="Login expired")
        active = SyncJob("other", "/tmp/other", name="Photos")
        state, detail = tray_state_for_jobs([failed, active], {active.id}, "Photos synchronized")
        self.assertEqual(state, "error")
        self.assertEqual(detail, "Documents — Login expired")

    def test_resolving_or_removing_last_error_restores_activity_then_ready_state(self):
        failed = SyncJob("drive", "/tmp/cloud", last_error="Access denied")
        failed.last_error = ""
        self.assertEqual(alerts_for_jobs([failed]), ())
        self.assertEqual(tray_state_for_jobs([failed], {failed.id}, "Documents"),
                         ("syncing", "Documents"))
        self.assertEqual(tray_state_for_jobs([], set()), ("ready", ""))

    def test_long_multiline_error_is_bounded_but_tooltip_keeps_redacted_details(self):
        reason = "Authorization: Bearer header-secret\n" + "Provider unavailable " * 30
        alert = TrayAlert("id", "Name_" * 20, reason)
        self.assertLessEqual(len(alert.menu_label), 153)
        self.assertNotIn("\n", alert.menu_label)
        self.assertNotIn("header-secret", alert.menu_label + alert.tooltip)
        self.assertIn("[redacted]", alert.tooltip)
        self.assertIn("…", alert.menu_label)
        self.assertGreater(len(alert.tooltip), len(alert.menu_label))
        self.assertNotIn("query-secret", compact_tray_text(
            "Failed: https://user:password@example.test/?access_token=query-secret"))

    def test_runtime_failure_has_its_own_summary_without_any_jobs(self):
        reason = "Runtime preparation failed: cloud engine not found"
        alert, = alerts_for_jobs([], reason)
        self.assertIsNone(alert.job_id)
        self.assertIn("cloud engine not found", alert.menu_label)
        self.assertEqual(tray_state_for_jobs([], set(), "Loaded", reason),
                         ("error", alert.menu_label))


if __name__ == "__main__":
    unittest.main()
