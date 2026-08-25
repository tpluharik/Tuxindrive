# Android installer storage

CI stages the signed APK in this directory before uploading it. Published APKs
live permanently in the matching versioned GitHub Release; they are not
committed to Git because they exceed normal repository file-size limits.

For version 0.26.29, download the durable package from the
[`v0.26.29` GitHub Release](https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.29).
See [the release process](../../../docs/RELEASES.md) for signing and updater rules.
