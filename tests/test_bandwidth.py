import threading
import time
import unittest
from unittest.mock import patch

from tuxindrive.bandwidth import (
    GlobalBandwidthController,
    effective_rclone_limit,
    normalize_bandwidth_limit,
    protected_bandwidth_limit,
)


class GlobalBandwidthControllerTests(unittest.TestCase):
    def test_rates_are_validated_and_directional_limits_are_combined(self):
        self.assertEqual(normalize_bandwidth_limit(" 2M:10M "), "2M:10M")
        self.assertEqual(effective_rclone_limit("2M:10M", "5M:4M"), "2M:4M")
        self.assertEqual(effective_rclone_limit("off", "3M"), "3M")
        with self.assertRaises(ValueError):
            normalize_bandwidth_limit("weekday 10M")

    def test_invalid_shapes_and_units_are_rejected(self):
        for value in ("1M:2M:3M", "-1M", "1MiB", "NaN", "1 M", "off:bad"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_bandwidth_limit(value)

    def test_unlimited_direction_never_overrides_a_finite_limit(self):
        self.assertEqual(effective_rclone_limit("off:10M", "2M:off"), "2M:10M")
        self.assertEqual(effective_rclone_limit("off", "3M"), "3M")
        self.assertEqual(effective_rclone_limit("4M", "invalid schedule"), "4M")

    def test_rclone_uses_global_limit_unless_job_is_stricter(self):
        controller = GlobalBandwidthController("10M")
        self.assertEqual(controller.rclone_args(), ["--bwlimit", "10M"])
        self.assertEqual(controller.rclone_args("2M"), ["--bwlimit", "2M"])
        controller.configure("off")
        self.assertFalse(controller.enabled)

    def test_automatic_limit_reserves_headroom_and_divides_parallel_consumers(self):
        self.assertEqual(
            protected_bandwidth_limit("10M", headroom_percent=20, parallel_budget=2),
            "4194304B",
        )
        self.assertEqual(
            protected_bandwidth_limit("2M:10M", headroom_percent=25, parallel_budget=2),
            "786432B:3932160B",
        )
        controller = GlobalBandwidthController("10M", automatic=True, headroom_percent=20)
        controller.configure_parallel_budget(2)
        self.assertEqual(controller.rclone_args(), ["--bwlimit", "4194304B"])
        self.assertEqual(controller.rclone_args("2M"), ["--bwlimit", "2M"])

    def test_in_process_downloads_share_one_rate_clock(self):
        controller = GlobalBandwidthController("1")
        with patch("tuxindrive.bandwidth.time.monotonic", return_value=10.0), patch(
            "tuxindrive.bandwidth.time.sleep"
        ) as sleep:
            controller.throttle_download(1024)
            controller.throttle_download(1024)
        sleep.assert_called_once_with(1.0)

    def test_upload_and_download_use_independent_directional_clocks(self):
        controller = GlobalBandwidthController("1:2")
        with patch("tuxindrive.bandwidth.time.monotonic", return_value=10.0), patch(
            "tuxindrive.bandwidth.time.sleep"
        ) as sleep:
            controller.throttle_upload(1024)
            controller.throttle_upload(1024)
            controller.throttle_download(2048)
            controller.throttle_download(2048)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1.0, 1.0])

    def test_zero_unlimited_and_empty_downloads_do_not_sleep(self):
        with patch("tuxindrive.bandwidth.time.sleep") as sleep:
            for limit, count in (("", 1024), ("off", 1024), ("0", 1024), ("1M", 0), ("1M", -1)):
                GlobalBandwidthController(limit).throttle_download(count)
        sleep.assert_not_called()

    def test_scan_jitter_is_bounded_and_handles_nonpositive_intervals(self):
        with patch("tuxindrive.bandwidth.random.uniform", return_value=0.25) as uniform:
            self.assertEqual(GlobalBandwidthController.scan_jitter(120), 0.25)
            uniform.assert_called_once_with(0.0, 30.0)
        with patch("tuxindrive.bandwidth.random.uniform", return_value=0.0) as uniform:
            GlobalBandwidthController.scan_jitter(-10)
            uniform.assert_called_once_with(0.0, 0.25)

    def test_parallel_exclusive_callers_do_not_deadlock(self):
        controller = GlobalBandwidthController("1M", max_active=2)
        completed: list[int] = []

        def run(index: int) -> None:
            with controller.guard(exclusive=True):
                time.sleep(0.01)
                completed.append(index)

        threads = [threading.Thread(target=run, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=1)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertCountEqual(completed, [0, 1])

    def test_guard_releases_every_slot_after_an_exception(self):
        controller = GlobalBandwidthController("1M", max_active=2)
        with self.assertRaisesRegex(RuntimeError, "stop"):
            with controller.guard(exclusive=True):
                raise RuntimeError("stop")
        completed = []
        with controller.guard(exclusive=True):
            completed.append(True)
        self.assertEqual(completed, [True])

    def test_control_plane_request_is_not_starved_by_active_transfer(self):
        controller = GlobalBandwidthController("1M", max_active=1)
        transfer_entered = threading.Event()
        release_transfer = threading.Event()
        control_completed = threading.Event()

        def transfer() -> None:
            with controller.guard():
                transfer_entered.set()
                release_transfer.wait(timeout=1)

        def control_request() -> None:
            with controller.control_plane_guard():
                control_completed.set()

        transfer_thread = threading.Thread(target=transfer)
        transfer_thread.start()
        self.assertTrue(transfer_entered.wait(timeout=1))
        control_thread = threading.Thread(target=control_request)
        control_thread.start()
        control_thread.join(timeout=0.2)
        release_transfer.set()
        transfer_thread.join(timeout=1)

        self.assertTrue(control_completed.is_set())
        self.assertFalse(control_thread.is_alive())
        self.assertFalse(transfer_thread.is_alive())

    def test_interactive_transfer_is_not_starved_by_active_sync(self):
        controller = GlobalBandwidthController("1M", max_active=1)
        sync_entered = threading.Event()
        release_sync = threading.Event()
        interactive_completed = threading.Event()

        def sync() -> None:
            with controller.guard():
                sync_entered.set()
                release_sync.wait(timeout=1)

        def interactive() -> None:
            with controller.interactive_transfer_guard():
                interactive_completed.set()

        sync_thread = threading.Thread(target=sync)
        sync_thread.start()
        self.assertTrue(sync_entered.wait(timeout=1))
        interactive_thread = threading.Thread(target=interactive)
        interactive_thread.start()
        interactive_thread.join(timeout=0.2)
        release_sync.set()
        sync_thread.join(timeout=1)

        self.assertTrue(interactive_completed.is_set())
        self.assertFalse(interactive_thread.is_alive())
        self.assertFalse(sync_thread.is_alive())


if __name__ == "__main__":
    unittest.main()
