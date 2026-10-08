"""Opt-in real GTK mail controls, synthetic data only, isolated display required."""
from tests import signal_safety as _signal_safety  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tuxindrive.mail_auth import MailAccountStore
from tuxindrive.mail_index import MailSearchIndex
from tuxindrive.search_index import FolderSearchIndex
from tests.test_mail_attachments import GMAIL, SyntheticClient


@unittest.skipUnless(os.environ.get("TUXINDRIVE_GTK_TESTS") == "1", "Requires an isolated GTK display")
class MailGtkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {
            f"XDG_{kind}_HOME": f"{cls.temporary.name}/{kind.lower()}"
            for kind in ("CONFIG", "CACHE", "DATA", "STATE")
        })
        cls.environment.start()
        with patch("platform.platform", return_value="isolated synthetic mail GUI"):
            from tuxindrive import app
        cls.app = app
        app.Gtk.init([])

    @classmethod
    def tearDownClass(cls):
        cls.environment.stop()
        cls.temporary.cleanup()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.controller = SimpleNamespace(
            config=SimpleNamespace(settings=SimpleNamespace(search_content_indexing=False)),
            managed_policy=SimpleNamespace(allow_content_indexing=True),
            mail_accounts=MailAccountStore(root / "mail-accounts.json"),
            mail_search_index=MailSearchIndex(root / "mail.sqlite3"),
            search_index=FolderSearchIndex(root / "files.sqlite3"),
            mail_authorization=Mock(), bandwidth=None,
        )
        self.controller.mail_accounts.save([GMAIL])
        self.dialogs = []
        self.addCleanup(lambda: [dialog.destroy() for dialog in reversed(self.dialogs)])

    def manager(self):
        dialog = self.app.MailAccountsDialog(None, self.controller)
        self.dialogs.append(dialog)
        return dialog

    def test_provider_dialogs_construct_without_browser_or_token_access(self):
        with patch.object(self.app, "authorize_mail") as authorize:
            for provider in ("gmail", "microsoft365"):
                dialog = self.app.MailConnectDialog(None, self.controller, provider, Mock())
                self.dialogs.append(dialog)
                self.assertFalse(dialog._busy)
                self.assertFalse(dialog.browser_link.get_visible())
            authorize.assert_not_called()
        self.controller.mail_authorization.store.assert_not_called()

    def test_refresh_applies_visible_options_and_searches_synthetic_contents(self):
        dialog = self.manager()
        dialog.contents.set_active(True)
        dialog.days.set_value(30)
        dialog.limit.set_value(10)
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "MailClient", return_value=SyntheticClient()), \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._refresh()
        saved = self.controller.mail_accounts.load()[0]
        self.assertEqual((saved.days, saved.max_messages, saved.include_content), (30, 10, True))
        self.assertEqual(len(self.controller.mail_search_index.search("needle")), 1)
        self.assertIn("Indexed 1 attachments", dialog.status.get_text())
        dialog.contents.set_active(False)
        dialog._save_options()
        self.assertEqual(self.controller.mail_search_index.search("needle"), [])

    def test_mail_result_opens_message_without_local_materialization(self):
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient())
        dialog = self.app.FolderSearchDialog(None, self.controller)
        self.dialogs.append(dialog)
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog.search_entry.set_text("invoice")
            dialog.scope.set_active_id("mail")
            dialog._run_search()
        self.assertEqual(len(dialog._results), 1)
        dialog.view.get_selection().select_path(self.app.Gtk.TreePath.new_from_indices([0]))
        with patch.object(self.app.webbrowser, "open", return_value=True) as browser:
            dialog._open_selected()
            browser.assert_called_once_with(dialog._results[0].attachment.message_url)
        dialog._open_selected_local_location()
        self.assertIn("not retained", dialog.status.get_text())


if __name__ == "__main__":
    unittest.main()
