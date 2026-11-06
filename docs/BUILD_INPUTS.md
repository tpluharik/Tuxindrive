# Frozen native build inputs

Version 0.26.81 replays reviewed native dependency snapshots instead of resolving
live MSYS2 or Homebrew repositories in a release build. This is a build-time
change. Application synchronization, backup, mailbox indexing, encryption,
account settings and credential formats are unchanged.

## What is frozen

- Windows x64: the 208-package MSYS2/UCRT64 environment used for 0.26.80,
  including Python, GTK and PyInstaller, plus the Inno Setup compiler files.
- macOS arm64: the 53-formula runtime closure used for 0.26.80, including
  GTK 3.24.52, Python 3.14.7, GI, Cairo and their runtime libraries. Original
  Cellar paths and links are retained to preserve compiled library install names.
- Python release dependencies retain exact versions and reviewed PyPI hashes.
  The macOS virtual environment no longer inherits arbitrary system packages;
  only the captured GI/Cairo module directories are added explicitly.

The archive URL, exact size, SHA-256, capture commit and baseline-inventory hash
are committed in `packaging/build-environments/*.lock.json`. The archives are
stored in a separate `build-inputs-*` GitHub Release, not in Git history, a
moving `latest` URL or an expiring Actions artifact. They are not end-user
installers and are never referenced by the application updater.

## Fail-closed replay

`scripts/build-environment.py restore` downloads only the exact official
versioned asset. It rehashes even a cached archive, verifies its size and baseline,
then checks all archive members before extracting anything. Traversal, linked
parents, escaping links, duplicate members, devices/FIFOs and oversized archives
are rejected. Failed downloads/checksums cannot become a verified archive.

There is no fallback to `pacman -S`, `brew install`, another dependency version,
or an unverified compiler. Release jobs record the lock and host image identifier
as build evidence. GTK/cryptography/keyring imports and frozen application
`--version` startup checks must pass without opening or connecting an account.
Existing guarded tests, isolated historical upgrades, Android signing and
publication gates remain in force.

## Refresh procedure

1. Review security advisories and deliberately choose a new baseline. Never
   freeze vulnerable dependencies indefinitely in the name of reproducibility.
2. Update the baseline inventories in a reviewable branch. The capture mode is
   an explicit `capture_native_environments=true` workflow dispatch. It has
   read-only repository access, no signing credentials and no publication job.
3. Compare all dependency versions with the approved baseline. Capture excludes
   developer homes, application state, package caches, logs, private SSL folders
   and the package manager's disposable local signing keyring. It does not
   contain production signing keys or connected cloud/mail accounts.
   Upstream Python public TLS test fixtures remain as package data; the audit
   permits only their explicit reviewed paths and rejects unexpected PEM keys.
4. Review candidate provenance, archive paths, private-directory exclusions,
   hashes and native import/startup checks. Retain included upstream license
   notices and package/formula metadata; the baseline identifies exact upstream
   package versions for corresponding-source retrieval.
5. Publish under a fresh `build-inputs-*` tag and immutable filenames. Never
   overwrite an existing input version. Pin the verified bytes in the lock files.
6. Validate both native builds from those locks in a fresh CI run before merging
   a version bump. A missing archive or changed hash blocks publication.
   `native_replay_only=true` runs guarded tests and both native builds without
   Android signing, an application release or a redundant Android rebuild.

## Explicit boundaries

This freezes third-party runtime and packaging inputs, not a complete VM image.
macOS CI uses the supported `macos-15` ARM64 host after GitHub retired macOS 14
on 2 November 2026. The existing reviewed dependency archives are unchanged;
capture/replay still reject an architecture mismatch. See
[GitHub's retirement notice](https://github.blog/changelog/2026-10-01-github-actions-macos-14-runner-image-retirement/).
GitHub's Windows/macOS host OS and Apple system tools such as `codesign` and
`hdiutil` are recorded but not vendored or made immutable. Archive timestamps,
native signing and packaging can still change final bytes; bit-for-bit
reproducibility is not claimed. A versioned self-hosted VM/OS-image pipeline is
separate infrastructure work.

Native signing is deliberately pending: Windows packages have no Authenticode
signature and macOS uses ad-hoc signing, not Developer ID notarization. The
existing Android identity and offline Ed25519 in-app update signing remain
independent and unchanged. These archives do not turn an unsigned installer
into a trusted native publisher.
