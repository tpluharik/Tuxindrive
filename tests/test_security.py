from tests import signal_safety as _signal_safety  # noqa: F401

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

from tuxindrive.security import (
    UnsafePathError, confined_path, copy_from_confined, install_confined,
    safe_relative, sign_json, unlink_confined, verify_signed_json,
)


class SecurityBoundaryTests(unittest.TestCase):
    def test_relative_path_validation_rejects_empty_absolute_and_traversal_values(self):
        for value in ("", "/etc/passwd", "../secret", "folder/../../secret", "."):
            with self.subTest(value=value), self.assertRaises(UnsafePathError):
                safe_relative(value)
        self.assertEqual(safe_relative("folder/./file.txt"), Path("folder/file.txt"))

    def test_confined_path_rejects_parent_and_symlink_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root, outside = base / "root", base / "outside"
            root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                confined_path(root, "../outside/file")
            with self.assertRaises((UnsafePathError, OSError)):
                confined_path(root, "link/file", create_parents=True)

    def test_signed_json_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temporary:
            private = Ed25519PrivateKey.generate()
            path = Path(temporary) / "identity"
            path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            value = {"path": "document.odt", "size": 42}
            public, signature = sign_json(value, path)
            verify_signed_json(value, public, signature)
            with self.assertRaises(Exception):
                verify_signed_json({**value, "size": 43}, public, signature)

    def test_delta_signing_rejects_non_ed25519_private_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "identity"
            private = generate_private_key(public_exponent=65537, key_size=2048)
            path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                serialization.NoEncryption(),
            ))
            with self.assertRaisesRegex(ValueError, "Ed25519"):
                sign_json({"path": "file"}, path)

    def test_posix_confined_install_copy_and_unlink_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Linux",
        ):
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            source = base / "source"
            source.write_bytes(b"payload")
            installed = install_confined(source, root, "nested/file.bin")
            exported = base / "exported"
            copy_from_confined(root, "nested/file.bin", exported)
            self.assertEqual((installed.read_bytes(), exported.read_bytes()), (b"payload", b"payload"))
            unlink_confined(root, "nested/file.bin")
            self.assertFalse(installed.exists())

    def test_copy_refuses_a_symlink_source(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Linux",
        ):
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            outside = base / "outside"
            outside.write_bytes(b"secret")
            (root / "link").symlink_to(outside)
            with self.assertRaises(OSError):
                copy_from_confined(root, "link", base / "copy")

    def test_windows_confined_file_operations_round_trip(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Windows"
        ):
            base = Path(temporary)
            root = base / "root"
            root.mkdir()
            source = base / "source"
            source.write_bytes(b"portable payload")
            installed = install_confined(source, root, "folder/file.bin")
            self.assertEqual(installed.read_bytes(), b"portable payload")
            exported = base / "exported"
            copy_from_confined(root, "folder/file.bin", exported)
            self.assertEqual(exported.read_bytes(), b"portable payload")
            unlink_confined(root, "folder/file.bin")
            self.assertFalse(installed.exists())

    def test_windows_confined_path_rejects_reparse_parent(self):
        with tempfile.TemporaryDirectory() as temporary, patch(
            "tuxindrive.security.platform.system", return_value="Windows"
        ):
            base = Path(temporary)
            root, outside = base / "root", base / "outside"
            root.mkdir(); outside.mkdir()
            (root / "link").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                confined_path(root, "link/file.bin", create_parents=True)


if __name__ == "__main__":
    unittest.main()
