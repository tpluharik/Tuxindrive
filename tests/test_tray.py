import unittest

from tuxindrive.tray import SYNC_ANIMATION_ICONS, TrayIconModel


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


if __name__ == "__main__":
    unittest.main()
