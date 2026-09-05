# TuxInDrive platform release channels

Each platform has a dedicated folder containing its signed `latest-v2.json`
update manifest, plus a visible `packages/` directory documenting the exact
durable download location. Large installers are kept as GitHub Release assets
because Windows, macOS and Android packages can exceed GitHub's 100 MiB
repository-file limit. Workflow artifacts are temporary build outputs and are
never used as update sources.

- `android/` — Android APK channel
- `macos/` — macOS DMG channel
- `windows/` — Windows x64 installer channel

Linux uses the compatibility channel at `update/latest-v2.json`; the workflow
creates `releases/linux/packages` only as temporary build staging. It is not a
committed or client-facing channel directory.

Clients trust only expiring Ed25519-signed manifests, an approved TuxInDrive
download origin, a version-bound package filename, and the declared SHA-256.

A relevant push to `main` builds all four packages and publishes a durable
Release only when the source version does not already exist. An existing
release is never replaced by an ordinary main-branch build. A matching version
tag validates the tag/source version pair and can publish the same package set.
The current 0.26.34 package set is available at:

`https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.34`

Maintainer signing, validation, publication, and rollback rules are documented
in [`docs/RELEASES.md`](../docs/RELEASES.md).
