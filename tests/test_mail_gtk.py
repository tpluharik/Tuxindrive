"""Opt-in real GTK mail controls, synthetic data only, isolated display required."""
from tests import signal_safety as _signal_safety  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from tuxindrive.mail_auth import MICROSOFT_MAIL_CLIENT_ID, MailAccountStore, MailError
from tuxindrive.managed_policy import ManagedPolicy
from tuxindrive.models import Account, AppConfig, Provider
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
            managed_policy=ManagedPolicy(),
            mail_accounts=MailAccountStore(root / "mail-accounts.json"),
            mail_search_index=MailSearchIndex(root / "mail.sqlite3"),
            search_index=FolderSearchIndex(root / "files.sqlite3"),
            mail_authorization=Mock(), bandwidth=None,
        )
        self.controller.mail_accounts.save([GMAIL])
        self.controller.mail_authorization.store.load.return_value = {"client_secret": "synthetic-app-secret"}
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
                self.assertEqual(dialog.client_id.get_text(),
                                 GMAIL.client_id if provider == "gmail" else MICROSOFT_MAIL_CLIENT_ID)
                self.assertEqual(dialog.client_secret.get_text(), "")
                self.assertTrue(dialog.client_id.get_editable())
                self.assertFalse(dialog.advanced.get_expanded())
                if provider == "gmail":
                    self.assertEqual(dialog.connect_button.get_label(), "Sign in with Google")
                    self.assertFalse(dialog.setup_link.get_visible())
            authorize.assert_not_called()
        self.controller.mail_authorization.store.load.assert_not_called()

    def test_google_first_setup_and_ambiguous_registrations_do_not_invent_a_default(self):
        for accounts in ([], [GMAIL, self.app.replace(GMAIL, id="c" * 32,
                                                   client_id="another.apps.googleusercontent.com")]):
            self.controller.mail_accounts.save(accounts)
            dialog = self.app.MailConnectDialog(None, self.controller, "gmail", Mock())
            self.dialogs.append(dialog)
            self.assertEqual(dialog.client_id.get_text(), "")
            self.assertTrue(dialog.advanced.get_expanded())
            self.assertTrue(dialog.setup_link.get_visible())
        self.controller.mail_authorization.store.load.assert_not_called()

    def test_google_browser_sign_in_reuses_only_app_settings_and_requires_new_consent(self):
        done = Mock()
        self.controller.mail_authorization.store.load.return_value = {
            "client_secret": "synthetic-desktop-secret", "refresh_token": "never-reuse",
            "access_token": "never-reuse-either",
        }
        dialog = self.app.MailConnectDialog(None, self.controller, "gmail", done)
        self.dialogs.append(dialog)
        self.assertEqual(dialog.email.get_text(), "")
        self.controller.mail_authorization.store.load.assert_not_called()
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "authorize_mail") as authorize, \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
        account = authorize.call_args.args[0]
        self.assertNotEqual(account.id, GMAIL.id)
        self.assertEqual(account.client_id, GMAIL.client_id)
        self.assertEqual(authorize.call_args.kwargs["client_secret"], "synthetic-desktop-secret")
        self.assertNotIn("never-reuse", repr(authorize.call_args))
        self.assertEqual(len(self.controller.mail_accounts.load()), 2)
        done.assert_called_once_with(account, index_after_connect=True)

    def test_custom_google_app_does_not_read_another_apps_native_credentials(self):
        dialog = self.app.MailConnectDialog(None, self.controller, "gmail", Mock())
        self.dialogs.append(dialog)
        dialog.client_id.set_text("custom.apps.googleusercontent.com")
        dialog.client_secret.set_text("custom-desktop-secret")
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "authorize_mail") as authorize, \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
        self.controller.mail_authorization.store.load.assert_not_called()
        self.assertEqual(authorize.call_args.kwargs["client_secret"], "custom-desktop-secret")

    def test_google_app_removed_or_changed_before_connect_fails_safely(self):
        for accounts in ([], [self.app.replace(GMAIL, client_id="changed.apps.googleusercontent.com")]):
            self.controller.mail_accounts.save([GMAIL])
            done = Mock()
            dialog = self.app.MailConnectDialog(None, self.controller, "gmail", done)
            self.dialogs.append(dialog)
            self.controller.mail_accounts.save(accounts)
            def synchronous(operation, ready):
                try:
                    result = operation()
                except MailError as error:
                    ready(None, error)
                else:
                    ready(result, None)
            with patch.object(self.app, "authorize_mail") as authorize, \
                    patch.object(self.app, "_run_thread", side_effect=synchronous):
                dialog._response(dialog, self.app.Gtk.ResponseType.OK)
            self.assertIn("settings changed", dialog.status.get_text())
            authorize.assert_not_called()
            done.assert_not_called()
            self.assertEqual(self.controller.mail_accounts.load(), accounts)
        self.controller.mail_authorization.store.load.assert_not_called()

    def test_google_native_settings_unavailable_or_invalid_do_not_start_authorization(self):
        for value in (None, {"client_secret": ["invalid"]}, {"client_secret": "invalid\nsecret"}):
            done = Mock()
            dialog = self.app.MailConnectDialog(None, self.controller, "gmail", done)
            self.dialogs.append(dialog)
            if value is None:
                self.controller.mail_authorization.store.load.side_effect = MailError("Unlock the native credential store.")
            else:
                self.controller.mail_authorization.store.load.side_effect = None
                self.controller.mail_authorization.store.load.return_value = value
            def synchronous(operation, ready):
                try:
                    result = operation()
                except MailError as error:
                    ready(None, error)
                else:
                    ready(result, None)
            with patch.object(self.app, "authorize_mail") as authorize, \
                    patch.object(self.app, "_run_thread", side_effect=synchronous):
                dialog._response(dialog, self.app.Gtk.ResponseType.OK)
            self.assertTrue(dialog.status.get_text())
            self.assertNotIn("invalid\nsecret", dialog.status.get_text())
            authorize.assert_not_called()
            done.assert_not_called()
            self.assertEqual(self.controller.mail_accounts.load(), [GMAIL])

    def test_custom_microsoft_client_is_used_after_explicit_connect(self):
        done = Mock()
        dialog = self.app.MailConnectDialog(None, self.controller, "microsoft365", done)
        self.dialogs.append(dialog)
        custom_id = "00000000-0000-0000-0000-000000000123"
        dialog.client_id.set_text(custom_id)
        dialog.tenant.set_text("organizations")
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "authorize_mail") as authorize, \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            authorize.assert_not_called()
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
            authorize.assert_called_once()
        account = authorize.call_args.args[0]
        self.assertEqual((account.client_id, account.tenant), (custom_id, "organizations"))
        self.assertEqual(authorize.call_args.kwargs["client_secret"], "")
        done.assert_called_once_with(account, index_after_connect=True)
        self.assertIn(account, self.controller.mail_accounts.load())

    def test_reconnect_keeps_id_options_index_and_uses_native_google_secret(self):
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient())
        self.controller.mail_authorization.store.load.return_value = {"client_secret": "synthetic-secret"}
        done = Mock()
        dialog = self.app.MailConnectDialog(None, self.controller, "gmail", done, existing=GMAIL)
        self.dialogs.append(dialog)
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "authorize_mail") as authorize, \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
        saved = self.controller.mail_accounts.load()
        self.assertEqual(saved, [GMAIL])
        self.assertEqual(self.controller.mail_search_index.count(GMAIL.id), 1)
        self.assertEqual(authorize.call_args.kwargs["client_secret"], "synthetic-secret")
        self.controller.mail_authorization.invalidate.assert_called_once_with(GMAIL)
        done.assert_called_once_with(GMAIL, index_after_connect=False)

    def test_connection_explicitly_offers_initial_metadata_scan_and_can_opt_out(self):
        done = Mock()
        dialog = self.app.MailConnectDialog(None, self.controller, "microsoft365", done)
        self.dialogs.append(dialog)
        self.assertTrue(dialog.index_after_connect.get_active())
        self.assertIn("not attachment contents", dialog.index_after_connect.get_tooltip_text())
        dialog.index_after_connect.set_active(False)
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "authorize_mail"), \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
        done.assert_called_once_with(self.controller.mail_accounts.load()[-1], index_after_connect=False)

    def test_connected_callback_starts_selected_mailbox_only_when_requested(self):
        main = SimpleNamespace(controller=self.controller, refresh=Mock(), message=Mock(), _index_mail_account=Mock())
        self.app.MainWindow._mail_connected(main, GMAIL, index_after_connect=False)
        main._index_mail_account.assert_not_called()
        self.app.MainWindow._mail_connected(main, GMAIL, index_after_connect=True)
        main._index_mail_account.assert_called_once_with(None, GMAIL)

    def test_direct_index_action_does_not_start_second_or_wrong_mailbox_scan(self):
        dialog = self.manager()
        main = SimpleNamespace(_mail_indexing=Mock(return_value=dialog))
        with patch.object(dialog, "_refresh") as refresh:
            self.app.MainWindow._index_mail_account(main, None, GMAIL)
            refresh.assert_called_once_with()
            refresh.reset_mock()
            dialog._busy = True
            self.app.MainWindow._index_mail_account(main, None, GMAIL)
            refresh.assert_not_called()
            dialog._busy = False
            other = self.app.replace(GMAIL, id="c" * 32)
            self.app.MainWindow._index_mail_account(main, None, other)
            refresh.assert_not_called()

    def test_not_indexed_is_distinct_from_successfully_empty_and_limited_scan(self):
        dialog = self.manager()
        self.assertIn("not indexed yet", dialog.status.get_text())
        self.assertIn("Not indexed yet", self.app._mail_account_card_markup(GMAIL, 0))
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient(items=[]))
        dialog._reload()
        self.assertIn("Scan complete", dialog.status.get_text())
        state = self.controller.mail_search_index.last_scan(GMAIL.id)
        self.assertIn("No attachments found", self.app._mail_account_card_markup(GMAIL, 0, state))
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient(items=[], complete=False))
        dialog._reload()
        self.assertIn("Scan limit reached", dialog.status.get_text())
        state = self.controller.mail_search_index.last_scan(GMAIL.id)
        self.assertIn("scan limit reached", self.app._mail_account_card_markup(GMAIL, 0, state))
        self.assertIn("Indexing attachments", self.app._mail_account_card_markup(GMAIL, 0, state, indexing=True))

    def test_failed_reconnect_retains_account_and_index(self):
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient())
        dialog = self.app.MailConnectDialog(None, self.controller, "gmail", Mock(), existing=GMAIL)
        self.dialogs.append(dialog)
        def synchronous(operation, ready):
            try:
                ready(operation(), None)
            except MailError as error:
                ready(None, error)
        with patch.object(self.app, "authorize_mail", side_effect=MailError("Consent declined")), \
                patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog._response(dialog, self.app.Gtk.ResponseType.OK)
        self.assertIn("Consent declined", dialog.status.get_text())
        self.assertEqual(self.controller.mail_accounts.load(), [GMAIL])
        self.assertEqual(self.controller.mail_search_index.count(), 1)
        dialog.done.assert_not_called()

    def test_main_sidebar_contains_existing_mail_account_without_drive_migration(self):
        controller = self.app.Gtk.Application(flags=self.app.Gio.ApplicationFlags.NON_UNIQUE)
        controller.register(None)
        controller.config = AppConfig()
        controller.config.accounts = [Account("drive-one", Provider.GOOGLE_DRIVE, "Drive")]
        controller.engine = SimpleNamespace(running_jobs=set(), mounted_jobs=set())
        for name in ("mail_accounts", "mail_search_index", "managed_policy"):
            setattr(controller, name, getattr(self.controller, name))
        with patch.object(self.app.MainWindow, "set_network_meter_enabled"), \
                patch.object(self.app.MainWindow, "set_activity_log_enabled"):
            window = self.app.MainWindow(controller)
        self.dialogs.append(window)
        self.assertEqual(len(window.account_list.get_children()), 2)
        self.assertEqual(window.summary_values["services"].get_text(), "2")
        label = window._account_widgets["mail:" + GMAIL.id]["label"].get_text()
        self.assertIn("Personal mail", label)
        self.assertIn("Gmail", label)
        self.assertEqual(controller.config.accounts[0].remote, "drive-one")
        self.assertEqual(len(controller.config.accounts), 1)
        self.assertEqual(controller.config.jobs, [])
        # Real menu controls carry mail-only actions, not rclone drive operations.
        row = window.account_list.get_children()[1]
        menu = next(child for child in row.get_child().get_children() if isinstance(child, self.app.Gtk.MenuButton))
        labels = [item.get_label() for item in menu.get_popup().get_children()]
        self.assertIn("Search attachments", labels)
        self.assertIn("Indexing options / refresh", labels)
        self.assertIn("Index attachments now", labels)
        self.assertEqual(window._account_widgets["mail:" + GMAIL.id]["index"].get_label(), "Index attachments")
        self.assertFalse(any("mount" in label.lower() or "sync now" in label.lower() for label in labels))
        changed = self.app.replace(GMAIL, display_name="Renamed mailbox")
        controller.mail_accounts.upsert(changed)
        window._refresh_now()
        self.assertIn("Renamed mailbox", window._account_widgets["mail:" + GMAIL.id]["label"].get_text())

    def test_main_add_account_routes_mail_to_browser_oauth_not_rclone(self):
        main = SimpleNamespace(controller=self.controller, _mail_connected=Mock())
        self.controller.config.accounts = []
        def choose_gmail(dialog):
            responses = []
            dialog.connect("response", lambda _dialog, response: responses.append(response))
            def walk(widget):
                yield widget
                if isinstance(widget, self.app.Gtk.Container):
                    for child in widget.get_children():
                        yield from walk(child)
            button = next(widget for widget in walk(dialog)
                          if isinstance(widget, self.app.Gtk.Button) and widget.get_label() == "Gmail")
            button.clicked()
            return responses[-1]
        # Use a real parent window; no application startup or network calls.
        parent = self.app.Gtk.Window()
        self.dialogs.append(parent)
        parent.controller = self.controller
        parent._mail_connected = main._mail_connected
        with patch.object(self.app.ResponsiveDialog, "run", choose_gmail), \
                patch.object(self.app, "MailConnectDialog") as connect, \
                patch.object(self.app, "OAuthWizard") as drive:
            self.app.MainWindow._choose_provider(parent, None)
        connect.assert_called_once_with(parent, self.controller, "gmail", main._mail_connected)
        drive.assert_not_called()

    def test_indexing_manager_selects_mailbox_from_main_account_menu(self):
        second = self.app.replace(GMAIL, id="c" * 32, display_name="Second mailbox", days=14)
        self.controller.mail_accounts.save([GMAIL, second])
        dialog = self.app.MailAccountsDialog(None, self.controller, selected_id=second.id)
        self.dialogs.append(dialog)
        self.assertEqual(dialog._account(), second)
        self.assertEqual(dialog.days.get_value_as_int(), 14)

    def test_mail_account_search_starts_in_mail_scope(self):
        self.controller.mail_search_index.refresh(GMAIL, SyntheticClient())
        dialog = self.app.FolderSearchDialog(None, self.controller, mail_account_id=GMAIL.id)
        self.dialogs.append(dialog)
        self.assertEqual(dialog.scope.get_active_id(), "mail")
        def synchronous(operation, ready):
            ready(operation(), None)
        with patch.object(self.app, "_run_thread", side_effect=synchronous):
            dialog.search_entry.set_text("invoice")
            dialog._run_search()
        self.assertEqual(len(dialog._results), 1)
        self.assertEqual(dialog._results[0].attachment.account_id, GMAIL.id)

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

    def test_closed_scan_manager_releases_busy_state_when_worker_returns(self):
        dialog = self.manager()
        pending = []
        with patch.object(self.app, "_run_thread", side_effect=lambda operation, ready: pending.append(ready)):
            dialog._refresh()
        self.assertTrue(dialog._busy)
        self.assertEqual(dialog._active_account_id, GMAIL.id)
        dialog.destroy()
        self.assertTrue(dialog._stop.is_set())
        pending[0](None, MailError("Mail index refresh cancelled."))
        self.assertFalse(dialog._busy)

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
