import signal
import subprocess
import unittest
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxindrive.process_control import new_process_group, reload_process, run_process, stop_process, terminate_process


class ProcessControlTests(unittest.TestCase):
    def test_bounded_run_preserves_output_input_and_exit_status(self):
        result = run_process(
            [sys.executable, "-c", "import sys; print(sys.stdin.read()); sys.exit(7)"],
            input="synthetic", capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(result.stdout.strip(), "synthetic")
        self.assertEqual(result.returncode, 7)
        with self.assertRaises(subprocess.CalledProcessError):
            run_process([sys.executable, "-c", "raise SystemExit(7)"], check=True, timeout=5)

    @unittest.skipIf(os.name == "nt", "POSIX process-group lifecycle")
    def test_timeout_reaps_descendant_not_just_group_leader(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "orphan-ran"
            child = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process([sys.executable, "-c", parent], capture_output=True, text=True, timeout=0.2)
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    @patch("tuxindrive.process_control.terminate_process")
    def test_shutdown_escalates_after_bounded_grace(self, terminate):
        process = MagicMock()
        process.wait.side_effect = [subprocess.TimeoutExpired("rclone", 5), -9]
        self.assertEqual(stop_process(process), -9)
        self.assertEqual(process.wait.call_args_list[0].kwargs, {"timeout": 5})
        terminate.assert_any_call(process, force=True)

    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_processes_use_native_group_flag(self, _system):
        self.assertEqual(
            new_process_group()["creationflags"],
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200),
        )

    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_process_is_terminated_without_posix_signals(self, _system):
        process = MagicMock()
        process.poll.return_value = None
        self.assertTrue(terminate_process(process))
        process.terminate.assert_called_once_with()

    @patch("tuxindrive.process_control.platform.system", return_value="Linux")
    @patch("tuxindrive.process_control.os.killpg")
    def test_unix_process_group_receives_signal(self, killpg, _system):
        process = MagicMock(pid=1234)
        process.poll.return_value = None
        self.assertTrue(terminate_process(process, force=True))
        killpg.assert_called_once_with(1234, signal.SIGKILL)

    @patch("tuxindrive.process_control.platform.system", return_value="Windows")
    def test_windows_reload_fails_closed(self, _system):
        process = MagicMock()
        process.poll.return_value = None
        self.assertFalse(reload_process(process))


if __name__ == "__main__":
    unittest.main()
