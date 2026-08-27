import unittest
from datetime import datetime, timedelta, timezone

from tuxindrive.scheduling import persisted_run_time


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)

    def test_timezone_aware_persisted_run_is_restored(self):
        value = persisted_run_time("2026-08-27T13:30:00+02:00", self.now)
        self.assertEqual(value, datetime(2026, 8, 27, 11, 30, tzinfo=timezone.utc))

    def test_malformed_and_naive_values_fail_open_to_reconciliation(self):
        self.assertIsNone(persisted_run_time("not-a-date", self.now))
        self.assertIsNone(persisted_run_time("2026-08-27T11:30:00", self.now))

    def test_large_future_clock_does_not_suppress_recovery(self):
        self.assertIsNone(persisted_run_time((self.now + timedelta(hours=1)).isoformat(), self.now))
        self.assertIsNotNone(persisted_run_time((self.now + timedelta(minutes=4)).isoformat(), self.now))


if __name__ == "__main__":
    unittest.main()
