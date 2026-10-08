from tests import signal_safety as _signal_safety  # noqa: F401

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tuxindrive.bootstrap import BootstrapError, RCLONE_SHA256, install_rclone, resolve_rclone
from tuxindrive import bootstrap


class BootstrapTests(unittest.TestCase):
    def tearDown(self):
        bootstrap._COMPATIBILITY_CACHE.clear()
    def test_explicit_executable_is_preferred(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "rclone"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch("tuxindrive.bootstrap.rclone_compatible", return_value=True):
                self.assertEqual(resolve_rclone(str(executable)), str(executable))

    def test_incompatible_system_rclone_is_rejected(self):
        with patch("tuxindrive.bootstrap.shutil.which", return_value="/usr/bin/rclone"), patch(
            "tuxindrive.bootstrap.Path.is_file", return_value=True
        ), patch("tuxindrive.bootstrap.os.access", return_value=True), patch(
            "tuxindrive.bootstrap.rclone_compatible", return_value=False
        ):
            self.assertIsNone(resolve_rclone())

    def test_release_checksums_cover_supported_architectures(self):
        for system in ("linux", "osx", "windows"):
            self.assertEqual(len(RCLONE_SHA256[(system, "amd64")]), 64)
            self.assertEqual(len(RCLONE_SHA256[(system, "arm64")]), 64)

    @patch("tuxindrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxindrive.bootstrap.platform.system", return_value="Darwin")
    @patch("tuxindrive.bootstrap.platform.machine", return_value="arm64")
    @patch("tuxindrive.bootstrap.urllib.request.urlopen")
    def test_macos_bootstrap_selects_osx_archive(self, urlopen, _machine, _system, _resolve):
        urlopen.side_effect = OSError("offline test")
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.bootstrap.user_rclone_path", return_value=Path(temporary) / "rclone"
        ):
            with self.assertRaises(BootstrapError):
                install_rclone()
        self.assertIn("rclone-v1.75.0-osx-arm64.zip", urlopen.call_args.args[0])

    @patch("tuxindrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxindrive.bootstrap.platform.system", return_value="Windows")
    @patch("tuxindrive.bootstrap.platform.machine", return_value="AMD64")
    @patch("tuxindrive.bootstrap.urllib.request.urlopen")
    def test_windows_bootstrap_selects_verified_exe_archive(self, urlopen, _machine, _system, _resolve):
        urlopen.side_effect = OSError("offline test")
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.bootstrap.user_rclone_path", return_value=Path(temporary) / "rclone.exe"
        ):
            with self.assertRaises(BootstrapError):
                install_rclone()
        self.assertIn("rclone-v1.75.0-windows-amd64.zip", urlopen.call_args.args[0])

    @patch("tuxindrive.bootstrap.resolve_rclone", return_value=None)
    @patch("tuxindrive.bootstrap.platform.machine", return_value="mips64")
    def test_unsupported_architecture_is_explained(self, _machine, _resolve):
        with self.assertRaisesRegex(BootstrapError, "Unsupported CPU architecture"):
            install_rclone()

    def test_compatibility_check_is_cached_and_invalidated_by_binary_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "rclone"
            executable.write_text("one", encoding="utf-8")
            executable.chmod(0o755)
            version = unittest.mock.MagicMock(returncode=0, stdout="rclone v1.75.0\n", stderr="")
            help_result = unittest.mock.MagicMock(returncode=0, stdout="--resilient --recover --resync-mode", stderr="")
            with patch("tuxindrive.bootstrap.subprocess.run", side_effect=[version, help_result]) as run:
                self.assertTrue(bootstrap.rclone_compatible(executable))
                self.assertTrue(bootstrap.rclone_compatible(executable))
                self.assertEqual(run.call_count, 2)
            executable.write_text("replacement-longer", encoding="utf-8")
            with patch("tuxindrive.bootstrap.subprocess.run", side_effect=[version, help_result]) as run:
                self.assertTrue(bootstrap.rclone_compatible(executable))
                self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
