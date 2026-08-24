# Marketplace and package-manager distribution

TuxInDrive keeps GitHub Releases as the immutable source of release bytes. A
tagged release also generates checksum-bound metadata for WinGet, Chocolatey,
AUR, Homebrew, and Google Play. Marketplace copies must reference those exact
bytes and must never replace an existing tag silently.

## Automated release outputs

| Channel | Generated release input | Update owner |
|---|---|---|
| WinGet | Multi-file manifest for `TuxInDrive.TuxInDrive` | WinGet |
| Chocolatey | `.nuspec` and checksum-pinned install script | Chocolatey |
| AUR | `tuxindrive-bin` `PKGBUILD` | Pacman/AUR helper |
| Homebrew | Architecture-specific `tuxindrive` Cask | Homebrew |
| Google Play | Signed `TuxInDrive-VERSION-android-store.aab` | Google Play |
| GitHub Android | Signed `TuxInDrive-VERSION-android.apk` | TuxInDrive updater |

`scripts/generate-marketplace-metadata.py` reads the canonical version,
requires exactly one matching package per platform, calculates hashes from the
files and emits `TuxInDrive-VERSION-marketplace-metadata.tar.gz`. No placeholder
checksum is accepted. The Play Store flavor has self-update disabled; the
separately signed sideload APK retains it.

## Submission sequence

1. Publish and validate one complete tagged GitHub Release.
2. Freeze its artifacts; never replace bytes below an existing tag.
3. Inspect the generated marketplace metadata archive.
4. Submit WinGet and Homebrew changes as pull requests.
5. Push Chocolatey from the verified maintainer account.
6. Push AUR recipes using the maintainer's registered SSH identity.
7. Upload the AAB first to Google Play internal testing.
8. Promote only after clean-install and previous-version upgrade tests pass.

## Maintainer inputs still required

Do not send passwords, private keys, API keys, or service-account JSON through
an issue, pull request, chat, or commit. Add them directly as encrypted
repository/environment secrets and send only non-secret names or fingerprints.

### GitHub-backed submissions

- Confirm whether submissions should come from `tpluharik` or a dedicated
  packaging-bot account.
- Add a fine-grained token to the protected `release` environment only when
  external WinGet/Homebrew pull requests are ready. It needs no cloud-account
  or TuxInDrive user-data access.

### Windows

- Obtain an Authenticode certificate and add its PFX plus password as protected
  release secrets. Send only its subject and SHA-256 fingerprint.
- Create or verify the Chocolatey maintainer account and add its API key as a
  protected secret. Send the account name, never the key.

Public Windows submission should wait for Authenticode so SmartScreen and the
installer identity remain stable across upgrades.

### macOS

- Enroll in the Apple Developer Program.
- Add a Developer ID Application certificate, its private-key password, and
  notarization credentials directly to the protected release environment.
- Send the Team ID, certificate subject, and public fingerprint only.

Homebrew submission waits for a Developer ID-signed and notarized DMG. The
current ad-hoc development signature is not production notarization.

### Google Play

- Create the app with package ID `io.github.tuxindrive.mobile` and retain this
  identity permanently.
- Enable Play App Signing and decide whether the existing release key becomes
  the app-signing key or remains the upload key.
- Add the Play service-account JSON as a protected secret; send only its email.
- Complete the privacy policy, Data Safety, content-rating, target-audience,
  and testing declarations. These legal/product assertions require the owner.
- Supply approved store screenshots and the public support contact.

### Snap Store

- Create the Snapcraft publisher account and register `tuxindrive`.
- Confirm the publisher display name.
- Request classic confinement, explaining that explicit user-selected cloud
  roots, FUSE mounts, credential services, and file-manager integration need
  host filesystem access. Publication waits for the store assertion.

Snap packaging must not weaken TuxInDrive path checks merely to avoid review.

### Ubuntu PPA and Debian

- Create or confirm the Launchpad account and PPA name.
- Register the maintainer OpenPGP public key and send its fingerprint only.
- Choose the supported Ubuntu series and architectures.

Launchpad accepts signed source uploads, not the existing prebuilt `.deb`.
Debian archive inclusion additionally needs a policy-compliant source package,
an ITP/RFS process, and a Debian Developer sponsor. Until those builds reproduce
the installer behavior, the signed GitHub `.deb` remains canonical.

### AUR

- Create the AUR account, add a dedicated SSH public key, and send the username
  plus public-key fingerprint.
- Confirm ownership of `tuxindrive-bin` and `tuxindrive-server-bin` before push.

### F-Droid and Flathub

F-Droid needs a network-free reproducible recipe for the pinned rclone Android
library. Current CI verifies the source commit but downloads Go inputs during
the build, so submission is deferred until these are reviewed source-library
dependencies.

Flathub currently rejects applications containing AI-assisted code or
documentation. TuxInDrive must not conceal its history or submit while that
rule remains in force.

## Release safety

- Marketplace credentials live only in an approval-protected environment.
- Pull-request automation receives repository-scoped, short-lived access.
- Store builds never invoke the TuxInDrive self-updater.
- Packages retain the MIT license, source link, security contact, and version.
- A failed target never publishes a partial replacement under an existing tag.
