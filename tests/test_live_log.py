from tests import signal_safety as _signal_safety  # noqa: F401

import unittest

from tuxindrive.live_log import newest_first_log


class LiveLogTests(unittest.TestCase):
    def test_timestamped_records_are_rendered_newest_first(self) -> None:
        content = (
            "2026-09-26 09:00:00,000 INFO First\n"
            "2026-09-26 09:01:00,000 INFO Second\n"
            "2026-09-26 09:02:00,000 INFO Third\n"
        )

        self.assertEqual(
            newest_first_log(content),
            "2026-09-26 09:02:00,000 INFO Third\n"
            "2026-09-26 09:01:00,000 INFO Second\n"
            "2026-09-26 09:00:00,000 INFO First",
        )

    def test_multiline_error_stays_with_its_record(self) -> None:
        content = (
            "2026-09-26 09:00:00,000 ERROR Transfer failed\n"
            "Traceback (most recent call last):\n"
            "  provider error\n"
            "2026-09-26 09:01:00,000 INFO Retrying\n"
        )

        self.assertEqual(
            newest_first_log(content),
            "2026-09-26 09:01:00,000 INFO Retrying\n"
            "2026-09-26 09:00:00,000 ERROR Transfer failed\n"
            "Traceback (most recent call last):\n"
            "  provider error",
        )

    def test_untimestamped_provider_output_is_reversed_by_line(self) -> None:
        self.assertEqual(newest_first_log("first\nsecond\nthird\n"), "third\nsecond\nfirst")


if __name__ == "__main__":
    unittest.main()
