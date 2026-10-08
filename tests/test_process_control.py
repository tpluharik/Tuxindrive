from tests import signal_safety as _signal_safety  # noqa: F401

import signal
import subprocess
import threading
import unittest
from unittest.mock import MagicMock, call, patch

from tuxindrive import process_control as control


class StubProcess:
    """No OS process, pipes, descriptors or destructor are created."""

    def __init__(self, pid=1234):
        self.pid = pid
        self.returncode = None
        self._waitpid_lock = threading.Lock()
        self.wait = MagicMock(return_value=0)
        self.kill = MagicMock()
        self.terminate = MagicMock()

    def poll(self):
        return self.returncode


class ProcessControlTests(unittest.TestCase):
    def setUp(self):
        self.patchers = [
            patch.object(control, "_POPEN_TYPE", StubProcess),
            patch.object(control.signal, "SIGHUP", 1, create=True),
            patch.object(control.signal, "SIGKILL", 9, create=True),
            patch.object(control.os, "killpg", create=True),
            patch.object(control.signal, "pidfd_send_signal", create=True),
            patch.object(control.os, "getpgid", side_effect=lambda pid: pid, create=True),
            patch.object(control.os, "getsid", side_effect=lambda pid: pid, create=True),
            patch.object(control.os, "getpgrp", return_value=99, create=True),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)

    def owned(self, *, pid=1234, system="Darwin"):
        process = StubProcess(pid)
        owner = control._Ownership(pid, system)
        control._OWNED[process] = owner
        self.addCleanup(control._OWNED.pop, process, None)
        return process, owner

    def test_all_signal_paths_reject_invalid_pids_without_coercion(self):
        for pid in (None, True, False, 0, 1, -1, -123, "1234", 1.5, 2**63, MagicMock()):
            with self.subTest(pid=repr(pid)):
                process, _owner = self.owned(pid=pid)
                self.assertFalse(control.terminate_process(process))
                self.assertFalse(control.terminate_process(process, force=True))
                self.assertFalse(control.reload_process(process))
        control.os.killpg.assert_not_called()
        control.signal.pidfd_send_signal.assert_not_called()

    def test_mocked_and_spec_spoofed_processes_are_never_owned(self):
        for process in (MagicMock(), MagicMock(pid=1234), MagicMock(spec=StubProcess)):
            process.poll.return_value = None
            self.assertFalse(control.terminate_process(process, force=True))
            self.assertFalse(control.reload_process(process))
        control.os.killpg.assert_not_called()
        control.signal.pidfd_send_signal.assert_not_called()

    def test_valid_but_unregistered_pid_is_rejected(self):
        process = StubProcess()
        self.assertFalse(control.terminate_process(process, force=True))
        self.assertFalse(control.reload_process(process))
        control.os.killpg.assert_not_called()

    def test_owned_unreaped_group_receives_term_kill_and_reload(self):
        process, _owner = self.owned()
        control.os.killpg.side_effect = lambda *_args: self.assertTrue(process._waitpid_lock.locked())
        with patch.object(control.platform, "system", return_value="Darwin"):
            self.assertTrue(control.terminate_process(process))
            self.assertTrue(control.terminate_process(process, force=True))
            self.assertTrue(control.reload_process(process))
        control.os.killpg.assert_has_calls([
            call(1234, signal.SIGTERM), call(1234, getattr(signal, "SIGKILL", 9)),
            call(1234, getattr(signal, "SIGHUP", 1)),
        ])

    def test_foreign_or_current_group_is_never_signalled(self):
        process, _owner = self.owned()
        for endpoint, value in (("getpgid", 2222), ("getsid", 2222), ("getpgrp", 1234)):
            with self.subTest(endpoint=endpoint), patch.object(control.os, endpoint, return_value=value):
                self.assertFalse(control.terminate_process(process, force=True))
        control.os.killpg.assert_not_called()

    def test_reaped_posix_leader_is_rejected_even_when_forced(self):
        process, _owner = self.owned()
        process.returncode = 0
        self.assertFalse(control.terminate_process(process, force=True))
        control.os.killpg.assert_not_called()

    def test_busy_wait_lock_fails_closed_without_blocking_cancellation(self):
        process, _owner = self.owned()
        process._waitpid_lock.acquire()
        try:
            self.assertFalse(control.terminate_process(process, force=True))
        finally:
            process._waitpid_lock.release()
        control.os.killpg.assert_not_called()

    def test_portable_wait_uses_short_bounded_waits(self):
        process, _owner = self.owned()
        process.wait.side_effect = [subprocess.TimeoutExpired("synthetic", 0.2), 0]
        self.assertEqual(control.wait_process(process), 0)
        self.assertEqual(process.wait.call_args_list, [call(timeout=0.2), call(timeout=0.2)])

    def test_changed_pid_cannot_redirect_registered_ownership(self):
        process, _owner = self.owned()
        process.pid = 4321
        self.assertFalse(control.terminate_process(process, force=True))
        control.os.killpg.assert_not_called()

    def test_pidfds_keep_original_targets_after_leader_reaping(self):
        process, owner = self.owned(system="Linux")
        process.returncode = 0
        owner.members = {
            1234: (8, control._Identity(1234, 1234, 1234, 100)),
            1235: (9, control._Identity(1235, 1234, 1234, 101)),
        }
        with patch.object(control, "_remember_linux_members"):
            self.assertTrue(control.terminate_process(process, force=True))
        control.signal.pidfd_send_signal.assert_has_calls([
            call(9, getattr(signal, "SIGKILL", 9), None, 0),
            call(8, getattr(signal, "SIGKILL", 9), None, 0),
        ])
        control.os.killpg.assert_not_called()

    def test_dead_or_reused_anchor_cannot_adopt_a_new_session(self):
        process, owner = self.owned(system="Linux")
        owner.members = {1234: (8, control._Identity(1234, 1234, 1234, 100))}
        for ready, identity in (([8], owner.members[1234][1]),
                                ([], control._Identity(1234, 1234, 1234, 200))):
            with patch.object(control.select, "poll", create=True) as poller, \
                 patch.object(control, "_linux_identity", return_value=identity), \
                 patch.object(control.os, "pidfd_open", create=True) as opened:
                poller.return_value.poll.return_value = ready
                with patch.object(control.select, "POLLIN", 1, create=True):
                    control._remember_linux_members(owner)
            opened.assert_not_called()

    def test_raced_member_identity_is_closed_not_adopted(self):
        _process, owner = self.owned(system="Linux")
        owner.members = {1234: (8, control._Identity(1234, 1234, 1234, 100))}
        first = control._Identity(1235, 1234, 1234, 101)
        second = control._Identity(1235, 1234, 1234, 202)
        with patch.object(control, "_anchor_matches", return_value=True), \
             patch.object(control.os, "listdir", return_value=["1235"]), \
             patch.object(control, "_linux_identity", side_effect=[first, second]), \
             patch.object(control.os, "pidfd_open", return_value=9, create=True), \
             patch.object(control.os, "close") as closed:
            control._remember_linux_members(owner)
        closed.assert_called_once_with(9)
        self.assertNotIn(1235, owner.members)

    def test_windows_uses_only_registered_native_handles(self):
        process, _owner = self.owned(system="Windows")
        self.assertTrue(control.terminate_process(process))
        self.assertTrue(control.terminate_process(process, force=True))
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        control.os.killpg.assert_not_called()

    def test_windows_reload_fails_closed(self):
        process, _owner = self.owned(system="Windows")
        with patch.object(control.platform, "system", return_value="Windows"):
            self.assertFalse(control.reload_process(process))
        control.os.killpg.assert_not_called()

    def test_shutdown_is_bounded_and_always_uses_owned_gateway(self):
        process = StubProcess()
        process.wait.side_effect = [subprocess.TimeoutExpired("rclone", 5), -9]
        with patch.object(control, "terminate_process") as terminate:
            self.assertEqual(control.stop_process(process), -9)
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 5})
        terminate.assert_any_call(process, force=True)

    def test_mocked_spawn_cannot_register_fabricated_pid(self):
        process = MagicMock(pid=1234)
        with patch.object(control.subprocess, "Popen", return_value=process) as popen:
            self.assertIs(control.spawn_process(["synthetic"]), process)
        self.assertNotIn(process, control._OWNED)
        self.assertIn("start_new_session" if control.platform.system() != "Windows"
                      else "creationflags", popen.call_args.kwargs)

    def test_registration_pins_verified_birth_identity(self):
        process = StubProcess()
        identity = control._Identity(1234, 1234, 1234, 100)
        with patch.object(control.platform, "system", return_value="Linux"), \
             patch.object(control, "_linux_identity", return_value=identity), \
             patch.object(control.os, "pidfd_open", return_value=8, create=True) as opened, \
             patch.object(control.os, "close") as closed:
            control._register_process(process)
            owner = control._OWNED[process]
            self.assertEqual(owner.members[1234], (8, identity))
            owner.close()  # Empty the synthetic handles before finalization.
        opened.assert_called_once_with(1234, 0)
        closed.assert_called_once_with(8)
        control._OWNED.pop(process)

    def test_registration_rejects_a_foreign_group(self):
        process = StubProcess()
        with patch.object(control.platform, "system", return_value="Darwin"), \
             patch.object(control.os, "getpgid", return_value=4321):
            control._register_process(process)
        self.assertNotIn(process, control._OWNED)

    def test_proc_stat_parses_spaces_parentheses_and_birth_time(self):
        fields = ["S", "99", "1234", "1234"] + ["0"] * 15 + ["100"]
        stat = "1234 (helper ) with spaces) " + " ".join(fields)
        with patch.object(control.Path, "read_text", return_value=stat):
            self.assertEqual(control._linux_identity(1234), control._Identity(1234, 1234, 1234, 100))
        with patch.object(control.Path, "read_text", return_value="malformed"):
            self.assertIsNone(control._linux_identity(1234))

    def test_bounded_run_preserves_mocked_output_and_exit_status(self):
        process = MagicMock(returncode=7)
        process.__enter__.return_value = process
        process.communicate.return_value = ("synthetic\n", "")
        with patch.object(control.subprocess, "Popen", return_value=process):
            result = control.run_process(["synthetic"], input="synthetic", capture_output=True, timeout=5)
            self.assertEqual(result.stdout.strip(), "synthetic")
            self.assertEqual(result.returncode, 7)
            with self.assertRaises(subprocess.CalledProcessError):
                control.run_process(["synthetic"], check=True, timeout=5)

    def test_timeout_cleanup_and_pipe_waits_remain_bounded(self):
        process = MagicMock()
        process.__enter__.return_value = process
        process.communicate.side_effect = [subprocess.TimeoutExpired("synthetic", 2),
                                           subprocess.TimeoutExpired("synthetic", 5)]
        with patch.object(control.subprocess, "Popen", return_value=process), \
             patch.object(control, "terminate_process") as terminate:
            with self.assertRaises(subprocess.TimeoutExpired):
                control.run_process(["synthetic"], timeout=2)
        terminate.assert_called_once_with(process, force=True)
        process.wait.assert_called_once_with(timeout=5)
        process.stdout.close.assert_called_once_with()
        process.stderr.close.assert_called_once_with()
        process.__enter__.assert_not_called()
        process.__exit__.assert_not_called()


if __name__ == "__main__":
    unittest.main()
