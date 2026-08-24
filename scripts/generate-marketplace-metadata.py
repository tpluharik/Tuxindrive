#!/usr/bin/env python3
"""Generate package-manager submissions from immutable release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


REPOSITORY = "https://github.com/tpluharik/Tuxindrive"
IDENTIFIER = "TuxInDrive.TuxInDrive"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_version(root: Path) -> str:
    source = (root / "src/tuxindrive/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$', source, re.MULTILINE)
    if not match:
        raise SystemExit("Could not read the TuxInDrive version")
    return match.group(1)


def require_one(asset_dir: Path, pattern: str) -> Path:
    matches = sorted(asset_dir.rglob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one {pattern!r} below {asset_dir}, found {len(matches)}")
    return matches[0]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def generate_winget(output: Path, version: str, installer: Path) -> None:
    base = output / "winget" / "manifests" / "t" / "TuxInDrive" / "TuxInDrive" / version
    url = f"{REPOSITORY}/releases/download/v{version}/{installer.name}"
    checksum = sha256(installer).upper()
    write(base / f"{IDENTIFIER}.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.9.0
""")
    write(base / f"{IDENTIFIER}.installer.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
InstallerType: inno
Scope: machine
InstallModes:
  - interactive
  - silent
  - silentWithProgress
UpgradeBehavior: install
Installers:
  - Architecture: x64
    InstallerUrl: {url}
    InstallerSha256: {checksum}
ManifestType: installer
ManifestVersion: 1.9.0
""")
    write(base / f"{IDENTIFIER}.locale.en-US.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
PackageLocale: en-US
Publisher: TuxInDrive contributors
PublisherUrl: {REPOSITORY}
PublisherSupportUrl: {REPOSITORY}/issues
PackageName: TuxInDrive
PackageUrl: {REPOSITORY}
License: MIT
LicenseUrl: {REPOSITORY}/blob/v{version}/LICENSE
ShortDescription: Multi-provider cloud synchronization, streaming, and encrypted peer sharing
Description: TuxInDrive connects cloud providers, GitHub repositories, files-on-demand drives, and explicitly approved encrypted peer workspaces from one desktop application.
Tags:
  - backup
  - cloud
  - file-sync
  - rclone
  - synchronization
ReleaseNotesUrl: {REPOSITORY}/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: 1.9.0
""")


def generate_chocolatey(output: Path, version: str, installer: Path) -> None:
    package = output / "chocolatey" / "tuxindrive"
    url = f"{REPOSITORY}/releases/download/v{version}/{installer.name}"
    checksum = sha256(installer)
    write(package / "tuxindrive.nuspec", f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd">
  <metadata>
    <id>tuxindrive</id>
    <version>{version}</version>
    <title>TuxInDrive</title>
    <authors>TuxInDrive contributors</authors>
    <projectUrl>{REPOSITORY}</projectUrl>
    <license type="expression">MIT</license>
    <requireLicenseAcceptance>false</requireLicenseAcceptance>
    <projectSourceUrl>{REPOSITORY}</projectSourceUrl>
    <bugTrackerUrl>{REPOSITORY}/issues</bugTrackerUrl>
    <tags>tuxindrive cloud sync rclone backup files</tags>
    <summary>Multi-provider cloud synchronization and encrypted peer sharing.</summary>
    <description>TuxInDrive provides cloud synchronization, files-on-demand streaming, GitHub integration, and explicitly approved encrypted peer workspaces.</description>
    <releaseNotes>{REPOSITORY}/releases/tag/v{version}</releaseNotes>
  </metadata>
</package>
""")
    write(package / "tools" / "chocolateyinstall.ps1", f"""
$ErrorActionPreference = 'Stop'
$packageArgs = @{{
  packageName    = 'tuxindrive'
  fileType       = 'exe'
  url64bit       = '{url}'
  checksum64     = '{checksum}'
  checksumType64 = 'sha256'
  silentArgs     = '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-'
  validExitCodes = @(0, 3010, 1641)
}}
Install-ChocolateyPackage @packageArgs
""")


def generate_aur(output: Path, version: str, deb: Path) -> None:
    package = output / "aur" / "tuxindrive-bin"
    url = f"{REPOSITORY}/releases/download/v{version}/{deb.name}"
    write(package / "PKGBUILD", f"""
pkgname=tuxindrive-bin
pkgver={version}
pkgrel=1
pkgdesc='Multi-provider cloud synchronization, streaming, and encrypted peer sharing'
arch=('any')
url='{REPOSITORY}'
license=('MIT')
depends=('python>=3.10' 'python-gobject' 'gtk3' 'python-cryptography' 'python-defusedxml' 'libsecret' 'xdg-utils' 'ca-certificates' 'git')
optdepends=('python-nautilus: Nautilus status and context-menu integration'
            'fuse3: files-on-demand virtual drives'
            'tor: Tor onion peer workspaces'
            'obfs4proxy: Tor pluggable transport support'
            'qrencode: QR profile and invitation export'
            'zbar: QR image import')
provides=('tuxindrive')
conflicts=('tuxindrive')
source=("${{pkgname}}-${{pkgver}}.deb::{url}")
sha256sums=('{sha256(deb)}')

package() {{
  bsdtar -xf "${{srcdir}}/${{pkgname}}-${{pkgver}}.deb" -C "${{srcdir}}"
  bsdtar -xf "${{srcdir}}/data.tar."* -C "${{pkgdir}}"
  rm -f "${{pkgdir}}/usr/lib/systemd/user/tuxdrive.service"
  ln -s tuxindrive.service "${{pkgdir}}/usr/lib/systemd/user/tuxdrive.service"
}}
""")


def generate_aur_server(output: Path, version: str, deb: Path) -> None:
    package = output / "aur" / "tuxindrive-server-bin"
    url = f"{REPOSITORY}/releases/download/v{version}/{deb.name}"
    write(package / "PKGBUILD", f"""
pkgname=tuxindrive-server-bin
pkgver={version}
pkgrel=1
pkgdesc='Self-hosted encrypted TuxInDrive coordination and synchronization server'
arch=('any')
url='{REPOSITORY}'
license=('MIT')
depends=('python>=3.10' 'python-gobject' 'gtk3' 'python-cryptography' 'python-defusedxml' 'openssh' 'rclone')
optdepends=('tor: onion endpoints' 'obfs4proxy: Tor pluggable transport support')
provides=('tuxindrive-server')
conflicts=('tuxindrive-server')
source=("${{pkgname}}-${{pkgver}}.deb::{url}")
sha256sums=('{sha256(deb)}')

package() {{
  bsdtar -xf "${{srcdir}}/${{pkgname}}-${{pkgver}}.deb" -C "${{srcdir}}"
  bsdtar -xf "${{srcdir}}/data.tar."* -C "${{pkgdir}}"
}}
""")


def generate_homebrew(output: Path, version: str, dmg: Path) -> None:
    match = re.search(r"-macos-(arm64|x86_64)\.dmg$", dmg.name)
    if not match:
        raise SystemExit(f"Unrecognized macOS architecture in {dmg.name}")
    architecture = match.group(1)
    arch_requirement = ":arm64" if architecture == "arm64" else ":x86_64"
    url = f"{REPOSITORY}/releases/download/v{version}/{dmg.name}"
    write(output / "homebrew" / "Casks" / "tuxindrive.rb", f"""
cask "tuxindrive" do
  version "{version}"
  sha256 "{sha256(dmg)}"

  url "{url}"
  name "TuxInDrive"
  desc "Multi-provider cloud synchronization and encrypted peer sharing"
  homepage "{REPOSITORY}"

  depends_on arch: {arch_requirement}
  depends_on macos: ">= :monterey"
  app "TuxInDrive.app"
end
""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    version = project_version(args.project_root)
    installer = require_one(args.asset_dir, f"TuxInDrive-{version}-windows-x64-setup.exe")
    deb = require_one(args.asset_dir, f"tuxindrive_{version}_all.deb")
    server_deb = require_one(args.asset_dir, f"tuxindrive-server_{version}_all.deb")
    dmg = require_one(args.asset_dir, f"TuxInDrive-{version}-macos-*.dmg")
    aab = require_one(args.asset_dir, f"TuxInDrive-{version}-android-store.aab")
    generate_winget(args.output, version, installer)
    generate_chocolatey(args.output, version, installer)
    generate_aur(args.output, version, deb)
    generate_aur_server(args.output, version, server_deb)
    generate_homebrew(args.output, version, dmg)
    write(args.output / "google-play" / "README.txt", f"""
Upload {aab.name} to the Google Play testing track for io.github.tuxindrive.mobile.
The store flavor disables TuxInDrive's sideload updater and delegates updates to Google Play.
SHA-256: {sha256(aab)}
""")
    print(args.output)


if __name__ == "__main__":
    main()
