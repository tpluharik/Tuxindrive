from tests import signal_safety as _signal_safety  # noqa: F401

import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock


os.environ.setdefault("XDG_STATE_HOME", "/tmp/tuxindrive-test-state")

try:
    from tuxindrive.app import Gtk, MainWindow  # noqa: E402
except SystemExit:
    # The generic Python CI lane intentionally has no GTK runtime. Desktop
    # packaging and platform lanes exercise the real GUI dependencies; keep
    # these focused lifecycle tests available wherever GTK can be imported.
    Gtk = None
    MainWindow = None


@unittest.skipUnless(MainWindow is not None, "GTK runtime is unavailable")
class UpdateDialogLifecycleTests(unittest.TestCase):
    def test_close_response_is_ignored_while_update_operation_is_active(self):
        window = SimpleNamespace(
            _pending_update=None,
            _update_operation_active=True,
            update_status=Mock(),
            _destroy_update_dialog=Mock(),
        )

        MainWindow._update_dialog_response(window, Mock(), Gtk.ResponseType.CANCEL)

        window._destroy_update_dialog.assert_not_called()
        window.update_status.set_text.assert_called_once()

    def test_late_download_callback_is_safe_after_window_shutdown(self):
        window = SimpleNamespace(
            update_dialog=None,
            update_progress=None,
            update_status=None,
            _update_operation_active=True,
        )

        self.assertFalse(MainWindow._update_downloaded(window, Mock(), None))
        self.assertFalse(window._update_operation_active)


if __name__ == "__main__":
    unittest.main()
