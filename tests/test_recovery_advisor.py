import unittest

from tuxindrive.recovery_advisor import advice_for_error


class RecoveryAdvisorTests(unittest.TestCase):
    def test_known_failures_have_actionable_categories(self):
        self.assertEqual(advice_for_error("invalid_grant: token expired").code, "authorization")
        self.assertEqual(advice_for_error("Bisync critical error: must run --resync").code, "bisync-state")
        self.assertEqual(advice_for_error("Protection paused synchronization: 90% changed").code, "bulk-protection")
        self.assertEqual(advice_for_error("connection reset by peer").code, "network")

    def test_unknown_failure_falls_back_without_echoing_unbounded_input(self):
        advice = advice_for_error("unexpected backend response")
        self.assertEqual(advice.code, "inspect")
        self.assertTrue(advice.steps)
