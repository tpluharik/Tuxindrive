from tests import signal_safety as _signal_safety  # noqa: F401

import signal
import unittest
from unittest.mock import call, patch

from tuxindrive import upgrade_processes as upgrade
from tuxindrive.process_control import _Identity


class UpgradeProcessTests(unittest.TestCase):
    def test_exact_launcher_arguments_are_required_not_a_substring(self):
        code = ('import runpy,sys; sys.path.insert(0,"/usr/lib"); '
                'sys.argv[0]="tuxindrive"; runpy.run_module("tuxindrive.app",run_name="__main__")')
        for candidate, expected in ((code, True), (code + "; print('other')", False),
                                    ("print(" + repr(code) + ")", False)):
            payload = b"\0".join([b"/usr/bin/python3", b"-I", b"-c", candidate.encode(), b""])
            with patch.object(upgrade.Path, "read_bytes", return_value=payload), \
                 patch.object(upgrade.os, "readlink", return_value="/usr/bin/python3.12"), \
                 patch.object(upgrade.os, "getpid", return_value=99):
                self.assertEqual(upgrade._is_application(1234), expected)

    def test_invalid_pids_cannot_be_discovered_as_application_targets(self):
        with patch.object(upgrade.Path, "read_bytes") as read:
            for pid in (0, 1, -1, True, "1234", None):
                self.assertFalse(upgrade._is_application(pid))
        read.assert_not_called()

    def test_escalation_uses_same_pidfd_not_reused_numeric_pid(self):
        identity = _Identity(1234, 1234, 1234, 100)
        with patch.object(upgrade.os, "listdir", return_value=["1234"]), \
             patch.object(upgrade, "_is_application", return_value=True), \
             patch.object(upgrade, "_linux_identity", return_value=identity), \
             patch.object(upgrade.os, "pidfd_open", return_value=8, create=True) as opened, \
             patch.object(upgrade.signal, "pidfd_send_signal", create=True) as send, \
             patch.object(upgrade.os, "close") as closed:
            self.assertEqual(upgrade.stop_previous_applications(grace=0), 1)
        opened.assert_called_once_with(1234, 0)
        send.assert_has_calls([call(8, signal.SIGINT, None, 0), call(8, signal.SIGTERM, None, 0)])
        closed.assert_called_once_with(8)

    def test_identity_change_during_open_refuses_both_signals(self):
        identities = [_Identity(1234, 1234, 1234, 100), _Identity(1234, 1234, 1234, 200)]
        with patch.object(upgrade.os, "listdir", return_value=["1234"]), \
             patch.object(upgrade, "_is_application", return_value=True), \
             patch.object(upgrade, "_linux_identity", side_effect=identities), \
             patch.object(upgrade.os, "pidfd_open", return_value=8, create=True), \
             patch.object(upgrade.signal, "pidfd_send_signal", create=True) as send, \
             patch.object(upgrade.os, "close") as closed:
            self.assertEqual(upgrade.stop_previous_applications(grace=0), 0)
        send.assert_not_called()
        closed.assert_called_once_with(8)

    def test_clean_exit_does_not_escalate(self):
        identity = _Identity(1234, 1234, 1234, 100)
        with patch.object(upgrade.os, "listdir", return_value=["1234"]), \
             patch.object(upgrade, "_is_application", return_value=True), \
             patch.object(upgrade, "_linux_identity", return_value=identity), \
             patch.object(upgrade.os, "pidfd_open", return_value=8, create=True), \
             patch.object(upgrade.signal, "pidfd_send_signal", create=True) as send, \
             patch.object(upgrade.select, "select", return_value=([8], [], [])), \
             patch.object(upgrade.os, "close"):
            self.assertEqual(upgrade.stop_previous_applications(), 1)
        send.assert_called_once_with(8, signal.SIGINT, None, 0)
