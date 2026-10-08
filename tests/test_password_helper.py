from tests import signal_safety as _signal_safety  # noqa: F401

import unittest
import subprocess
from unittest.mock import MagicMock, patch

from tuxindrive.password_helper import (
    ACCOUNT,
    LEGACY_SERVICE,
    SERVICE,
    configuration_password,
    store_configuration_password,
)


class PasswordHelperTests(unittest.TestCase):
    @patch("tuxindrive.password_helper._set_password")
    @patch("tuxindrive.password_helper.subprocess.run")
    def test_timeout_does_not_rotate_or_store_a_replacement_key(self, run, store):
        run.side_effect = subprocess.TimeoutExpired("secret-tool", 10)
        with self.assertRaisesRegex(RuntimeError, "desktop keyring"):
            configuration_password(ensure=True)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)
        store.assert_not_called()

    @patch("tuxindrive.password_helper._set_password")
    @patch("tuxindrive.password_helper.subprocess.run")
    def test_backend_failure_does_not_rotate_an_existing_key(self, run, store):
        run.return_value = MagicMock(returncode=1, stdout="", stderr="backend failed")
        with self.assertRaisesRegex(RuntimeError, "credential-store integration"):
            configuration_password(ensure=True)
        store.assert_not_called()

    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=False)
    @patch("tuxindrive.password_helper._keyring")
    def test_current_native_key_is_returned(self, keyring_factory, _backend):
        keyring = keyring_factory.return_value
        keyring.get_password.return_value = "current-secret"
        self.assertEqual(configuration_password(), "current-secret")
        keyring.get_password.assert_called_once_with(SERVICE, ACCOUNT)

    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=False)
    @patch("tuxindrive.password_helper._keyring")
    def test_legacy_native_key_is_read_in_place(self, keyring_factory, _backend):
        keyring = keyring_factory.return_value
        keyring.get_password.side_effect = [None, "legacy-secret"]
        self.assertEqual(configuration_password(), "legacy-secret")
        keyring.get_password.assert_any_call(LEGACY_SERVICE, ACCOUNT)
        keyring.set_password.assert_not_called()

    @patch("tuxindrive.password_helper.secrets.token_urlsafe", return_value="new-secret")
    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=False)
    @patch("tuxindrive.password_helper._keyring")
    def test_ensure_creates_key_only_when_missing(self, keyring_factory, _backend, _token):
        keyring = keyring_factory.return_value
        keyring.get_password.return_value = None
        self.assertEqual(configuration_password(ensure=True), "new-secret")
        keyring.set_password.assert_called_once_with(SERVICE, ACCOUNT, "new-secret")

    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=False)
    @patch("tuxindrive.password_helper._keyring")
    def test_explicit_migration_key_is_stored_in_current_service(self, keyring_factory, _backend):
        store_configuration_password("migrated-secret")
        keyring_factory.return_value.set_password.assert_called_once_with(
            SERVICE, ACCOUNT, "migrated-secret"
        )

    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=True)
    @patch("tuxindrive.password_helper._secret_tool_lookup")
    def test_linux_reads_current_secret_tool_entry(self, lookup, _backend):
        lookup.return_value = "linux-secret"
        self.assertEqual(configuration_password(), "linux-secret")
        lookup.assert_called_once_with(SERVICE)

    @patch("tuxindrive.password_helper._uses_secret_tool", return_value=True)
    @patch("tuxindrive.password_helper._secret_tool_lookup")
    def test_linux_reads_legacy_secret_tool_entry_in_place(self, lookup, _backend):
        lookup.side_effect = [None, "legacy-linux-secret"]
        self.assertEqual(configuration_password(), "legacy-linux-secret")
        self.assertEqual(lookup.call_args_list[1].args, (LEGACY_SERVICE,))

    @patch("tuxindrive.password_helper.subprocess.run")
    def test_linux_store_passes_secret_only_over_stdin(self, run):
        run.return_value = MagicMock(returncode=0)
        store_configuration_password("migrated-linux-secret")
        args, kwargs = run.call_args
        self.assertNotIn("migrated-linux-secret", args[0])
        self.assertEqual(kwargs["input"], "migrated-linux-secret")
        self.assertEqual(args[0][0], "/usr/bin/secret-tool")
        self.assertIn("application", args[0])
        self.assertIn("tuxindrive", args[0])

    @patch("tuxindrive.password_helper.subprocess.run")
    def test_linux_lookup_distinguishes_missing_entry_from_backend_failure(self, run):
        run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        with self.assertRaisesRegex(RuntimeError, "configuration key is unavailable"):
            configuration_password()
        run.return_value = MagicMock(returncode=1, stdout="", stderr="D-Bus unavailable")
        with self.assertRaisesRegex(RuntimeError, "credential-store integration"):
            configuration_password()


if __name__ == "__main__":
    unittest.main()
