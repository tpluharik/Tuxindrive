# Marketplace release inputs

TuxInDrive generates submission-ready package-manager definitions from the
exact files produced by each tagged release. The generator refuses missing or
ambiguous artifacts and calculates every checksum locally:

```bash
python3 scripts/generate-marketplace-metadata.py \
  --asset-dir release-assets --output marketplace-metadata
```

The generated artifact contains:

- a WinGet multi-file manifest;
- a Chocolatey package source;
- an AUR `tuxindrive-bin` `PKGBUILD`;
- a Homebrew Cask for the architecture-specific DMG; and
- the signed store-flavor Android App Bundle identity and checksum.

These generated files are release outputs, not hand-maintained source. They
must be submitted from their respective maintainer accounts after the release
files have become immutable. Store editions delegate updates to their store;
the GitHub APK retains the separately signed TuxInDrive sideload updater.

External prerequisites and the exact maintainer hand-off are documented in
[`docs/MARKETPLACE_DISTRIBUTION.md`](../../docs/MARKETPLACE_DISTRIBUTION.md).
