from tests import signal_safety as _signal_safety  # noqa: F401

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_distribution", ROOT / "scripts/verify-native-distribution.py")
NATIVE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NATIVE)


class CiWorkflowTests(unittest.TestCase):
    def test_reliability_installs_same_hashed_inputs_before_execution(self):
        build = (ROOT / ".github/workflows/build.yml").read_text()
        reliability = (ROOT / ".github/workflows/reliability.yml").read_text()
        inputs = [line.strip() for line in build.splitlines() if line.strip().startswith("python -m pip install ")]
        self.assertEqual(len(inputs), 3)
        for line in inputs:
            self.assertIn(line, reliability)
            self.assertLess(reliability.index(line), reliability.index("scripts/run-reliability-matrix.py"))
        self.assertIn("--files 5000", reliability)
        self.assertIn("--files 1000 --content", reliability)
        self.assertIn("if-no-files-found: error", reliability)
        for filename in ("reliability-report.json", "search-benchmark.json", "search-content-benchmark.json"):
            self.assertIn("dist/" + filename, reliability)

    def test_all_external_action_references_are_full_immutable_commits(self):
        count = 0
        for path in (ROOT / ".github").rglob("*"):
            if path.suffix not in {".yml", ".yaml"}:
                continue
            for reference in re.findall(r"(?m)^\s*(?:-\s*)?uses:\s*([^\s#]+)", path.read_text()):
                if reference.startswith("./"):
                    continue
                with self.subTest(path=path, action=reference):
                    self.assertRegex(reference, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
                count += 1
        self.assertGreater(count, 10)

    def test_native_gates_are_wired_without_loading_private_credentials(self):
        workflow = (ROOT / ".github/workflows/platform-packages.yml").read_text()
        for name, start, end in (("windows", "windows", "macos"), ("macos", "macos", "android-verification")):
            job = workflow.split("\n  " + start + ":\n")[1].split("\n  " + end + ":\n")[0]
            self.assertIn("verify-native-distribution.py --platform " + name, job)
            self.assertIn("TUXINDRIVE_REQUIRE_" + name.upper() + "_SIGNING || '0'", job)
            self.assertLess(job.index("verify-native-distribution.py"), job.index("name: tuxindrive-" + name))
            self.assertNotIn("secrets.", job)
        self.assertNotIn("notarytool submit", workflow)
        self.assertIn("--options runtime", (ROOT / "scripts/build-macos.sh").read_text())

    def test_required_mode_is_explicit_and_deferred_mode_does_not_verify(self):
        self.assertFalse(NATIVE.required({}, "WINDOWS"))
        self.assertTrue(NATIVE.required({"TUXINDRIVE_REQUIRE_WINDOWS_SIGNING": "1"}, "WINDOWS"))
        with self.assertRaises(ValueError):
            NATIVE.required({"TUXINDRIVE_REQUIRE_WINDOWS_SIGNING": "true"}, "WINDOWS")
        with mock.patch.dict(NATIVE.os.environ, {}, clear=True), mock.patch.object(sys, "argv",
                ["verify-native-distribution", "--platform", "windows", "--version", "0.26.81"]), \
                mock.patch.object(NATIVE, "command") as command, contextlib.redirect_stdout(io.StringIO()) as output:
            NATIVE.main()
        command.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "pending-not-configured")
        self.assertFalse(json.loads(output.getvalue())["native_signature_verified"])

    def test_windows_requires_pinned_timestamped_trusted_identity(self):
        with self.assertRaises(ValueError):
            NATIVE.verify_windows(Path("dist"), "0.26.81", {})
        for result in ({"status": "NotSigned", "sha256": "a" * 64, "timestamp": True},
                {"status": "Valid", "sha256": "b" * 64, "timestamp": True},
                {"status": "Valid", "sha256": "a" * 64, "timestamp": False}):
            with self.subTest(result=result), mock.patch.object(NATIVE.platform, "system", return_value="Windows"), \
                    mock.patch.object(NATIVE, "command", return_value=json.dumps(result)), self.assertRaises(ValueError):
                NATIVE.verify_windows(Path("dist"), "0.26.81", {"TUXINDRIVE_WINDOWS_CERT_SHA256": "a" * 64})

    def test_windows_portable_entrypoints_are_verified_and_duplicates_rejected(self):
        valid = json.dumps({"status": "Valid", "sha256": "a" * 64, "timestamp": True})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(NATIVE.platform, "system", return_value="Windows"), \
                mock.patch.object(NATIVE, "command", return_value=valid) as command:
            root = Path(temporary)
            archive = root / "TuxInDrive-0.26.81-windows-x64-portable.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("TuxInDrive.exe", b"synthetic only")
                output.writestr("tuxindrive-rclone-password.exe", b"synthetic only")
            NATIVE.verify_windows(root, "0.26.81", {"TUXINDRIVE_WINDOWS_CERT_SHA256": "a" * 64})
            self.assertEqual(command.call_count, 3)
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("../../TuxInDrive.exe", b"synthetic only")
            with self.assertRaisesRegex(ValueError, "entry point"):
                NATIVE.verify_windows(root, "0.26.81", {"TUXINDRIVE_WINDOWS_CERT_SHA256": "a" * 64})

    def test_macos_identity_rejects_adhoc_wrong_team_and_missing_runtime(self):
        valid = "TeamIdentifier=ABCDE12345\nAuthority=Developer ID Application: Test\nCodeDirectory flags=0x10000(runtime)\n"
        NATIVE.mac_identity(valid, "ABCDE12345", True)
        for value in (valid.replace("ABCDE12345", "ZZZZZ12345"), valid.replace("runtime", "none"),
                valid + "Signature=adhoc\n", valid.replace("Developer ID Application:", "Apple Development:")):
            with self.subTest(details=value), self.assertRaises(ValueError):
                NATIVE.mac_identity(value, "ABCDE12345", True)

    def test_macos_requires_gatekeeper_and_stapled_ticket(self):
        valid = "TeamIdentifier=ABCDE12345\nAuthority=Developer ID Application: Test\nCodeDirectory flags=0x10000(runtime)\n"
        with self.assertRaises(ValueError):
            NATIVE.verify_macos(Path("dist"), "0.26.81", Path("app"), {})
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(NATIVE.platform, "system", return_value="Darwin"):
            root = Path(temporary)
            (root / "TuxInDrive-0.26.81-macos-arm64.dmg").touch()
            with mock.patch.object(NATIVE, "command", return_value=valid) as command:
                NATIVE.verify_macos(root, "0.26.81", root / "app", {"TUXINDRIVE_APPLE_TEAM_ID": "ABCDE12345"})
                calls = [call.args[0] for call in command.call_args_list]
                self.assertTrue(any(c[:3] == ["xcrun", "stapler", "validate"] for c in calls))
                self.assertEqual(sum(c[0] == "spctl" for c in calls), 2)
            def reject_ticket(args):
                if args[:3] == ["xcrun", "stapler", "validate"]:
                    raise ValueError("Not notarized")
                return valid
            with mock.patch.object(NATIVE, "command", side_effect=reject_ticket), self.assertRaisesRegex(ValueError, "Not notarized"):
                NATIVE.verify_macos(root, "0.26.81", root / "app", {"TUXINDRIVE_APPLE_TEAM_ID": "ABCDE12345"})


if __name__ == "__main__":
    unittest.main()
