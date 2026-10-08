from tests import signal_safety as _signal_safety  # noqa: F401

import unittest
from pathlib import Path
from unittest.mock import patch

from tuxindrive.nautilus_support import (
    availability_route,
    command_line_path,
    is_available_offline,
    lexical_relative_path,
    rule_matches,
    verified_rules_after,
)


class OfflineActionTests(unittest.TestCase):
    def test_command_line_fallback_accepts_both_path_forms(self):
        self.assertEqual(
            command_line_path(["--offline-path", "/mnt/Cloud/a b"], "offline-path"),
            "/mnt/Cloud/a b",
        )
        self.assertEqual(
            command_line_path(["--offline-path=/mnt/Cloud/a b"], "offline-path"),
            "/mnt/Cloud/a b",
        )
        self.assertEqual(command_line_path(["--background"], "offline-path"), "")

    def test_running_mount_dispatches_without_runtime_discovery(self):
        self.assertEqual(
            availability_route(mounted=True, runtime_ready=False, enabled=True),
            "dispatch",
        )

    def test_cold_mount_queues_until_runtime_is_ready(self):
        self.assertEqual(
            availability_route(mounted=False, runtime_ready=False, enabled=True),
            "queue",
        )
        self.assertEqual(
            availability_route(mounted=False, runtime_ready=True, enabled=True),
            "start-mount",
        )

    def test_file_path_routing_is_lexical_and_never_stats_fuse_item(self):
        with patch.object(Path, "resolve", side_effect=AssertionError("must not resolve FUSE path")):
            self.assertEqual(
                lexical_relative_path(
                    "/mnt/Cloud/reports/rail.pdf", "/mnt/Cloud"
                ),
                "reports/rail.pdf",
            )
            self.assertEqual(lexical_relative_path("/mnt/Cloud", "/mnt/Cloud"), ".")

    def test_file_path_routing_rejects_sibling_prefix(self):
        with self.assertRaises(ValueError):
            lexical_relative_path("/mnt/Cloud-old/file.txt", "/mnt/Cloud")

    def test_only_completed_offline_rules_receive_green_state(self):
        configured = ["first", "second"]
        verified = verified_rules_after(set(), configured, "first", True)
        self.assertEqual(verified, {"first"})
        verified = verified_rules_after(verified, configured, "second", True)
        self.assertEqual(verified, {"first", "second"})
        self.assertEqual(
            verified_rules_after(verified, ["second"], "first", False),
            {"second"},
        )

    def test_verified_root_replaces_child_rules(self):
        self.assertEqual(
            verified_rules_after({"folder/child"}, ["."], ".", True),
            {"."},
        )

    def test_online_only_child_overrides_an_offline_parent(self):
        self.assertTrue(is_available_offline("folder/kept.txt", ["folder"]))
        self.assertFalse(
            is_available_offline("folder/online.txt", ["folder"], ["folder/online.txt"])
        )
        self.assertTrue(
            is_available_offline(
                "folder/online/kept.txt",
                ["folder", "folder/online/kept.txt"],
                ["folder/online"],
            )
        )

    def test_file_rule_never_applies_to_sibling_or_parent(self):
        self.assertTrue(rule_matches("folder/one.txt", "folder/one.txt"))
        self.assertFalse(rule_matches("folder/two.txt", "folder/one.txt"))
        self.assertFalse(rule_matches("folder", "folder/one.txt"))
        self.assertFalse(is_available_offline("folder/two.txt", ["folder/one.txt"]))


if __name__ == "__main__":
    unittest.main()
