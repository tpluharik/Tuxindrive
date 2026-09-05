# Platform support and adaptive installation

TuxInDrive 0.26.34 publishes packages for Debian-family Linux, Windows x64, macOS and Android. Linux, Windows and macOS use the same GTK desktop UI; Android uses a Material mobile UI backed by rclone's in-process gomobile library. The main desktop window remains freely resizable; dialogs open at 92% of the active monitor work area and keep oversized content reachable through local scrolling. Android Settings is vertically scrollable. Credentials remain in GNOME Secret Service, Windows Credential Manager, macOS Keychain, or Android's private application sandbox. A missing optional integration disables only that feature. Package locations and updater behavior are documented in [Release process](RELEASES.md).

## Compatibility matrix

The desktop baseline is Ubuntu 24.04/26.04, Debian 12/13, Windows 10/11 x64 and macOS 12+. Android targets API 26 (Android 8) and newer. Linux desktop packages support amd64 and arm64; the first Windows installer is x64. Platform CI creates developer-signed artifacts, while public distribution requires the platform-owner signing identities listed below.

| Distribution / desktop | Core cloud sync | Streaming | File-manager status/actions | Support level and limitations |
| --- | --- | --- | --- | --- |
| Windows 10/11 x64 | Native package CI | WinFsp optional | Application controls | Same GTK UI; Git must be installed for GitHub jobs. Explorer overlays are not included. |
| macOS 12+ | Native package CI | macFUSE optional | Application controls | Same GTK UI; Finder overlays and Apple notarization require the release signing gate. |
| Android 8+ phone/tablet | Native librclone + SAF | Offline selected folders | Native mobile controls | Material UI, encrypted config import, cloud browsing and WorkManager two-way sync; no transparent FUSE drive. |
| Ubuntu/Debian Server amd64/arm64 | Separate headless `.deb` | Not scheduled by default | CLI/systemd/API | GTK-free sync/peer agent plus independently enabled encrypted coordination roles; remote API requires TLS. |
| Ubuntu 26.04 GNOME | Expected | Expected with FUSE 3 | Nautilus 4.1 design target | Primary target; complete GNOME/Wayland VM release test required. |
| Ubuntu 24.04 LTS GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported; verify AppIndicator extension and unlocked GNOME Keyring in the user session. |
| Ubuntu 26.04 LTS GNOME | PPA source-build target | Expected with FUSE 3 | Nautilus 4.x | Supported through the Resolute PPA build; complete graphical/Secret Service/FUSE acceptance on the final release image. |
| Debian 13 GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported core; integration package versions come from Debian repositories. |
| Debian 12 GNOME | CI-installed | Expected with FUSE 3 | Nautilus 4.x | Supported core; use Debian security updates/backports and complete the manual Secret Service/FUSE gate. |
| Ubuntu 22.04 GNOME | PPA source-build target | Best effort | Older python-nautilus generation | Launchpad builds Jammy packages, but full graphical/Secret Service/FUSE VM acceptance remains required before treating Jammy as the security baseline. |
| Linux Mint with Cinnamon/Nemo | Expected core only | Expected with FUSE 3 | Not available in Nemo | TuxInDrive runs as a GTK application, but the packaged extension is Nautilus-only. A Nemo adapter is not yet shipped. |
| Pop!_OS GNOME-based releases | Expected core only | Expected with FUSE 3 | Best effort when Nautilus is used | Tray/shell behavior depends on the installed GNOME extensions; COSMIC sessions are not a GNOME integration target. |
| Zorin OS | Expected core only on a compatible Ubuntu base | Expected with FUSE 3 | Best effort | Run the system check; support follows the base Ubuntu Python, GTK and Nautilus versions rather than the Zorin version label. |
| Ubuntu flavors using Xfce, MATE, LXQt or KDE | Expected core only | Expected with FUSE 3 | No native Thunar/Caja/Dolphin integration | Cloud and peer functions can run, but Nautilus badges/actions and GNOME tray assumptions do not apply. |
| elementary OS / Pantheon Files | Expected core only | Expected with FUSE 3 | Not available | Pantheon Files is not supported by the Nautilus extension. |
| Kali Linux rolling | Best effort | Best effort | Best effort if Nautilus is installed | Rolling dependency changes are outside the release matrix; do not treat it as a stable production target. |
| MX Linux / antiX family | Best effort | Best effort | No native file-manager integration | Non-systemd or Xfce configurations may require manual autostart and lack the packaged user service. |
| Devuan | Best effort | Best effort | Best effort if Nautilus is installed | The systemd user unit is unavailable; desktop autostart and session services must be supplied separately. |
| Raspberry Pi OS 64-bit | Best effort | Hardware/kernel dependent | No native default file-manager integration | arm64 rclone is supported, but the default desktop is outside the GNOME/Nautilus matrix. 32-bit ARM is unsupported. |
| Other Debian derivatives | Unverified | Unverified | Unverified | Requires Python 3.10+, GTK 3/PyGObject, Secret Service and supported amd64/arm64 runtime; run `tuxindrive --system-check`. |

“Native package CI” means the platform build completes on that operating system. “CI-installed” means the Debian package was installed with mandatory dependencies in the repository's container matrix. Neither replaces a graphical/device acceptance test.

## Package outputs and signing

- Windows CI produces a per-user Inno Setup executable and portable ZIP. Production releases need an Authenticode certificate.
- macOS CI produces an ad-hoc signed application DMG. Public distribution needs an Apple Developer ID, hardened-runtime signing and notarization.
- Android branch CI produces an installable debug APK; version tags require the encrypted release keystore and produce an upgrade-compatible signed APK. Store distribution may require a separate upload-key policy.
- The official sideload APK checks the signed Android channel automatically,
  downloads only on an eligible network while the battery is not low, and
  notifies the user when a verified package is ready. Android still presents
  its system installer and requires user approval. The feature can be disabled
  in mobile Settings and remains absent from store builds.
- No private signing key is stored in the repository. A missing signing identity must never be silently replaced for a production release.

The shared global bandwidth controller applies on every platform. Desktop
rclone operations receive the effective directional rate, native Git/Proton
work is admitted through the same controller, and Android passes the rate to
its embedded rclone core while serializing browse/sync/update work.

## Search availability

Linux, Windows, and macOS provide the 0.26.31 private cross-folder filename
search. It indexes metadata from ordinary local synchronization roots and does
not enumerate streaming/FUSE mounts. Search therefore remains usable offline
and cannot hydrate files-on-demand content merely by opening the search window.

Android 0.26.31 can browse connected cloud roots through its native Files page,
but it does not yet build the desktop SQLite index or provide one query across
all Storage Access Framework trees. Android document-provider search remains a
separate roadmap item; documentation must not imply desktop search parity until
that native implementation ships.

The Linux, Windows and macOS search window also has a default-off
selected-result preview. Text, images and ZIP-based office formats are handled
by the desktop runtime with bounded local reads. PDF text additionally needs
`pdftotext` (recommended as `poppler-utils` by the Debian package); absence of
that optional tool disables only PDF text preview. Android preview parity is
not part of this change.

## Checks performed

`postinst` writes a machine-level snapshot to `/var/lib/tuxindrive/install-capabilities.json`. Because package installation runs as root outside the graphical login, run the user-session check after installation:

```bash
tuxindrive --system-check
# machine-readable output
tuxindrive --system-check --json
```

The session check reports the distribution, CPU, desktop/session and availability of Secret Service, URL opening, FUSE, Nautilus, PolicyKit, notifications, NetworkManager policies, Tor/obfs4, NAT traversal and QR pairing. Required failures return exit status 1. Optional failures return an actionable installation hint and disable only the affected feature.

## Package model

- Required: Python 3.10+, PyGObject, GTK 3, Python cryptography, `defusedxml`, Secret Service tools, XDG utilities and CA certificates. `defusedxml` is mandatory for hostile-input-safe collaborative ODT/ODS parsing.
- Recommended: Nautilus integration, AppIndicator, FUSE streaming, peer SSH, Tor transports, NAT traversal, NetworkManager policies, QR tools, notifications and PolicyKit updates.
- Suggested: Snowflake transport.

APT normally installs recommendations. Minimal systems may use `--no-install-recommends`; TuxInDrive will then start with the available core and report which optional functions are disabled. Linux Mint/Nemo, Caja and non-Nautilus file managers can run TuxInDrive but do not currently receive badges or context actions.

## Limits

The `.deb` is adaptive, not a hermetic container: authentication needs a working user Secret Service, streaming needs kernel FUSE access, tray visibility depends on the GNOME shell indicator extension, and Nautilus integration is host-loaded code. These boundaries cannot safely be bundled or activated from a root maintainer script. Clean GNOME VM tests remain required for each distribution release.

## Release VM gate

Before marking a distribution as fully verified, install the `.deb` on a clean amd64 or arm64 image and test login autostart, Wayland and X11 startup where offered, Secret Service lock/unlock, Google/OneDrive OAuth, a two-way move/delete cycle, FUSE reconnect after logout and suspend, Nautilus badges/actions, tray visibility, notifications, PolicyKit update installation and uninstall/reinstall with preserved encrypted configuration. Record the exact distribution image, package versions and result in the release notes.

Equivalent clean-device gates for Windows, macOS, and Android are listed in
[Release validation](RELEASES.md#release-validation).

The first server package is Linux `Architecture: all` Python code; rclone,
OpenSSH and optional Tor executables still need matching host-architecture
packages. Windows Server, macOS LaunchDaemon, OCI/NAS appliances and public
federation remain compatibility targets, not current package claims.
