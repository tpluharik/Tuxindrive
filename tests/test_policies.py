from tests import signal_safety as _signal_safety  # noqa: F401

import unittest
from datetime import datetime
from unittest.mock import patch

from tuxindrive.models import AppSettings
from tuxindrive.policies import TransferPolicy


class TransferPolicyTests(unittest.TestCase):
    def test_default_is_unrestricted_maximum_usage(self):
        settings = AppSettings()
        with patch.object(TransferPolicy, "_metered", return_value=True), patch.object(
            TransferPolicy, "_battery_percent", return_value=1
        ):
            self.assertTrue(TransferPolicy(settings).evaluate().allowed)

    def test_controlled_schedule_and_battery_pause(self):
        settings = AppSettings(
            network_policy="controlled", pause_below_battery_percent=30,
            schedule_start="08:00", schedule_end="18:00",
        )
        with patch.object(TransferPolicy, "_battery_percent", return_value=20), patch.object(
            TransferPolicy, "_on_ac_power", return_value=False
        ), patch.object(TransferPolicy, "_metered", return_value=False):
            decision = TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 10, 0))
        self.assertFalse(decision.allowed)
        self.assertIn("battery", decision.reason)

    def test_controlled_schedule_pauses_outside_window(self):
        settings = AppSettings(network_policy="controlled", schedule_start="08:00", schedule_end="18:00")
        with patch.object(TransferPolicy, "_battery_percent", return_value=None), patch.object(
            TransferPolicy, "_metered", return_value=False
        ):
            self.assertFalse(TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 22, 0)).allowed)

    def test_metered_network_is_blocked_only_when_disallowed(self):
        settings = AppSettings(network_policy="controlled", allow_metered_networks=False)
        with patch.object(TransferPolicy, "_metered", return_value=True):
            decision = TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 12, 0))
        self.assertFalse(decision.allowed)
        self.assertIn("metered", decision.reason)

    def test_overnight_schedule_accepts_both_sides_of_midnight(self):
        settings = AppSettings(
            network_policy="controlled", schedule_start="22:00", schedule_end="06:00",
        )
        with patch.object(TransferPolicy, "_battery_percent", return_value=None), patch.object(
            TransferPolicy, "_metered", return_value=False,
        ):
            self.assertTrue(TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 23, 0)).allowed)
            self.assertTrue(TransferPolicy(settings).evaluate(datetime(2026, 1, 2, 5, 59)).allowed)
            self.assertFalse(TransferPolicy(settings).evaluate(datetime(2026, 1, 2, 6, 0)).allowed)

    def test_controlled_policy_reports_success_when_every_gate_allows(self):
        settings = AppSettings(network_policy="controlled")
        with patch.object(TransferPolicy, "_battery_percent", return_value=None), patch.object(
            TransferPolicy, "_metered", return_value=False,
        ):
            decision = TransferPolicy(settings).evaluate(datetime(2026, 1, 1, 12, 0))
        self.assertTrue(decision.allowed)
        self.assertIn("allows", decision.reason)

    def test_metered_probe_fails_open_without_networkmanager(self):
        with patch("tuxindrive.policies.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(TransferPolicy._metered())
