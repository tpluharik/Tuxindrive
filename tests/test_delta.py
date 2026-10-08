from tests import signal_safety as _signal_safety  # noqa: F401

import tempfile
import unittest
from pathlib import Path

from tuxindrive.delta import BlockDeltaPlanner


class BlockDeltaTests(unittest.TestCase):
    def test_only_changed_blocks_are_planned(self):
        planner = BlockDeltaPlanner(64 * 1024)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "large.bin"
            path.write_bytes(b"A" * 65536 + b"B" * 65536 + b"C" * 65536)
            before = planner.signatures(path)
            path.write_bytes(b"A" * 65536 + b"X" * 65536 + b"C" * 65536)
            changed = planner.changed(planner.signatures(path), before)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].offset, 65536)
        self.assertEqual(planner.transferred_bytes(changed), 65536)
