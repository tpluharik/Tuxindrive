"""Real process signals: disposable Linux container only, never unit discovery."""

import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import time
import unittest

from tuxindrive.process_control import run_process, spawn_process, stop_process


ISOLATED = (
    sys.platform.startswith("linux")
    and os.environ.get("TUXINDRIVE_ISOLATED_PROCESS_TESTS") == "1"
    and (Path("/.dockerenv").is_file() or Path("/run/.containerenv").is_file())
    and not os.environ.get("DISPLAY")
    and not os.environ.get("WAYLAND_DISPLAY")
)


@unittest.skipUnless(ISOLATED, "requires explicit opt-in and a disposable Linux container")
class IsolatedProcessTests(unittest.TestCase):
    def test_run_preserves_input_output_and_status(self):
        result = run_process([sys.executable, "-c", "import sys; print(sys.stdin.read()); sys.exit(7)"],
                             input="synthetic", capture_output=True, text=True, timeout=5)
        self.assertEqual(result.stdout.strip(), "synthetic")
        self.assertEqual(result.returncode, 7)

    def test_timeout_reaps_descendant_not_just_group_leader(self):
        with tempfile.TemporaryDirectory() as temporary:
            marker = Path(temporary) / "orphan-ran"
            child = f"import time; from pathlib import Path; time.sleep(0.6); Path({str(marker)!r}).touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            with self.assertRaises(subprocess.TimeoutExpired):
                run_process([sys.executable, "-c", parent], capture_output=True, text=True, timeout=0.2)
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_stop_cleans_term_ignoring_child_after_leader_is_reaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / "ready"
            marker = Path(temporary) / "orphan-ran"
            child = ("import signal,time; from pathlib import Path; "
                     "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
                     f"Path({str(ready)!r}).touch(); time.sleep(1); Path({str(marker)!r}).touch()")
            parent = ("import subprocess,sys,time; from pathlib import Path\n"
                      f"subprocess.Popen([sys.executable,'-c',{child!r}])\n"
                      f"ready=Path({str(ready)!r})\n"
                      "deadline=time.monotonic()+3\n"
                      "while not ready.exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
                      "print('ready',flush=True)\ntime.sleep(10)\n")
            process = spawn_process([sys.executable, "-c", parent], stdout=subprocess.PIPE, text=True)
            try:
                self.assertTrue(select.select([process.stdout], [], [], 4)[0])
                self.assertEqual(process.stdout.readline().strip(), "ready")
                self.assertTrue(ready.exists())
                stop_process(process, grace=0.5)
                time.sleep(1.1)
                self.assertFalse(marker.exists())
            finally:
                stop_process(process, grace=0.5)
                process.stdout.close()
