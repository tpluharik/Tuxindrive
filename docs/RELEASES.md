# TuxInDrive release process

This document defines the release and signed update-channel workflow for
TuxInDrive 0.26.28. It is intended for maintainers. Users should use
the installation and update instructions in the [user guide](USER_GUIDE.md).

## Release outputs

| Platform | Durable package | Channel manifest |
|---|---|---|
| Windows x64 | `TuxInDrive-VERSION-windows-x64-setup.exe` and portable ZIP | `releases/windows/latest-v2.json` |
| macOS | `TuxInDrive-VERSION-macos-ARCH.dmg` | `releases/macos/latest-v2.json` |
| Android sideload | `TuxInDrive-VERSION-android.apk` | `releases/android/latest-v2.json` |
| Android store | `TuxInDrive-VERSION-android-store.aab` | Marketplace-controlled update channel |
| Linux | `tuxindrive_VERSION_all.deb` | `update/latest-v2.json` |
| Linux server preview | `tuxindrive-server_VERSION_all.deb` | No automatic-update channel in the first preview |

Large packages are GitHub Release assets, not Git objects. The dedicated
`releases/windows`, `releases/macos`, and `releases/android` folders are stable
channel roots: each contains the signed manifest and `packages/README.md`
pointing to the durable Release URL. Linux retains the compatibility channel
under `update/`. Seven-day Actions artifacts and the workflow's temporary
`releases/linux/packages` staging directory are build evidence only and are
never updater sources.

Each complete Release also contains
`TuxInDrive-VERSION-marketplace-metadata.tar.gz`. It is generated only after
the final packages exist and contains checksum-bound WinGet, Chocolatey, AUR,
Homebrew, and Google Play submission inputs. See
[Marketplace distribution](MARKETPLACE_DISTRIBUTION.md). Marketplace metadata
does not replace the signed TuxInDrive updater manifests.

The server is intentionally a separate Debian package built with
`scripts/build-server-deb.sh`. It is not installed by the desktop package. The
cross-platform release workflow publishes it as a durable asset beside the
client packages after all platform jobs pass. Before a server package is
attached to a Release, run its focused tests, inspect its installed layout and
control scripts, validate the systemd hardening and perform a clean
Debian/Ubuntu install. A future server update channel must receive its own signed
platform/product manifest; it must never reuse the desktop Linux manifest.

## Version sources

The canonical application version is `src/tuxindrive/__init__.py`. Packaging,
Android version naming, manifest filenames, Git tag, and release title must
agree. Update the changelog and documentation baseline in the same change.
Versions follow semantic `MAJOR.MINOR.PATCH` ordering and the release tag is
exactly `vMAJOR.MINOR.PATCH`.

## Trust model and keys

Update manifests are signed with Ed25519. The private update key is held only
by the release maintainer and must never enter the repository, package, log, or
workflow artifact. Clients embed only the public key. A manifest binds:

- schema, product, version, platform, architecture, and expiry;
- an approved HTTPS download origin and version-bound filename;
- exact package size and SHA-256;
- Ed25519 signature over canonical manifest content.

Android packages are additionally signed with a long-lived Android keystore.
The keystore and passwords are encrypted GitHub Actions secrets:
`ANDROID_KEYSTORE_BASE64`, `ANDROID_STORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and
`ANDROID_KEY_PASSWORD`. Losing that identity prevents seamless upgrades of an
installed Android app. Windows/macOS production code-signing and notarization
should use their platform identities when available; update-manifest
verification remains mandatory and separate.

## Before tagging

1. Ensure `main` is clean, reviewed, and synchronized with GitHub.
2. Update the canonical version, changelog, README/current docs, and manifests.
3. Run the full Python test suite and Android lint/unit/assembly tasks.
4. Validate package scripts on the target runners and confirm pinned Actions
   and dependency/tool versions.
5. Confirm Android release-signing secrets exist without printing them.
6. Confirm the offline update private key is accessible to the authorized
   maintainer, has restrictive permissions, and matches the embedded public key.
7. Create or regenerate each manifest only after the final package bytes exist.

Never reuse a signed manifest for different bytes and never rewrite an existing
version tag to point at a different commit.

## Continuous-integration behavior

`.github/workflows/platform-packages.yml` builds Linux, Windows, macOS, and
Android on relevant pushes to `main`, manual dispatch, and version tags. A
main-branch run publishes a durable `vVERSION` Release only when that source
version has no Release yet; an existing Release is left unchanged. A version
tag validates that the tag equals the source version. Both publication paths
require the Android release keystore, download all platform artifacts, check
exact version-bound names, produce `SHA256SUMS.txt`, and publish one complete
package set. Documentation-only commits do not trigger this path-filtered
workflow.

The Linux job builds the Debian package. The Windows job freezes the GTK/Python
application in MSYS2 and produces an installer plus portable ZIP. The macOS job
builds the GTK application and DMG. The Android job builds a pinned rclone
gomobile library, then runs release tests and lint and produces both the signed
sideload APK and the self-update-disabled Play Store AAB. The publication job
derives package-manager definitions and checksums from those exact files.
Publishing waits for all four jobs; a failed platform blocks the
release rather than publishing a partial channel.

## Manifest publication

For every platform package:

1. Download the final Release asset and calculate SHA-256 and byte size from
   those exact bytes.
2. Set a bounded expiry that allows normal upgrades but forces periodic
   channel renewal.
3. Use only the approved GitHub Release URL and exact versioned filename.
4. Canonicalize and sign with the offline Ed25519 private key using the
   repository manifest-signing tooling.
5. Verify with the embedded public key and run the updater tests before commit.
6. Commit the platform `latest-v2.json` and `packages/README.md` pointers to
   `main`, then verify the raw GitHub URL delivers the committed bytes.

The manifest commit normally follows a successful package release because its
hash and size cannot be known beforehand. Until that commit lands, clients
correctly continue to report the preceding trusted version.

## Release validation

Validate on a clean supported device for every platform:

- install the package and confirm version, icon, launch, configuration path,
  credential store, account connection, one safe synchronization, and logs;
- check for an update from the previous supported version;
- verify that a changed signature, URL, filename, size, digest, expiry, product,
  platform, or architecture is rejected;
- verify download cancellation/failure leaves the installed version usable;
- Android: verify the signing certificate matches the previous release, SAF
  selection works, scheduled foreground sync works, profile backup is
  searchable/importable, and the branded launcher icon is present;
- Windows/macOS: verify installer/DMG, launch-at-login, keyring, mount helper,
  uninstall, and portable behavior where applicable.
- Desktop search: verify ordinary and paused roots are found without reading
  contents, excluded paths and symlinks remain absent, stale results are
  pruned after a complete refresh, streaming mounts are not traversed, and an
  item moved outside its configured root cannot be opened from an old result.

Record Git commit, tag, workflow run, Release URL, package hashes, signing-key
public fingerprint, and validation results in the release notes.

## Rollback and compromised releases

Do not mutate a published package or move its tag. For an ordinary regression,
publish a higher patch version that restores the safe behavior, sign new
manifests, and clearly document impact. The updater intentionally rejects a
lower version as an update.

If an update key may be compromised, stop channel publication, protect logs and
evidence, revoke repository/workflow access, rotate the key through a separately
reviewed application release, and notify users through authenticated project
channels. If the Android keystore is compromised, also follow the Android
distribution key-rotation procedure before accepting replacement packages.

Never "fix" a channel by disabling signature, digest, origin, filename, size,
or expiry validation. See [Security hardening](SECURITY_HARDENING.md) for the
complete trust boundary and [Operations](OPERATIONS.md) for client diagnosis.
