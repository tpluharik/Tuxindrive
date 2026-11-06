# TuxInDrive release process

This document defines the release and signed update-channel workflow for
TuxInDrive 0.26.81. It is intended for maintainers. Users should use
the installation and update instructions in the [user guide](USER_GUIDE.md).

Native dependencies are replayed from reviewed, SHA-256-pinned archives. Only
explicit unsigned capture mode contacts live native package managers. A failed
lock, download or archive check blocks the build; no live-resolution fallback is
allowed. See [frozen build-input refresh and boundaries](BUILD_INPUTS.md).

## Release outputs

| Platform | Durable package | Channel manifest |
|---|---|---|
| Windows x64 | `TuxInDrive-VERSION-windows-x64-setup.exe` and portable ZIP | `releases/windows/latest-v2.json` |
| macOS | `TuxInDrive-VERSION-macos-ARCH.dmg` | `releases/macos/latest-v2.json` |
| Android sideload | `TuxInDrive-VERSION-android.apk` | `releases/android/latest-v2.json` |
| Android store | `TuxInDrive-VERSION-android-store.aab` | Marketplace-controlled update channel |
| Linux | `tuxindrive_VERSION_all.deb` | `update/latest-v2.json` |
| Linux server preview | `tuxindrive-server_VERSION_all.deb` | No automatic-update channel in the first preview |
| Linux Network Lab | `tuxindrive-network-lab_VERSION+labREVISION_all.deb` | Separate `network-lab-vVERSION.REVISION` release; never the desktop/server updater |

Large packages are GitHub Release assets, not Git objects. The small, identical
Linux compatibility copy is an explicit exception: retain a versioned
`dist/tuxdrive_VERSION_all.deb` in Git and point the Linux feed at its immutable
commit using the legacy `raw.githubusercontent.com/tpluharik/Tuxdrive/` prefix.
Historical clients before 0.26.3 cannot use Release-download URLs. They also
require the preserved Debian `Package: tuxdrive` identity. Never rename or
repackage bytes after computing their signatures. The dedicated
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

The Network Lab is even more strictly separated. It is built by
`.github/workflows/network-lab-release.yml`, uses `+labREVISION` Debian versions
and is published only from `network-lab-vVERSION.REVISION` tags. Its package and
checksum are not staged by the desktop platform workflow, are not attached to a
normal `vVERSION` release and never enter an in-app update manifest. See
[Network Lab](NETWORK_LAB.md) for the scenario and isolation contract.

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

- version, download URL, SHA-256, release notes, and expiry;
- an Ed25519 signature over those five fields as compact, sorted JSON.

Clients additionally enforce an approved HTTPS origin, a version-bound filename
for their platform/architecture, and a 1 GiB download ceiling. The current
manifest format does not separately sign schema, product, architecture or size.
Desktop and Android must verify the same canonical bytes; Android's regression
fixture uses an official manifest produced by the offline Python signer.

Android packages are additionally signed with a long-lived Android keystore.
The keystore and passwords are protected release-environment secrets, not
repository-wide secrets:
`ANDROID_KEYSTORE_BASE64`, `ANDROID_STORE_PASSWORD`, `ANDROID_KEY_ALIAS`, and
`ANDROID_KEY_PASSWORD`. Losing that identity prevents seamless upgrades of an
installed Android app. Windows/macOS production signing and notarization remain
pending. Opt-in identity/timestamp/Gatekeeper verification gates are available,
but do not provision private credentials or a signing producer. See the exact
remaining setup in [Code signing policy](CODE_SIGNING_POLICY.md).
Update-manifest verification remains mandatory and separate.

The Android build job receives no signing credentials. A separate job, after
guarded tests and historical upgrade checks, downloads only its unsigned
artifacts from that same workflow run. It does not check out application code
or run Gradle. It verifies the certificate against the established sideload
identity, signs APKs with apksigner and AABs with jarsigner, verifies signatures,
and removes its temporary keystore. Never regenerate a release identity because
credentials are missing. The release environment restricts main/version tags
and requires maintainer approval; branch builds cannot access its secrets.

## Before tagging

1. Ensure `main` is clean, reviewed, and synchronized with GitHub.
2. Update the canonical version, changelog, README/current docs, and manifests.
3. Require successful CI for the guarded Python suite, isolated process
   lifecycle tests, and Android lint/unit/assembly tasks. Do not reproduce real
   lifecycle signals in the developer's desktop session.
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
version has no Release yet; an existing Release is refused. A version
tag validates that the tag equals the source version and also refuses an
existing Release. Both publication paths wait for isolated Android signing,
download only the four approved platform artifacts, check
exact version-bound names, produce `SHA256SUMS.txt`, and publish one complete
package set. Documentation-only commits do not trigger this path-filtered
workflow.

The Linux job builds the Debian package. The Windows job freezes the GTK/Python
application in MSYS2 and produces an installer plus portable ZIP. The macOS job
builds the GTK application and DMG. The Android job builds a pinned rclone
gomobile library, then runs release tests and lint and produces both the signed
sideload APK and the self-update-disabled Play Store AAB. The publication job
derives package-manager definitions and checksums from those exact files.
Publishing also requires the `safety-gate` job: the guarded unit suite and real
process-lifecycle checks run in a disposable Linux container, in separate
interpreters. Never run the real signal checks in a developer desktop session.
Publishing waits for the safety gate and all four platform jobs; a failure blocks the
release rather than publishing a partial channel.

## Manifest publication

For every platform package:

1. Download the final Release asset and calculate SHA-256 and byte size from
   those exact bytes.
2. Set a bounded expiry that allows normal upgrades but forces periodic
   channel renewal.
3. Use the approved GitHub Release URL and exact versioned filename; Linux uses
   the byte-identical commit-pinned compatibility copy described above.
4. Canonicalize and sign with the offline Ed25519 private key using the
   repository manifest-signing tooling.
5. Verify with the embedded public key and the updater parser before commit;
   updater tests run in signal-guarded CI, not as local process tests.
6. Commit the platform `latest-v2.json` and `packages/README.md` pointers to
   `main`, then verify the raw GitHub URL delivers the committed bytes.

The manifest commit normally follows a successful package release because its
hash cannot be known beforehand. Until that commit lands, clients
correctly continue to report the preceding trusted version.

Keep the original 0.19.1 compatibility file while the preceding legacy manifest
remains valid (through 9 November 2026). Renew `update/latest.json` using only
its original offline key and a bridge proven on 0.18.1; never substitute the
modern key or bypass verification. Test the real published feeds with the
historical parsers after signing. CI's historical staging test uses a synthetic
test key and is not proof of a production-key signature by itself.

Dependency-verification collection is an explicit unsigned-only dispatch mode.
Review the generated Gradle metadata before committing it; collection runs
cannot sign or publish. Keep dependency versions unchanged during this
hardening rollout and refresh pins through a reviewed change.

## Release validation

Validate on a clean supported device for every platform:

- install the package and confirm version, icon, launch, configuration path,
  credential store, account connection, one safe synchronization, and logs;
- check for an update from the previous supported version;
- verify that a changed signed field/signature, a mismatched platform/version
  filename, an expired feed, or a download exceeding the size ceiling is rejected;
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
