import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "marketplace_metadata", ROOT / "scripts/generate-marketplace-metadata.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class MarketplaceMetadataTests(unittest.TestCase):
    def test_release_workflow_builds_store_bundle_and_generates_metadata(self):
        workflow = (ROOT / ".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        self.assertIn(":app:bundleStoreRelease", workflow)
        self.assertIn("TuxInDrive-${version}-android-store.aab", workflow)
        self.assertIn("generate-marketplace-metadata.py", workflow)
        self.assertIn("marketplace-metadata.tar.gz", workflow)

    def test_generators_bind_urls_and_checksums_to_exact_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            installer = root / "TuxInDrive-1.2.3-windows-x64-setup.exe"
            deb = root / "tuxindrive_1.2.3_all.deb"
            server_deb = root / "tuxindrive-server_1.2.3_all.deb"
            dmg = root / "TuxInDrive-1.2.3-macos-arm64.dmg"
            for path in (installer, deb, server_deb, dmg):
                path.write_bytes(path.name.encode())

            MODULE.generate_winget(output, "1.2.3", installer)
            MODULE.generate_chocolatey(output, "1.2.3", installer)
            MODULE.generate_aur(output, "1.2.3", deb)
            MODULE.generate_aur_server(output, "1.2.3", server_deb)
            MODULE.generate_homebrew(output, "1.2.3", dmg)

            content = "\n".join(
                path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file()
            )
            self.assertIn("releases/download/v1.2.3", content)
            self.assertIn(MODULE.sha256(installer), content.lower())
            self.assertIn(MODULE.sha256(deb), content.lower())
            self.assertIn(MODULE.sha256(server_deb), content.lower())
            self.assertIn(MODULE.sha256(dmg), content.lower())
            self.assertNotIn("SKIP", content)

    def test_require_one_rejects_missing_or_ambiguous_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaises(SystemExit):
                MODULE.require_one(root, "*.deb")
            (root / "one.deb").write_bytes(b"one")
            (root / "two.deb").write_bytes(b"two")
            with self.assertRaises(SystemExit):
                MODULE.require_one(root, "*.deb")


if __name__ == "__main__":
    unittest.main()
