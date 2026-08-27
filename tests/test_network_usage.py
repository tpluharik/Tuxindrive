import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from tuxindrive.network_usage import (
    NetworkUsageMeter, _linux_counters, _macos_counters, _windows_counters,
    format_bytes, read_network_counters,
)


class Sequence:
    def __init__(self, values):
        self.values = iter(values)

    def __call__(self):
        return next(self.values)


class NetworkUsageTests(unittest.TestCase):
    def test_current_rates_and_daily_totals(self):
        with tempfile.TemporaryDirectory() as temporary:
            meter = NetworkUsageMeter(
                Path(temporary) / "usage.json",
                reader=Sequence([(1000, 2000), (3048, 3024)]),
                clock=Sequence([10.0, 10.0, 12.0]),
                today=lambda: date(2026, 8, 13),
            )
            usage = meter.sample()
        self.assertEqual(usage.download_rate, 1024.0)
        self.assertEqual(usage.upload_rate, 512.0)
        self.assertEqual(usage.downloaded_today, 2048)
        self.assertEqual(usage.uploaded_today, 1024)

    def test_restart_restores_total_and_counts_traffic_while_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            path.write_text(json.dumps({
                "day": "2026-08-13", "downloaded": 500,
                "uploaded": 250, "counters": [1000, 2000],
            }), encoding="utf-8")
            meter = NetworkUsageMeter(
                path, reader=lambda: (1600, 2300), clock=lambda: 5.0,
                today=lambda: date(2026, 8, 13),
            )
        self.assertEqual(meter.usage.downloaded_today, 1100)
        self.assertEqual(meter.usage.uploaded_today, 550)

    def test_new_day_resets_totals_and_counter_reset_is_safe(self):
        days = Sequence([date(2026, 8, 13), date(2026, 8, 14)])
        with tempfile.TemporaryDirectory() as temporary:
            meter = NetworkUsageMeter(
                Path(temporary) / "usage.json",
                reader=Sequence([(5000, 9000), (100, 200)]),
                clock=Sequence([1.0, 1.0, 2.0]), today=days,
            )
            usage = meter.sample()
        self.assertEqual((usage.downloaded_today, usage.uploaded_today), (0, 0))

    def test_linux_parser_excludes_loopback(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dev"
            path.write_text(
                "Inter-| Receive | Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
                " lo: 900 0 0 0 0 0 0 0 800 0 0 0 0 0 0 0\n"
                "eth0: 1234 0 0 0 0 0 0 0 5678 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            self.assertEqual(_linux_counters(path), (1234, 5678))

    def test_linux_parser_fails_closed_on_malformed_counters(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "dev"
            path.write_text(
                "Inter-| Receive | Transmit\n"
                " face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n"
                "eth0: not-a-number\n",
                encoding="utf-8",
            )
            self.assertIsNone(_linux_counters(path))

    def test_macos_parser_deduplicates_interface_rows_and_excludes_loopback(self):
        output = (
            "Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
            "en0 1500 link aa 1 0 100 2 0 200 0\n"
            "en0 1500 link bb 2 0 150 3 0 250 0\n"
            "lo0 16384 link cc 3 0 999 4 0 999 0\n"
        )
        with patch("tuxindrive.network_usage.subprocess.run", return_value=Mock(returncode=0, stdout=output)):
            self.assertEqual(_macos_counters(), (150, 250))

    def test_macos_and_windows_probe_failures_are_nonfatal(self):
        with patch("tuxindrive.network_usage.subprocess.run", side_effect=FileNotFoundError):
            self.assertIsNone(_macos_counters())
        with patch("tuxindrive.network_usage.platform.system", return_value="Linux"):
            self.assertIsNone(_windows_counters())

    def test_counter_dispatch_selects_the_current_platform(self):
        with patch("tuxindrive.network_usage.platform.system", return_value="Darwin"), patch(
            "tuxindrive.network_usage._macos_counters", return_value=(7, 8),
        ) as macos:
            self.assertEqual(read_network_counters(), (7, 8))
        macos.assert_called_once_with()

    def test_unavailable_counters_preserve_totals_without_writing_garbage(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "usage.json"
            meter = NetworkUsageMeter(path, reader=lambda: None, clock=lambda: 1.0)
            usage = meter.sample()
        self.assertFalse(usage.available)
        self.assertEqual((usage.downloaded_today, usage.uploaded_today), (0, 0))

    def test_expensive_platform_reader_is_cached_between_display_ticks(self):
        reader = Mock(side_effect=[(100, 200), (400, 500)])
        with tempfile.TemporaryDirectory() as temporary:
            meter = NetworkUsageMeter(
                Path(temporary) / "usage.json", reader=reader,
                clock=Sequence([1.0, 1.0, 2.0, 5.0]),
                minimum_sample_seconds=3.0,
            )
            cached = meter.sample()
            self.assertEqual(reader.call_count, 1)
            updated = meter.sample()
        self.assertEqual(cached.downloaded_today, 0)
        self.assertEqual(updated.downloaded_today, 300)
        self.assertEqual(reader.call_count, 2)

    def test_human_readable_units(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1536), "1.5 KiB")
        self.assertEqual(format_bytes(1024 * 1024, rate=True), "1.0 MiB/s")
        self.assertEqual(format_bytes(-5), "0 B")


if __name__ == "__main__":
    unittest.main()
