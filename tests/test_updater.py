from tests import signal_safety as _signal_safety  # noqa: F401

import hashlib
import json
import tempfile
import base64
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from tuxindrive.updater import UpdateManager, release_package_name, version_key
from tuxindrive.update_helper import PrivilegedUpdateError, stage_verified_package
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.position = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.payload)
        chunk = self.payload[self.position:self.position + size]
        self.position += len(chunk)
        return chunk


class UpdateManagerTests(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = base64.b64encode(self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw,
        )).decode("ascii")

    def release_payload(
        self, version="0.5.1", body=b"deb", url=None,
        expires_at="2999-01-01T00:00:00+00:00", sha256=None,
    ):
        signed = {
            "version": version,
            "url": url or f"https://raw.githubusercontent.com/tpluharik/TuxInDrive/main/dist/tuxindrive_{version}_all.deb",
            "sha256": sha256 or hashlib.sha256(body).hexdigest(),
            "notes": "Test release",
            "expires_at": expires_at,
        }
        canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
        return json.dumps({**signed, "signature": base64.b64encode(self.private.sign(canonical)).decode("ascii")}).encode()

    def test_version_comparison_is_numeric(self):
        self.assertGreater(version_key("0.10.0"), version_key("0.9.9"))
        for invalid in ("", "v", "1.beta.0", "1.-1", "1..0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                version_key(invalid)

    def test_manifest_rejects_tampering_expiry_and_invalid_checksum(self):
        tampered = json.loads(self.release_payload())
        tampered["notes"] = "changed after signing"
        with self.assertRaisesRegex(ValueError, "signature"):
            UpdateManager.parse_manifest(json.dumps(tampered).encode(), self.public)
        for expiry in ("2020-01-01T00:00:00+00:00", "2999-01-01T00:00:00"):
            with self.subTest(expiry=expiry), self.assertRaisesRegex(ValueError, "expired"):
                UpdateManager.parse_manifest(
                    self.release_payload(expires_at=expiry), self.public,
                )
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            UpdateManager.parse_manifest(
                self.release_payload(sha256="z" * 64), self.public,
            )

    def test_platform_package_names_are_bound_to_the_signed_version(self):
        windows_url = "https://github.com/tpluharik/Tuxindrive/releases/download/v0.5.1/TuxInDrive-0.5.1-windows-x64-setup.exe"
        macos_url = "https://github.com/tpluharik/Tuxindrive/releases/download/v0.5.1/TuxInDrive-0.5.1-macos-arm64.dmg"
        windows = UpdateManager.parse_manifest(
            self.release_payload(url=windows_url), self.public, "windows",
        )
        macos = UpdateManager.parse_manifest(
            self.release_payload(url=macos_url), self.public, "macos",
        )
        self.assertEqual(release_package_name(windows, "windows"), windows_url.rsplit("/", 1)[-1])
        self.assertEqual(release_package_name(macos, "macos"), macos_url.rsplit("/", 1)[-1])
        with self.assertRaisesRegex(ValueError, "filename"):
            UpdateManager.parse_manifest(self.release_payload(url=windows_url), self.public, "macos")

    def test_repository_manifest_matches_current_or_staged_debian_release(self):
        """Allow a durable Release asset or the legacy repository package path."""
        from tuxindrive import __version__

        release = UpdateManager.parse_manifest(Path("update/latest-v2.json").read_bytes())
        current = version_key(__version__)
        published = version_key(release.version)
        self.assertEqual(published[:2], current[:2])
        self.assertGreaterEqual(current, published)
        package_name = release_package_name(release, "linux")
        if "/releases/download/" in release.url:
            self.assertIn(f"/releases/download/v{release.version}/", release.url)
        else:
            package = Path("dist") / package_name
            self.assertTrue(package.is_file(), "the signed Debian package must remain available")
            self.assertEqual(release.sha256, hashlib.sha256(package.read_bytes()).hexdigest())

    def test_repository_platform_channels_are_signed_and_version_bound(self):
        """Keep every published platform channel on the current release."""
        from tuxindrive import __version__

        for platform in ("windows", "macos", "android"):
            manifest = Path(f"releases/{platform}/latest-v2.json")
            self.assertTrue(manifest.is_file(), f"missing {platform} update channel")
            release = UpdateManager.parse_manifest(manifest.read_bytes(), target_platform=platform)
            current = version_key(__version__)
            published = version_key(release.version)
            self.assertEqual(published[:2], current[:2])
            self.assertGreaterEqual(current, published)
            self.assertIn(f"/releases/download/v{release.version}/", release.url)
            self.assertEqual(release_package_name(release, platform), release.url.rsplit("/", 1)[-1])

    def test_pre_rebrand_repository_bridge_is_accepted_but_version_mismatch_is_not(self):
        payload = json.loads(self.release_payload())
        payload["url"] = "https://raw.githubusercontent.com/tpluharik/Tuxdrive/main/dist/tuxdrive_0.5.1_all.deb"
        signed = {key: payload[key] for key in ("version", "url", "sha256", "notes", "expires_at")}
        canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
        payload["signature"] = base64.b64encode(self.private.sign(canonical)).decode("ascii")
        self.assertEqual(UpdateManager.parse_manifest(json.dumps(payload).encode(), self.public).version, "0.5.1")
        payload["url"] = payload["url"].replace("0.5.1", "0.5.2")
        signed["url"] = payload["url"]
        canonical = json.dumps(signed, sort_keys=True, separators=(",", ":")).encode()
        payload["signature"] = base64.b64encode(self.private.sign(canonical)).decode("ascii")
        with self.assertRaisesRegex(ValueError, "filename"):
            UpdateManager.parse_manifest(json.dumps(payload).encode(), self.public)

    def test_legacy_bridge_manifest_remains_fixed_at_0191(self):
        """Keep 0.18.1 on its one-step bridge without moving the old trust root."""
        old_public = "xyquZ4Mp8SGBpNiNjEcjhkeaPxBkAOwiBT0AhdhjolU="
        release = UpdateManager.parse_manifest(Path("update/latest.json").read_bytes(), old_public)
        self.assertEqual(release.version, "0.19.1")
        self.assertEqual(release.url.rsplit("/", 1)[-1], "tuxdrive_0.19.1_all.deb")

    def test_manifest_rejects_untrusted_download(self):
        payload = self.release_payload().replace(b"raw.githubusercontent.com/tpluharik/TuxInDrive", b"example.com")
        with self.assertRaises(ValueError):
            UpdateManager.parse_manifest(payload, self.public)

    def test_check_reports_only_newer_version(self):
        manager = UpdateManager("0.5.0", public_key=self.public, target_platform="linux")
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload())):
            self.assertEqual(manager.check().version, "0.5.1")
        with patch("urllib.request.urlopen", return_value=FakeResponse(self.release_payload("0.5.0"))):
            self.assertIsNone(manager.check())

    def test_check_uses_control_plane_lane_and_download_clock(self):
        bandwidth = Mock()
        bandwidth.control_plane_guard.return_value = nullcontext()
        payload = self.release_payload()
        manager = UpdateManager(
            "0.5.0", public_key=self.public, target_platform="linux", bandwidth=bandwidth,
        )
        with patch("urllib.request.urlopen", return_value=FakeResponse(payload)):
            self.assertIsNotNone(manager.check())
        bandwidth.control_plane_guard.assert_called_once_with()
        bandwidth.guard.assert_not_called()
        bandwidth.throttle_download.assert_called_once_with(len(payload))

    def test_download_verifies_checksum(self):
        body = b"valid-debian-package-placeholder"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                target = manager.download(release)
            self.assertEqual(target.read_bytes(), body)

    def test_download_reports_progress(self):
        body = b"progress-data"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        updates = []
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.6.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                manager.download(release, lambda received, total: updates.append((received, total)))
        self.assertTrue(updates)
        self.assertEqual(updates[-1], (len(body), len(body)))

    def test_download_uses_interactive_lane_instead_of_sync_gate(self):
        body = b"interactive-update"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        bandwidth = Mock()
        bandwidth.interactive_transfer_guard.return_value = nullcontext()
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory), bandwidth=bandwidth)
            with patch("urllib.request.urlopen", return_value=FakeResponse(body)):
                manager.download(release)
        bandwidth.interactive_transfer_guard.assert_called_once_with()
        bandwidth.guard.assert_not_called()

    def test_download_reuses_verified_cached_release(self):
        body = b"already-downloaded-and-verified"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        progress = []
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            target = Path(directory) / release_package_name(release)
            target.write_bytes(body)
            with patch("urllib.request.urlopen") as urlopen:
                result = manager.download(release, lambda received, total: progress.append((received, total)))
        urlopen.assert_not_called()
        self.assertEqual(result, target)
        self.assertEqual(progress, [(len(body), len(body))])

    def test_download_removes_bad_partial(self):
        release = UpdateManager.parse_manifest(self.release_payload(body=b"expected"), self.public)
        with tempfile.TemporaryDirectory() as directory:
            manager = UpdateManager("0.5.0", Path(directory))
            with patch("urllib.request.urlopen", return_value=FakeResponse(b"tampered")):
                with self.assertRaises(ValueError):
                    manager.download(release)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_oversized_download_is_removed_before_installation(self):
        body = b"123456"
        release = UpdateManager.parse_manifest(self.release_payload(body=body), self.public)
        with tempfile.TemporaryDirectory() as directory, patch(
            "tuxindrive.updater.MAX_UPDATE_SIZE", 5,
        ), patch("urllib.request.urlopen", return_value=FakeResponse(body)):
            with self.assertRaisesRegex(ValueError, "1 GiB"):
                UpdateManager("0.5.0", Path(directory)).download(release)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_privileged_helper_reverifies_root_owned_copy(self):
        body = b"signed package"
        release = UpdateManager.parse_manifest(self.release_payload(version="0.5.1", body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "tuxindrive_0.5.1_all.deb"
            source.write_bytes(body)
            staged = stage_verified_package(source, root / "staged.deb", release)
            self.assertEqual(staged.read_bytes(), body)

    def test_privileged_helper_rejects_symlink_and_wrong_digest(self):
        body = b"signed package"
        release = UpdateManager.parse_manifest(self.release_payload(version="0.5.1", body=body), self.public)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real = root / "real.deb"
            real.write_bytes(body)
            link = root / "tuxindrive_0.5.1_all.deb"
            link.symlink_to(real)
            with self.assertRaises(PrivilegedUpdateError):
                stage_verified_package(link, root / "stage-one.deb", release)
            link.unlink()
            link.write_bytes(b"replaced after desktop verification")
            with self.assertRaisesRegex(PrivilegedUpdateError, "digest"):
                stage_verified_package(link, root / "stage-two.deb", release)


if __name__ == "__main__":
    unittest.main()
