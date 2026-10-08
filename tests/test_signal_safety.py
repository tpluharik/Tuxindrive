from tests import signal_safety

import os
import signal
import sys
import unittest
from unittest.mock import patch


class SignalSafetyTests(unittest.TestCase):
    def test_real_signal_endpoints_are_blocked_by_default(self):
        self.assertIs(os.kill, signal_safety._probe_only)
        if hasattr(os, "killpg"):
            self.assertIs(os.killpg, signal_safety._deny)
        if hasattr(signal, "pidfd_send_signal"):
            self.assertIs(signal.pidfd_send_signal, signal_safety._deny)

    def test_audit_hook_blocks_cached_endpoint_events_without_a_syscall(self):
        for event, arguments in (("os.kill", (-1, signal.SIGTERM)),
                                 ("os.kill", (1234, signal.SIGTERM)),
                                 ("os.killpg", (1, signal.SIGTERM)),
                                 ("signal.pidfd_send_signal", (8, signal.SIGTERM))):
            with self.subTest(event=event), self.assertRaises(signal_safety.RealSignalBlocked):
                sys.audit(event, *arguments)

    def test_only_exact_positive_pid_zero_signal_probes_are_allowed(self):
        # Even a broken guard can only reach a mock, never the operating system.
        with patch.object(signal_safety, "_original_kill") as original:
            signal_safety._probe_only(1234, 0)
            original.assert_called_once_with(1234, 0)
            for pid, sig in ((-1, 0), (0, 0), (1, 0), (True, 0), (1234, signal.SIGTERM)):
                with self.assertRaises(signal_safety.RealSignalBlocked):
                    signal_safety._probe_only(pid, sig)
            original.assert_called_once_with(1234, 0)
