import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


class PackagingTests(unittest.TestCase):
    def test_launcher_points_to_parent_of_installed_package(self):
        launcher = Path("packaging/tuxindrive-launcher").read_text(encoding="utf-8")
        self.assertIn("unset PYTHONPATH PYTHONHOME", launcher)
        self.assertIn("/usr/bin/python3 -I", launcher)
        self.assertIn('sys.path.insert(0,"/usr/lib")', launcher)
        self.assertIn('run_module("tuxindrive.app"', launcher)
        self.assertIn('--system-check', launcher)
        self.assertIn('tuxindrive-doctor', launcher)
        self.assertIn('run_module("tuxindrive.platform_support"', launcher)
        self.assertIn('"tuxdrive-doctor"', launcher)
        self.assertIn('.tuxdrive-encrypted', launcher)

    def test_upgrade_stops_only_the_exact_old_tuxindrive_application(self):
        postinst = Path("packaging/DEBIAN/postinst").read_text(encoding="utf-8")
        self.assertIn('if [ "${1:-}" = "configure" ] && [ -n "${2:-}" ]', postinst)
        self.assertIn('runpy.run_module("tuxindrive.app",run_name="__main__")', postinst)
        self.assertIn('runpy.run_module("tuxdrive.app",run_name="__main__")', postinst)
        self.assertIn('kill -INT "$tuxindrive_pid"', postinst)
        self.assertIn('kill -TERM "$tuxindrive_pid"', postinst)

    def test_build_has_installed_layout_import_smoke_test(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn('PYTHONPATH="$PACKAGE_ROOT/usr/lib"', build_script)
        self.assertIn('find_spec("tuxindrive.app")', build_script)
        self.assertIn('usr/bin/tuxdrive', build_script)
        self.assertIn('tuxdrive.service', build_script)
        self.assertIn('LEGACY_OUTPUT=', build_script)
        self.assertIn('name __pycache__', build_script)

    def test_launchpad_source_packaging_targets_supported_lts_releases(self):
        control = Path("debian/control").read_text(encoding="utf-8")
        rules = Path("debian/rules").read_text(encoding="utf-8")
        source_builder = Path("scripts/build-ppa-source.sh").read_text(encoding="utf-8")
        self.assertIn("Source: tuxindrive", control)
        self.assertIn("Package: tuxdrive", control)
        self.assertIn("debhelper-compat (= 13)", control)
        self.assertIn("dpkg-deb -x", rules)
        self.assertIn("jammy|noble|resolute", source_builder)
        self.assertIn("dpkg-buildpackage -S -sa", source_builder)
        self.assertIn("_source.buildinfo", source_builder)
        self.assertIn("TUXINDRIVE_PPA_GPG_FINGERPRINT", source_builder)
        self.assertIn('"$source_dir/dist"', source_builder)
        self.assertIn("TUXINDRIVE_PPA_ORIG", source_builder)
        self.assertIn('cp -a "$project_root/debian" "$packaging_dir"', source_builder)
        self.assertIn('tar -xzf "$work_root/tuxindrive_${upstream_version}.orig.tar.gz"', source_builder)
        self.assertIn("gzip -n", source_builder)
        self.assertNotIn("BEGIN PGP PRIVATE KEY", source_builder)
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("ppa:tpluharik77/tuxindrive", readme)
        self.assertIn("sudo apt install tuxdrive", readme)

    def test_snapcraft_package_is_classic_versioned_and_credential_scoped(self):
        from tuxindrive import __version__

        snapcraft = Path("snap/snapcraft.yaml").read_text(encoding="utf-8")
        workflow = Path(".github/workflows/snapcraft-publish.yml").read_text(encoding="utf-8")
        self.assertIn("name: tuxindrive", snapcraft)
        self.assertIn(f'version: "{__version__}"', snapcraft)
        self.assertIn("confinement: classic", snapcraft)
        self.assertIn("      - python3\n", snapcraft)
        self.assertIn("      - python3-venv\n", snapcraft)
        self.assertIn("      - python3.12-minimal\n", snapcraft)
        self.assertIn("      - libpython3.12-stdlib\n", snapcraft)
        self.assertIn("      - enable-patchelf\n", snapcraft)
        self.assertIn("SNAPCRAFT_STORE_CREDENTIALS", workflow)
        self.assertNotIn("BEGIN PRIVATE", snapcraft + workflow)

    def test_debian_identity_is_an_explicit_signed_updater_compatibility_abi(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        self.assertIn("Package: tuxdrive", control)
        from tuxindrive import __version__
        self.assertIn(f"Version: {__version__}", control)
        self.assertIn(f"Provides: tuxindrive (= {__version__})", control)
        helper = Path("packaging/tuxindrive-rclone-password").read_text(encoding="utf-8")
        self.assertIn("lookup application tuxdrive purpose rclone-config", helper)

    def test_gtk3_and_gdk3_are_pinned_before_repository_import(self):
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        gdk_requirement = 'gi.require_version("Gdk", "3.0")'
        gtk_requirement = 'gi.require_version("Gtk", "3.0")'
        repository_import = "from gi.repository import Gtk, Gdk, Gio, GLib"
        self.assertIn(gdk_requirement, app)
        self.assertIn(gtk_requirement, app)
        self.assertIn(repository_import, app)
        self.assertLess(app.index(gdk_requirement), app.index(repository_import))
        self.assertLess(app.index(gtk_requirement), app.index(repository_import))

    def test_peer_runtime_and_key_generator_are_installed(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("openssh-client", control)
        self.assertIn("qrencode", control)
        self.assertIn("zbar-tools", control)
        self.assertIn("poppler-utils", control)
        self.assertIn('find_spec("tuxindrive.peer")', build_script)
        self.assertIn('docs/TESTING.md', build_script)
        self.assertIn('docs/ROADMAP.md', build_script)
        self.assertIn("python3-cryptography", control)
        self.assertIn("python3-defusedxml", control)
        self.assertIn("libsecret-tools", control)
        self.assertIn("tuxindrive-rclone-password", build_script)
        self.assertIn('find_spec("tuxindrive.migration")', build_script)
        self.assertIn("tuxindrive-update-helper", build_script)
        self.assertIn('find_spec("tuxindrive.update_helper")', build_script)
        self.assertIn('find_spec("tuxindrive.github_sync")', build_script)
        self.assertIn('find_spec("tuxindrive.proton")', build_script)

    def test_linux_profile_migration_uses_packaged_secret_service_backend(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        helper = Path("src/tuxindrive/password_helper.py").read_text(encoding="utf-8")
        self.assertIn("libsecret-tools", control)
        self.assertIn('SECRET_TOOL = "/usr/bin/secret-tool"', helper)
        self.assertIn('input=password', helper)
        self.assertNotIn('python3-keyring', control)

    def test_all_provider_icons_are_packaged(self):
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        for provider in ("dropbox", "box", "pcloud", "mega", "proton-drive", "nextcloud", "github"):
            self.assertTrue(Path(f"packaging/tuxindrive-{provider}.svg").exists())
        self.assertIn("dropbox box pcloud mega proton-drive nextcloud github", build_script)
        self.assertIn("git", Path("packaging/DEBIAN/control").read_text(encoding="utf-8"))

    def test_primary_brand_assets_cover_every_platform(self):
        for asset in (
            "branding/tuxindrive-logo.png",
            "branding/tuxindrive-icon.ico",
            "branding/tuxindrive-icon.icns",
            "packaging/tuxindrive.svg",
            "packaging/tuxindrive-sync.svg",
            "packaging/tuxindrive-error.svg",
            "android/app/src/main/res/drawable-nodpi/tuxindrive_logo.png",
            "android/app/src/main/res/drawable-nodpi/tuxindrive_logo_monochrome.png",
        ):
            self.assertTrue(Path(asset).is_file(), asset)
        logo = Path("packaging/tuxindrive.svg").read_text(encoding="utf-8")
        self.assertIn("#e31b23", logo)
        self.assertIn("circular penguin with red bow tie", logo)
        foreground = Path("android/app/src/main/res/drawable/ic_launcher_foreground.xml").read_text(encoding="utf-8")
        monochrome = Path("android/app/src/main/res/drawable/ic_launcher_monochrome.xml").read_text(encoding="utf-8")
        self.assertIn("@drawable/tuxindrive_logo", foreground)
        self.assertIn("@drawable/tuxindrive_logo_monochrome", monochrome)

    def test_nautilus_extension_is_packaged_with_safe_app_actions(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        extension = Path("packaging/nautilus-extension-tuxindrive.py").read_text(encoding="utf-8")
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        self.assertIn("Recommends: python3-nautilus", control)
        self.assertIn("usr/share/nautilus-python/extensions", build_script)
        self.assertNotIn('gi.require_version("Nautilus"', extension)
        self.assertIn('group.activate_action(action, parameter)', extension)
        self.assertIn('"open-online-path"', extension)
        self.assertIn("nautilus-state.json", extension)
        self.assertIn('get("nautilus_integration", True)', extension)
        self.assertIn('"--offline-path"', extension)
        self.assertIn('"--online-only-path"', extension)
        self.assertNotIn("resolve(strict=False)", extension)
        self.assertIn('(\"sync-path\", self._nautilus_sync_path)', app)
        self.assertIn('(\"open-online-path\", self._nautilus_open_online)', app)
        self.assertIn('(\"offline-path\", self._nautilus_keep_offline)', app)
        self.assertIn('(\"online-only-path\", self._nautilus_make_online_only)', app)
        self.assertIn('_desktop_open_command(url)', app)
        self.assertIn("Gio.ApplicationFlags.HANDLES_COMMAND_LINE", app)
        self.assertIn('if action == "open-online-path"', extension)
        self.assertIn("def do_command_line", app)
        self.assertIn("command_line_path(arguments, name)", app)
        self.assertIn("_request_offline_path", app)
        self.assertIn('name.startswith(("config-", "nautilus-state-"))', extension)
        self.assertNotIn("self.activate()\n        if not self._runtime_ready_once:\n            self._pending_nautilus_online", app)
        self.assertIn("_publish_nautilus_state", app)
        self.assertIn("_pending_nautilus_paths", app)
        self.assertIn('"configured_offline_paths"', app)
        self.assertIn('"online_only_paths"', app)
        self.assertIn('"__tuxindrive__"', extension)
        self.assertIn("Prefer the small extension snapshot", extension)
        self.assertIn("_LAST_VALID_JOBS", extension)
        self.assertIn("len(paths) == 1", extension)
        self.assertIn('relative == rule or relative.startswith(rule.rstrip("/") + "/")', extension)
        self.assertNotIn("from tuxindrive", extension)
        self.assertIn("without remounting", app)
        self.assertNotIn("policy_result = self.engine.restart_mount", app)
        self.assertIn("Reconnects must never trigger an implicit download", app)
        self.assertIn("Do not mount the cloud merely to make it online-only", app)
        self.assertIn("dispatch that exact", app)
        self.assertIn("verified_offline_rules(job)", app)
        self.assertNotIn("for relative in list(job.offline_paths)", app)

    def test_nautilus_info_provider_completes_and_packages_emblems(self):
        extension = Path("packaging/nautilus-extension-tuxindrive.py").read_text(encoding="utf-8")
        build_script = Path("scripts/build-deb.sh").read_text(encoding="utf-8")
        self.assertIn("def update_file_info_full", extension)
        self.assertIn("Nautilus.OperationResult.COMPLETE", extension)
        for state in ("synced", "syncing", "streaming", "paused", "pending", "error"):
            self.assertTrue(Path(f"packaging/emblem-tuxindrive-{state}.svg").exists())
            self.assertIn(f'emblem-tuxdrive-${{STATE}}.svg', build_script)
        self.assertIn('file_info.add_emblem(emblem)', extension)
        self.assertIn('f"emblem-tuxindrive-{state}"', extension)
        self.assertIn("scalable/emblems", build_script)

    def test_job_action_opens_online_folder_without_creating_share_link(self):
        app = Path("src/tuxindrive/app.py").read_text(encoding="utf-8")
        i18n = Path("src/tuxindrive/i18n.py").read_text(encoding="utf-8")
        self.assertIn('Gtk.Button(label=tr("open_online_folder"))', app)
        self.assertIn('self.controller._open_online_path(str(job.local))', app)
        self.assertNotIn('Gtk.Button(label=tr("share_link"))', app)
        self.assertNotIn("def _share_job", app)
        self.assertNotIn("Creating a provider share link", app)
        self.assertIn('account.provider is Provider.PROTON_DRIVE and account.backend == "proton_cli"', app)
        self.assertIn("does not\n            # currently publish a stable private web-route contract", app)
        self.assertNotIn('"share_link":', i18n)
        self.assertEqual(i18n.count('"open_online_folder":'), 6)

    def test_nautilus_emblems_are_unbranded_and_visually_distinct(self):
        palette = {
            "synced": "#15803D",
            "syncing": "#1565C0",
            "streaming": "#00838F",
            "paused": "#6D28D9",
            "pending": "#D97706",
            "error": "#C62828",
        }
        descriptions: set[str] = set()
        for state, color in palette.items():
            path = Path(f"packaging/emblem-tuxindrive-{state}.svg")
            source = path.read_text(encoding="utf-8")
            root = ET.fromstring(source)
            self.assertEqual(root.attrib.get("data-state"), state)
            self.assertIn(color, source)
            self.assertNotIn("#20252b", source.lower())
            self.assertNotIn("#f4a51c", source.lower())
            description = root.find("{http://www.w3.org/2000/svg}desc")
            self.assertIsNotNone(description)
            descriptions.add(description.text or "")
        self.assertEqual(len(set(palette.values())), len(palette))
        self.assertEqual(len(descriptions), len(palette))

    def test_optional_integrations_do_not_block_core_install(self):
        control = Path("packaging/DEBIAN/control").read_text(encoding="utf-8")
        depends, recommends = control.split("Depends: ", 1)[1].split("\n", 1)[0], control.split("Recommends: ", 1)[1].split("\n", 1)[0]
        for package in ("python3-nautilus", "fuse3", "tor", "obfs4proxy", "natpmpc"):
            self.assertNotIn(package, depends)
            self.assertIn(package, recommends)
        self.assertIn("install-capabilities.json", Path("packaging/DEBIAN/postinst").read_text(encoding="utf-8"))

    def test_release_workflows_cover_all_packaged_platforms(self):
        workflow = Path(".github/workflows/build.yml").read_text(encoding="utf-8")
        self.assertIn("Build Debian package", workflow)
        platforms = Path(".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: windows-latest", platforms)
        self.assertIn("runs-on: macos-14", platforms)
        self.assertIn("name: tuxindrive-android", platforms)
        self.assertIn(":app:testSideloadDebugUnitTest", platforms)
        self.assertIn(":app:testSideloadReleaseUnitTest", platforms)
        self.assertIn("golang.org/x/mobile/cmd/gobind@v0.0.0-20260709172247-6129f5bee9d5", platforms)
        self.assertNotIn('"${HOME}/go/bin/gomobile" init', platforms)
        self.assertIn("sh scripts/build-server-deb.sh", platforms)
        self.assertIn('tuxindrive-server_${version}_all.deb', platforms)
        self.assertTrue(Path("scripts/build-windows.ps1").is_file())
        self.assertTrue(Path("scripts/build-macos.sh").is_file())
        self.assertTrue(Path("packaging/windows/TuxInDrive.iss").is_file())
        self.assertTrue(Path("android/app/src/main/AndroidManifest.xml").is_file())
        manifest = Path("android/app/src/main/AndroidManifest.xml").read_text(encoding="utf-8")
        sideload_manifest = Path("android/app/src/sideload/AndroidManifest.xml").read_text(encoding="utf-8")
        self.assertNotIn("REQUEST_INSTALL_PACKAGES", manifest)
        self.assertIn("REQUEST_INSTALL_PACKAGES", sideload_manifest)
        self.assertIn('android:usesCleartextTraffic="false"', manifest)
        self.assertTrue(Path("android/app/src/main/res/xml/network_security_config.xml").is_file())
        self.assertTrue(Path("android/app/src/main/java/io/github/tuxindrive/mobile/NetworkUsageMeter.kt").is_file())
        update_worker = Path(
            "android/app/src/main/java/io/github/tuxindrive/mobile/AndroidUpdateWorker.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("PeriodicWorkRequestBuilder<AndroidUpdateWorker>", update_worker)
        self.assertIn("repository.checkUpdate()", update_worker)
        self.assertIn("repository.downloadUpdate(update)", update_worker)
        self.assertIn("repository.updateInstallerIntent(packageFile)", update_worker)
        self.assertIn("setRequiresBatteryNotLow(true)", update_worker)
        android_updater = Path(
            "android/app/src/main/java/io/github/tuxindrive/mobile/AndroidUpdater.kt"
        ).read_text(encoding="utf-8")
        self.assertIn("sha256(target) == update.sha256", android_updater)
        self.assertIn("verified update cache", android_updater)
        self.assertTrue(Path("android/app/src/test/java/io/github/tuxindrive/mobile/MobileValidationTest.kt").is_file())

    def test_chocolatey_publication_is_secret_backed_and_fail_closed(self):
        workflow = Path(".github/workflows/chocolatey-publish.yml").read_text(encoding="utf-8")
        self.assertIn("environment: release", workflow)
        self.assertIn("secrets.CHOCOLATEY_API_KEY", workflow)
        self.assertIn("Get-AuthenticodeSignature", workflow)
        self.assertIn("signature.Status -ne 'Valid'", workflow)
        self.assertIn("Get-FileHash $installer -Algorithm SHA256", workflow)
        self.assertIn("Chocolatey clean-install test failed", workflow)
        self.assertIn("Chocolatey uninstall test failed", workflow)
        self.assertIn("https://push.chocolatey.org/", workflow)
        self.assertNotIn("tpluharik@gmail.com", workflow)

    def test_public_code_signing_policy_is_complete_and_linked(self):
        policy = Path("docs/CODE_SIGNING_POLICY.md").read_text(encoding="utf-8")
        downloads = Path("docs/DOWNLOADS.md").read_text(encoding="utf-8")
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertIn("# Code signing policy", policy)
        self.assertIn("Free code signing is provided by SignPath.io", policy)
        self.assertIn("certificate is provided by\nSignPath Foundation", policy)
        self.assertIn("Signing approver", policy)
        self.assertIn("multi-factor authentication", policy)
        self.assertIn("GitHub-hosted runners", policy)
        self.assertIn("does not transfer information", policy)
        self.assertIn("SignPath.io", downloads)
        self.assertIn("docs/DOWNLOADS.md", readme)
        self.assertIn("docs/CODE_SIGNING_POLICY.md", readme)

    def test_platform_release_channels_are_durable_and_version_bound(self):
        from tuxindrive import __version__

        platforms = Path(".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        for platform in ("windows", "macos", "android"):
            self.assertTrue(Path(f"releases/{platform}/packages/README.md").is_file())
            channel = Path(f"releases/{platform}/README.md").read_text(encoding="utf-8")
            self.assertIn("releases/download/vVERSION/", channel)
        self.assertIn('release_tag="$GITHUB_REF_NAME"', platforms)
        self.assertIn('test "$release_tag" = "v$version"', platforms)
        self.assertIn('release_tag="v$version"', platforms)
        self.assertIn("github.ref == 'refs/heads/main'", platforms)
        self.assertIn("SHA256SUMS.txt", platforms)
        self.assertIn("environment: release", platforms)
        self.assertIn("HOMEBREW_NO_AUTO_UPDATE", platforms)
        self.assertIn("update: false", platforms)
        self.assertIn("python.cdx.json", platforms)
        self.assertTrue(Path("requirements-ci.txt").is_file())
        self.assertTrue(Path("requirements-release.txt").is_file())
        self.assertIn('gh release upload "$RELEASE_TAG" "${packages[@]}" --clobber', platforms)
        self.assertIn('--target "$GITHUB_SHA"', platforms)
        self.assertIn(f'version = "{__version__}"', Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn(f'versionName = "{__version__}"', Path("android/app/build.gradle.kts").read_text(encoding="utf-8"))
        self.assertIn(
            f"versionCode = {int(__version__.replace('.', ''))}",
            Path("android/app/build.gradle.kts").read_text(encoding="utf-8"),
        )
        self.assertIn(f'#define AppVersion "{__version__}"', Path("packaging/windows/TuxInDrive.iss").read_text(encoding="utf-8"))
        self.assertIn(
            "SetupIconFile=..\\..\\branding\\tuxindrive-icon.ico",
            Path("packaging/windows/TuxInDrive.iss").read_text(encoding="utf-8"),
        )

    def test_native_build_paths_match_ci_runner_layout(self):
        platforms = Path(".github/workflows/platform-packages.yml").read_text(encoding="utf-8")
        windows = Path("scripts/build-windows.ps1").read_text(encoding="utf-8")
        macos = Path("scripts/build-macos.sh").read_text(encoding="utf-8")
        self.assertIn("mingw-w64-ucrt-x86_64-pyinstaller", platforms)
        self.assertNotIn("mingw-w64-ucrt-x86_64-python-pyinstaller", platforms)
        self.assertIn("mkdir -p android/app/libs", platforms)
        self.assertIn("test -s \"${GITHUB_WORKSPACE}/android/app/libs/rclone.aar\"", platforms)
        self.assertNotIn("cygpath", windows)
        self.assertIn('if ($LASTEXITCODE -ne 0)', windows)
        self.assertIn("PackageOnly", windows)
        self.assertIn("VERSION=$(sed", Path("scripts/build-deb.sh").read_text(encoding="utf-8"))
        windows_msys2 = Path("scripts/build-windows-msys2.sh").read_text(encoding="utf-8")
        self.assertIn('--specpath build', windows_msys2)
        self.assertIn('--add-data "../branding/tuxindrive-logo.png:branding"', windows_msys2)
        self.assertIn('--icon "../branding/tuxindrive-icon.ico"', windows_msys2)
        self.assertTrue((Path("build") / "../branding/tuxindrive-logo.png").resolve().is_file())
        self.assertTrue((Path("build") / "../branding/tuxindrive-icon.ico").resolve().is_file())
        self.assertNotIn('$project_root/branding/tuxindrive-logo.png', windows_msys2)
        self.assertIn("test -s build/windows/TuxInDrive/TuxInDrive.exe", windows_msys2)
        self.assertIn("run: sh scripts/build-windows-msys2.sh", platforms)
        self.assertIn("run: scripts/build-windows.ps1 -PackageOnly", platforms)
        self.assertIn('$project_root/branding/tuxindrive-logo.png', macos)
        self.assertIn('--icon "$project_root/branding/tuxindrive-icon.icns"', macos)
        self.assertTrue(Path("branding/tuxindrive-icon.icns").is_file())
        android_build = Path("android/app/build.gradle.kts").read_text(encoding="utf-8")
        self.assertIn('create("sideload")', android_build)
        self.assertIn('create("store")', android_build)
        self.assertIn('SELF_UPDATE_ENABLED', android_build)
        self.assertIn("sourceCompatibility = JavaVersion.VERSION_17", android_build)
        self.assertIn("targetCompatibility = JavaVersion.VERSION_17", android_build)
        self.assertIn("jvmToolchain(17)", android_build)


if __name__ == "__main__":
    unittest.main()
