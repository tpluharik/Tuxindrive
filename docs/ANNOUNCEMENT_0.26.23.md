# TuxInDrive 0.26.23 announcement notes

Use these short drafts when announcing the release. Adapt the opening sentence
to the community and disclose that you maintain the project. Do not paste the
same text into unrelated discussions, imply endorsement, or describe untested
platform behavior as complete.

## Release facts

- Release: [TuxInDrive 0.26.23](https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.23)
- Main change: one private desktop search for file and folder names across
  configured ordinary synchronized folders, including paused jobs.
- Privacy boundary: metadata only; no file contents, symlink traversal,
  telemetry, server upload, or files-on-demand enumeration.
- Refresh behavior: startup, successful synchronization, and a manual refresh
  button; a 250,000-entry per-root limit preserves the last complete snapshot.
- Platforms: Linux, Windows, and macOS receive desktop search. Android 0.26.23
  retains cloud browsing and synchronized-folder controls but not the new
  cross-tree index.
- Release packages: Linux client/server `.deb`, Windows setup/portable,
  macOS DMG, and signed Android APK, all with dedicated signed update channels.
- Validation: 386 Python tests passed; the platform release workflow completed
  successfully for Linux, Windows, macOS, and Android.

## Very short post

TuxInDrive 0.26.23 is out. It adds private local filename/path search across
desktop synchronized folders without reading file contents or walking
files-on-demand mounts. Linux, Windows, macOS and Android packages are on the
release page. Feedback, testing and contributions are welcome:
https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.23

## Community post

I maintain TuxInDrive, an open-source, Linux-first multi-cloud synchronization
client. Version 0.26.23 adds one local search window for file and folder names
across configured desktop sync roots. The index stores metadata only, stays on
the device, skips symlinks and excluded paths, and does not enumerate streaming
mounts—so opening search should not wake a cloud provider.

The release includes Linux, Windows, macOS and Android packages; the new
cross-folder search is currently desktop-only. I would especially appreciate
feedback from people with large folder trees, unusual Unicode filenames, or
several paused and active sync jobs. Bug reports, testers and contributors are
welcome: https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.23

## Developer-oriented note

TuxInDrive 0.26.23 now has a bounded, rebuildable SQLite metadata index for
cross-folder desktop search. Refresh runs outside the GTK thread, preserves the
last complete snapshot when a root reaches its safety cap, and revalidates path
confinement before opening a result. The implementation and threat boundary are
documented, with regression coverage for Unicode, SQL wildcards, exclusions,
symlinks, stale pruning, paused jobs, streaming avoidance and partial scans.

Release and source:
https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.23

## Suggested replies to common questions

- **Does it search file contents?** No. Version 0.26.23 searches names and
  relative paths only.
- **Does search upload an index?** No. The index and queries stay on the desktop
  device and are not sent to cloud providers or the optional TuxInDrive server.
- **Will it download online-only files?** No. Streaming/files-on-demand jobs are
  deliberately excluded from indexing.
- **Is Android cross-folder search included?** Not yet. Android keeps its native
  Files browsing; cross-tree document-provider search remains planned work.
- **Where should bugs go?** Use the repository issue forms and remove personal
  filenames, credentials, tokens and private paths from screenshots or logs.
