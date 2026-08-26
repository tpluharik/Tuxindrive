# TuxInDrive release history

This changelog summarizes user-visible releases. Detailed operation, safety limitations, and recovery instructions are maintained in the [user guide](docs/USER_GUIDE.md).

## 0.26.30 — recovery, private content search and managed operation

- Added optional bounded local content indexing for supported formats. It is
  off by default, never traverses files-on-demand mounts, and never sends
  indexed text to a provider.
- Added preview-first cloud-to-cloud copying between configured rclone
  accounts, with global bandwidth admission and no delete semantics.
- Added immediate categorized recovery advice to error details, root-controlled
  managed desktop policy, and private CSV/JSONL audit export.
- Added historical configuration upgrade tests, a scheduled offline reliability
  matrix, and reproducible metadata/content-index performance evidence.

## 0.26.29 — automatic orphaned Bisync lock recovery

- Detects old rclone Bisync locks whose recorded owner process has exited and
  safely removes them before synchronization starts, including locks with a
  corrupted far-future expiry time.
- Never removes active, fresh, foreign, malformed, oversized, or symlinked lock
  files, and verifies the file identity again immediately before removal.
- Continues with the existing durable synchronization baseline instead of
  unnecessarily rebuilding state or repeatedly failing the scheduled job.

## 0.26.28 — immediate synchronization error details

- Added an **Error details** action beside **View log** on every synchronized
  folder card. It shows the last reason, reported source file/path, local and
  cloud locations, timestamp, exact job log, and a bounded recent error excerpt.
- Kept error inspection local and immediate: opening the dialog performs no
  provider request, integrity comparison, or conflict scan.
- Persisted structured error context across restarts and redacted common
  credential fields and credential-bearing URLs before rendering log lines.

## 0.26.27 — protocol backends, selective synchronization, and safer recovery

- Added first-class S3-compatible, generic WebDAV, and SFTP accounts with
  conservative capability declarations and the existing encrypted rclone
  credential boundary.
- Added per-job selective synchronization by file extension, maximum size, and
  maximum age. The same rules apply to full synchronization, native Proton
  transfers, and the private local search index.
- Expanded version history with search, reason filtering, readable sizes,
  retention details, and direct access to the protected recovery location.
- Replaced conflict-wide repair actions with a per-file graphical resolution
  choice. **Keep both** preserves the local file and installs the cloud/peer
  copy under a dated conflict name.
- Added explicitly confirmed HTTPS share-link creation only for providers whose
  capabilities safely advertise it; opening the online folder remains private.

## 0.26.26 — marketplace-ready release automation

- Produces a signed, self-update-disabled Android App Bundle for Google Play
  alongside the existing signed sideload APK.
- Derives checksum-bound WinGet, Chocolatey, Homebrew, AUR client/server, and
  Google Play submission inputs from the exact immutable release artifacts.
- Publishes those definitions as a versioned marketplace metadata archive and
  documents the protected account, signing, and review hand-off.

## 0.26.25 — secure automatic Android updates

- Added default-on, user-configurable periodic update checks to the official
  Android sideload build, constrained to an available network and a battery
  that is not low.
- Reused the existing expiring Ed25519-signed Android manifest and verified the
  exact APK digest before atomically retaining a ready-to-install package.
- Added an update notification that opens Android's package installer. Android
  continues to require the user's installation approval and unknown-source
  permission; TuxInDrive never attempts a silent or privileged installation.
- Reused an already downloaded APK only after checking its SHA-256 again and
  confined installer intents to the application's private verified-update
  cache.

## 0.26.24 — opt-in search-result previews

- Added an **Enable preview** feature flag inside the desktop search window;
  it is off for every new window and reads only the result the user selects.
- Added bounded local previews for UTF-8/UTF-16 text and common source files,
  images, PDF text, ODT/ODS, DOCX/XLSX and PPTX while keeping the metadata
  search index content-free.
- Confined preview paths to their synchronized root, rejected symbolic links,
  bounded input/archive/output sizes and compression ratios, parsed XML with
  `defusedxml`, and limited optional PDF extraction to three pages and eight
  seconds without invoking a shell.

## 0.26.23 — private synchronized-folder search

- Added one desktop search window for file and folder names across every
  configured local synchronization root, including paused jobs.
- Added a private incremental SQLite metadata index that refreshes at startup,
  after successful synchronization, or on demand and removes stale results.
- Kept searches local and content-free: file bodies are never opened, symlinks
  and excluded paths are ignored, and files-on-demand mounts are not walked so
  indexing cannot hydrate cloud data or create an idle provider scan.
- Bounded each very large root to 250,000 indexed entries and preserved the
  last complete index if a later refresh reaches that safety limit.

## 0.26.22 — monitor-safe responsive dialogs

- Opened desktop settings and other dialogs at 92% of the active monitor's
  usable work area without requesting window-manager maximization or extending
  across panels and screen edges.
- Removed a false window-sized minimum from the inner scroll canvas that could
  clip the left edge and create horizontal overflow as soon as a dialog opened.
- Kept both axes scrollable after later resizing so every control remains
  reachable on smaller displays.

## 0.26.21 — automatic aggregate bandwidth protection

- Fixed process-local rclone limits multiplying when synchronization, update
  download, and several streaming mounts were active at the same time.
- Added default-on automatic protection that reserves 20% of the configured
  ceiling and fairly divides the remainder across every possible simultaneous
  streaming/transfer consumer. The reserve is configurable from 0–80%.
- Budgeted the responsive update lane separately and made the optional server
  agent and relay share one controller instead of independently receiving the
  complete ceiling.

## 0.26.20 — server and update-channel security hardening

- Made the server configuration directory root-owned and read-only to the
  service, migrated the configuration to `root:tuxindrive-server` mode `0640`,
  removed `/etc` from the service write set, and replaced predictable temporary
  writes with randomized descriptor-relative no-follow atomic replacement.
- Bounded server request and relay concurrency globally and per source/tenant,
  added request and relay idle deadlines, applied the global upload/download
  rate controller to relays, and added systemd task, descriptor and memory
  ceilings.
- Tightened TLS, database and headless-client path validation against symlinks,
  unsafe modes and unexpected owners.
- Hardened the Android sideload updater with explicit redirect/final-origin
  validation, HTTPS-only network policy, advertised/downloaded size limits,
  durable atomic package storage, and sideload-only package-install permission.
- Pinned Python CI/release tools, disabled automatic Homebrew/MSYS2 updates,
  added a release environment and published Python dependency SBOM, while
  retaining native platform signing as an explicit maintainer requirement.
- Added regression tests and documented the 2026-08-22 security audit,
  remediation status and remaining release-provenance work.

## 0.26.19 — working integrity repair with quieter bulk protection

- Corrected the reversed `rclone check --combined` meanings for local-only and
  cloud-only files, so choosing the local side uploads and choosing the cloud
  side downloads the intended content.
- Restored the missing temporary staging dependency used for verified incoming
  repair files and retained recovery copies before destructive repair actions.
- Reduced false mass-change pauses by requiring both the configured changed
  path count and percentage for ordinary bulk edits. Deletion ceilings and
  ransomware-shaped filename extensions remain independent hard stops.
- Migrated the former 200-path/25-percent defaults to 500 paths/80 percent
  without changing explicitly customized non-default thresholds.

## 0.26.18 — reliable interactive updates

- Prevented signed package downloads from waiting indefinitely behind a
  long-running scheduled synchronization while retaining the global byte-rate
  limit and one-at-a-time interactive transfer admission.
- Kept the update dialog alive while download, verification, and installation
  are active, eliminating a late-callback crash when the window was closed.
- Reused an already downloaded package only after checking it again against
  the SHA-256 digest in the signed manifest, making a safe retry immediate.
- Removed incomplete package files after every failed download and made late
  completion callbacks safe during application shutdown.

## 0.26.17 — resizable desktop windows

- Prevented long synchronized-folder action rows from setting an enormous
  minimum window width; their controls now scroll within the folder card.
- Restored normal resizing and natural initial sizes for the desktop client,
  configuration dialogs, and graphical server administration application.
- Capped dialogs to the active monitor while retaining two-axis scrolling so
  every control remains reachable at small resolutions.

## 0.26.16 — reliable synchronized-folder editing

- Kept cloud-folder selections in persistent dialog state while the remote
  folder tree loads asynchronously, so Save cannot silently lose a selection.
- Reset folder selection to the new account root when an existing job is moved
  to another account instead of retaining an invalid path from the old account.
- Kept add/edit dialogs open and displayed validation errors inline when a
  folder is missing or overlaps another job unsafely.

## 0.26.15 — graphical server administration

- Added a maximized, scrollable TuxInDrive Server application for Linux so an
  administrator can manage the service without assembling command lines.
- Moved the complete server configuration schema, roles, quotas, bandwidth,
  relay/update targets, tenant-token generation, bootstrap-token handling,
  service lifecycle and journal viewer into the graphical application.
- Retained the `init`, `check` and `serve` commands for automation and recovery;
  protected changes use fixed, validated, no-shell PolicyKit operations.

## 0.26.14 — immutable server package repair

- Isolated the server Python runtime under `/usr/lib/tuxindrive-server` so the
  server and desktop Debian packages can be installed together safely.
- Added clean Ubuntu 24.04, Debian 12 and Debian 13 co-installation checks and
  verified the installed bootstrap token plus server configuration command.
- Made an existing same-version Release a hard failure for branch publishing,
  preventing a successful workflow from silently retaining stale artifacts.

## 0.26.13 — server installer repair

- Fixed the Linux server launcher so the post-install initializer receives the
  requested `init` command instead of an extra executable-name argument.
- Prepare the private server state directory before creating its locked system
  account, avoiding a misleading missing-home warning during installation.
- Install the server runtime under its own private library root so the server
  and desktop Debian packages can be installed together without file clashes.
- Added package-launcher regression coverage and documented both GitHub Release
  installation and recovery from an unfinished 0.26.12 package configuration.

## 0.26.12 — self-hosted server preview

- Refreshed the complete user, operator, architecture, configuration, security,
  testing, platform, release-channel and roadmap documentation for the 0.26.12
  implementation; the existing update trust root remains unchanged.
- Added the first self-hosted Linux server preview with a separate `.deb`,
  hardened systemd service, headless reuse of the sync/peer engines, bounded
  opaque mailbox/rendezvous/object/collaboration storage, allowlisted relay,
  attestation, read-only MCP, authenticated API, and a default-off desktop
  Settings feature flag whose token remains in the native credential store.

## 0.26.11 — maximized scrollable dialogs

- Open every desktop dialog maximized on its current monitor instead of shrinking the requested layout to a fraction of the available work area.
- Preserve each dialog's intended content dimensions inside an automatic two-axis scrolling canvas, keeping controls reachable on smaller displays without compressing the layout.
- Build the Android release package with the configured release signing key when an unreleased bumped version is published directly from `main`.

## 0.26.10 — responsive controls and optional live rendering

- Made every desktop dialog resizable and automatically scrollable when its content exceeds the monitor work area or the user shrinks the window.
- Made Android Settings a fully scrollable screen so all controls remain reachable on small phones and in split-screen mode.
- Added persistent one-click hide controls for the desktop and Android network meter; hiding it stops periodic sampling and rendering until it is re-enabled in Settings.
- Added persistent one-click hide controls for the desktop live activity log and Android Activity destination; hiding them stops log rendering until they are re-enabled in Settings.
- Preserved existing visibility defaults and configuration compatibility for upgrades.

## 0.26.9 — approval-based local collaboration

- Replaced the circular manual-key LAN pairing flow with discoverable folder advertisements and explicit owner approval requests.
- Let a host select and advertise a folder before any collaborator is authorized; no file service starts until a device is approved.
- Scope approved LAN invitations to the requesting device while retaining SSH public-key authentication and pinned server fingerprints.
- Added bounded, deduplicated, expiring access requests with per-source rate limiting so LAN packets cannot silently grant access or grow memory without limit.
- Simplified the desktop workflow around **Share this folder**, **Request access**, and **Approve selected request**, while retaining invitations, QR exchange, roles, relay, and Tor settings as advanced paths.
- Disabled automatic router port mapping for new shares unless the owner explicitly enables it.

## 0.26.8 — circular penguin visual identity

- Replaced the product logo and application icon with the circular black-and-white penguin identity, retaining red only for the bow tie.
- Propagated the new identity through Linux, Windows, macOS and Android application surfaces, installers, status icons and repository documentation.
- Kept signed update checks responsive during active synchronization by routing their bounded manifest request through a dedicated control-plane lane while retaining the global byte-rate clock, HTTP timeout and signature verification.
- Preserved application behavior, configuration compatibility, security controls and update trust roots.

## 0.26.7 — Linux profile credential-store repair

- Fixed credential-enabled profile backup, restore, and desktop-to-Android QR export on Linux packages by using the packaged GNOME Secret Service integration directly instead of an undeclared Python module.
- Preserved current and pre-rebrand configuration-key entries while keeping Windows Credential Manager and macOS Keychain behavior unchanged.
- Kept configuration keys out of process arguments by passing new Secret Service values only through standard input.
- Added Linux backend, legacy compatibility, unavailable-service, secret-handling, and installed-package regression tests.

## 0.26.6 — secure Android profile transfer

- Added encrypted desktop-to-Android configuration transfer through bounded multi-frame QR codes with sequence and SHA-256 integrity checks.
- Fixed `.tdx` mobile migration by including the separate rclone configuration unlock key inside the AES-GCM envelope, validating usable remotes before replacement, and reporting the imported account count instead of claiming success after decryption alone.
- Store the imported rclone unlock key through Android Keystore so cloud accounts remain usable after an application restart; raw rclone imports keep a separate explicit unlock flow.
- Revised the complete automated suite to isolate it from real user configuration and installed provider tools, preventing local credentials or machine state from changing results.
- Expanded network, bandwidth, transfer-policy, recovery, updater and path/signature security coverage, including malformed operating-system counters and fail-safe cleanup.
- Added Android JVM tests for bandwidth/version validation and serialized embedded-engine access; both debug and release package workflows now run the matching unit tests before linting and assembly.
- Removed a brittle desktop UI source-text test that duplicated implementation strings without exercising behavior; visual GTK behavior remains an explicit manual release check.

## 0.26.4 — durable platform release channels

- Advanced the signed Linux update channel so installations on 0.26.3 can receive the idle-network optimizations.
- Made the Windows, macOS and Android package directories visible and permanent in the repository, with exact durable GitHub Release locations for installers too large for normal Git storage.
- Added release preflight checks that bind a release tag to the source version, verify every expected installer, emit SHA-256 checksum files and prevent an ordinary main-branch artifact build from being presented as a published update.

## 0.26.2 — lower idle network activity

- Reuse the verified rclone bisync baseline when realtime monitoring restarts, avoiding an immediate duplicate recursive cloud listing.
- Use targeted same-path provider checks for ordinary local file saves while retaining scheduled full scans, conflict reconciliation, failure deferral and mass-change protection.
- Skip redundant GitHub pushes when the local branch is not ahead and avoid Proton Drive's second recursive traversal on verified no-op runs.
- Replace frequent LAN discovery broadcasts with query-driven discovery and a low-frequency compatibility heartbeat.
- Use filesystem events to avoid idle recursive streaming-cache, peer-delta and one-time-drop inbox scans where supported, with conservative polling fallbacks.
- Add an enabled-by-default Settings switch for the desktop and Android network meter; disabling it stops sampling and hides the display without deleting accumulated daily totals.
- Pause desktop meter sampling while the window is hidden and reuse one background worker instead of creating a new thread every second.

## 0.26.1 — daily network transfer meter

- Added live device download/upload rates and persistent totals for the current day to the Linux, Windows and macOS desktop interface.
- Added the same compact traffic meter to the Android mobile interface using private OS traffic counters.
- Daily counters survive application restarts, reset automatically on a new local day, exclude loopback traffic where supported, and avoid false jumps after a counter reset.
- Made Debian CI artifact paths derive from the application version so source changes cannot silently rebuild an old release number.

## 0.26.0 — Windows, macOS, and Android packages

- Added Windows x64 setup/portable packages and a macOS application image built from the same GTK desktop UI as Linux.
- Added native Windows/macOS configuration, cache and log locations, native credential-store protection, portable process cancellation, verified Windows rclone bootstrap, WinFsp streaming support, and platform-safe update routing.
- Added a native Android Material UI for accounts, synchronized folders, cloud browsing, activity and transfer policies.
- Integrated the official pinned rclone 1.75.0 gomobile library in-process on Android, including encrypted configuration import/unlock, real cloud listing, SAF folder grants, WorkManager transfers, durable bisync state, keep-both conflicts and mass-deletion stops.
- Added reproducible CI jobs for Windows installer/portable ZIP, macOS DMG and installable Android APK. Developer artifacts are ad-hoc/debug signed until platform release certificates are configured.
- Expanded portability, native-key-store and native-package regressions; the Python suite now contains 251 tests.

## 0.25.3 — renamed GitHub repository recovery

- Recognize GitHub's verified HTTPS rename redirects when a saved repository URL and the checkout origin use the old and new repository names.
- Keep rejecting unrelated repositories, redirects outside GitHub, and malformed canonical destinations.
- Persist the checkout's canonical origin after a verified rename so subsequent scheduled synchronization does not require another network identity check.

## 0.25.2 — durable two-way sync recovery

- Store rclone bisync baselines in durable application data instead of the disposable cache, while migrating valid existing baseline pairs automatically.
- Detect initialized two-way jobs whose baseline pair is missing or incomplete and recover them with the conservative `newer` resynchronization mode.
- Recover the same state-loss race when it is reported by the safety preview, while keeping authentication and all other preview failures fail-closed.
- Report successful automatic reinitialization explicitly in the job status and synchronization log.

## 0.25.1 — Nautilus emblems and online-folder action

- Cached Nautilus's credential-free state snapshot and normalized job roots in memory, invalidating them only when the atomic metadata monitor fires, so status emblems appear quickly even in large directories.
- Restored visible Nautilus status emblems with explicit icon-theme identities.
- Kept legacy emblem aliases so overlays survive a live upgrade from the pre-rebrand extension.
- Replaced the synchronized-folder **Share link** action with **Open online folder** in all six languages.
- Open exact private provider folders or GitHub branches where supported, never create a public share link, and safely fall back to the authenticated provider root where no stable private item URL exists.

## 0.25.0 — complete TuxInDrive rebrand

- Renamed the product, Python distribution/module, executable, desktop application ID, systemd service, Nautilus extension, icons, documentation, translations, update client, build artifacts, and repository links from TuxDrive to TuxInDrive.
- Preserved existing configuration, state, caches, recovery records, Proton snapshots, peer identities, encrypted rclone credentials, profile backups, shared-folder protocol metadata, and enabled user services through explicit compatibility fallbacks.
- Added `tuxdrive` command/service aliases only for upgrade continuity. The Debian package identity and signed legacy download alias remain a compatibility ABI so 0.24.x can verify and install the rebrand; all user-visible installed components use TuxInDrive.
- Added rebrand, legacy-directory, Secret Service, profile-format, peer invitation, Nautilus metadata, package-transition, and updater bridge regressions.

## 0.24.1 — functional Proton CLI bootstrap

- Fixed Proton connection on clean Linux installations. The 0.24.0 dialog linked to a Proton URL that currently returns 404 and required an executable that the package did not install.
- **Install CLI and connect** now reads Proton's live release manifest, selects the official amd64 or arm64 Linux executable, downloads it into TuxInDrive's private user-data directory, and continues directly into browser authorization.
- The manifest is accepted only from Proton's exact HTTPS location. The platform binary must match the SHA-512 checksum published in the same Proton release row before it is atomically installed with private executable permissions; mismatches and partial downloads are discarded.
- Added download limits, redirect validation, cancellable installation, safe replacement, and regression coverage for architecture selection, checksum substitution, untrusted manifests/hosts, cancellation, and existing-binary preservation. The complete suite now contains 221 automated tests.

## 0.24.0 — official Proton Drive browser authorization

- Replaced new and reconnected Proton/rclone password login with Proton's official `proton-drive auth login` browser flow. Passwords and 2FA codes stay on Proton's page; the official CLI owns its session in Linux Secret Service.
- Added native Proton account persistence, `/my-files` validation and folder browsing, one-session enforcement, browser reconnect/logout, and safe migration that retains old job definitions while pausing the legacy backend.
- Added scheduled two-way, download-only and upload-only Proton reconciliation using official machine-readable file operations. Nested exceptions, transient-file filtering, path confinement, symlink refusal, timeouts/cancellation, redacted errors, atomic private state and pre-transfer mass-change protection are enforced.
- Disabled Proton files-on-demand and real-time callbacks because the official CLI exposes no mount or sync-event API. One-sided deletions are restored rather than propagated; `Newer wins` safely falls back to keep-both because no atomic provider primitive is available.
- Added Proton authorization, expiry, traversal, credential-store override, redaction, incremental reconciliation, deletion restoration, mass-change, symlink, exclusion, backend-routing, no-rclone, no-callback and no-mount regressions. The complete suite now contains 215 automated tests.

## 0.23.0 — event-driven performance and bounded cache

- Replaced two-second per-job local tree walks with recursive Linux inotify monitoring; queue overflow and uncertain directory topology fail closed into full reconciliation.
- Added adaptive 30/60/120/300-second remote polling, immediate activity checks and delayed authoritative reconciliation without duplicate post-transfer tree walks.
- Coalesced GTK refresh bursts, retained account/job rows for status-only updates, and stopped hidden or collapsed live-log reads.
- Deduplicated configuration and Nautilus state writes while preserving atomic replacement and `fsync` for changed configuration.
- Cached rclone compatibility by executable identity, made LAN advertising conditional, and removed startup's `network-online` dependency.
- Added conservative pin-aware cache quotas. Pinned, dirty, active, symlinked and uncertain objects are never evicted.
- Lazy-loaded optional dialog modules and expanded recovery, cache-safety and performance regression coverage.

## 0.22.0 — selectable modern application designs

- Implemented the three approved visual systems: **Nordic Glass**, **Bento Cloud**, and **Midnight Sync**. All use rounded controls, card-based account/folder/group surfaces, clearer hierarchy, and provider/status identity without changing synchronization behavior.
- Added **Settings → Visual design**. The selected theme is validated, stored in the private configuration, applied immediately after saving, and restored on the next launch. Legacy or invalid theme values safely fall back to Nordic Glass.
- Bento Cloud adds live connected-service, active-sync, and protected-folder summary tiles. Midnight Sync supplies a high-contrast navy/cyan workspace and dark GTK preference; Nordic Glass is the airy blue-white default.
- Kept drag/drop, grouping, minimized provider icons, streaming controls, account actions, live logs, six-language/RTL text, and accessibility structure intact. Added theme palette, persistence, fallback, dark-mode, localized-control, package-presence, and UI integration regressions; the complete suite now contains 178 automated tests.

## 0.21.1 — functional GTK folder drag and drop

- Fixed the drag handle accepting a pointer gesture without completing a drop. The 0.21.0 source advertised a private binary target but used GTK's text conversion helpers, so the destination received no synchronized-folder identifier.
- Folder rows now exchange a bounded, TuxInDrive-prefixed payload through GTK's recognized same-application UTF-8 target. Existing-entry validation remains mandatory before any list order or group metadata changes.
- Enlarged the drag handle's input area and added an explicit drag icon. Added payload round-trip and malformed/unrelated-data regressions; the complete suite now contains 173 automated tests.

## 0.21.0 — drag-and-drop folder organization

- Added drag handles to synchronized-folder rows. Dropping a row above or below another row changes its saved position; dropping it on a group header moves it into that group. Local paths, provider paths and file content are never moved.
- Added persistent collapsible groups. A minimized group hides its full folder rows and shows one compact provider icon per synchronized folder next to the group name, with folder/provider details available as a tooltip.
- Kept the existing **Group** dialog as an accessible keyboard-friendly alternative, and added localized drag/drop and expand/minimize guidance in English, German, French, Spanish, Arabic and Hebrew.
- Added pure layout-order regression coverage, collapsed-state configuration migration/round-trip coverage, package UI assertions and complete localization checks. The complete suite now contains 171 automated tests.

## 0.20.11 — durable Nautilus constructor compatibility

- Fixed the remaining provider-independent post-download menu failure. Nautilus 4.1 exposes `sensitive` as a writable GObject property, but `Nautilus.MenuItem.new()` accepts only `name`, `label`, `tip` and `icon`; passing `sensitive` as a fifth constructor keyword raised `TypeError` only when the pending/offline branch was built.
- The availability item is now created with the documented four-argument constructor and sensitivity is applied afterward with `set_property()`. Completed files retain the enabled **Free local space (make online-only)** action, while a pending download remains visibly disabled without suppressing the TuxInDrive submenu.
- Replaced the permissive menu-item test double with the exact Nautilus 4.1 constructor boundary and added separate pending and completed regressions. The complete suite now contains 163 automated tests.

## 0.20.10 — Nautilus 4.1 offline-action compatibility

- Fixed the provider-independent exception that removed the complete TuxInDrive submenu after a file entered pending or verified offline state. `Nautilus.MenuItem` exposes sensitivity as a GObject property; it does not implement the GTK widget method `set_sensitive()`.
- The pending action now supplies `sensitive=false` through the supported menu-item constructor property. Completed files retain an enabled **Free local space (make online-only)** action on Google Drive, OneDrive and every other streaming backend.
- Corrected the Nautilus test double so it no longer invents the unsupported method, and added a pending-file regression that fails on the old implementation. The complete suite now contains 162 automated tests.

## 0.20.9 — durable post-localization Nautilus menu

- Replaced retained caller-owned `Nautilus.FileInfo` wrappers with stable URI keys. Completion refreshes now reacquire the current file object from Nautilus's cache before invalidating its badge metadata, avoiding stale FUSE wrappers after a streamed file becomes local.
- Added the dedicated MenuProvider `items-updated` signal and full Nautilus 4 menu callbacks, so the TuxInDrive submenu is rebuilt independently of badge invalidation and continues to expose **Free local space (make online-only)** after localization.
- Added regression coverage proving the extension retains no caller-owned file objects, reacquires the live cache entry, emits a menu refresh, and preserves the completed-file online-only action. The complete suite now contains 161 automated tests.

## 0.20.8 — terminal offline hydration and persistent Nautilus actions

- Moved each offline file read into an isolated helper with a progress-based inactivity watchdog. A responsive large transfer may run for any duration, while a provider read that makes no progress for 60 seconds is terminated and retried once.
- Guaranteed a terminal availability state: after both attempts stall or fail, TuxInDrive rolls back the rule, clears the pending badge and reports an actionable retry error instead of leaving Nautilus spinning indefinitely.
- Added an upgrade transition that stops only the exact older TuxInDrive application process, preventing a newly installed Nautilus extension from forwarding actions to an older in-memory engine.
- Coalesced the config/state metadata burst after a completed pin, primed the last-known-good snapshot before refreshing badges, and discarded stale FUSE `FileInfo` handles before Nautilus re-enters the provider. The TuxInDrive menu now remains present and changes from **Keep available offline** to **Free local space (make online-only)** after the download completes.
- Normalized external job and availability-rule lists so malformed or mixed-version metadata cannot raise an exception that makes Nautilus suppress the provider.
- Added regression coverage for stalled-reader termination, retry, rule rollback, package-upgrade process matching, coalesced metadata refresh and the pending-to-verified menu transition. The complete suite now contains 160 automated tests.

## 0.20.6 — exact cache verification and durable badges

- Matched pin manifests to rclone's real mount-relative VFS layout, including mounts rooted at a cloud subfolder, so completed file downloads no longer time out or lose their saved offline state.
- Added versioned pin-manifest records while preserving locally complete 0.20.5 manifests during upgrade.
- Restricted availability actions to explicitly selected Nautilus files/folders; the folder-background menu can no longer accidentally request recursive hydration of the current folder or drive root. Whole-drive offline retention remains an explicit in-app action.
- Retained the last complete runtime badge snapshot through atomic state-file replacement, so locally verified files do not revert to cloud-only icons while their cache remains valid.
- Added regression coverage for the real rclone cache layout, legacy manifest migration, background-menu isolation and persistent verified badges. The complete suite now contains 155 automated tests.

## 0.20.5 — stable per-file pinning and persistent Nautilus menu

- Removed the first/last-pin FUSE remount. The streaming mount now starts with one stable retention policy, so pinning one file does not detach Nautilus, rebuild the folder view, or cause adjacent files to be read while the view reconnects.
- Kept availability rules exact: a file rule applies only to that file, while folder and drive-root rules remain explicitly recursive.
- Retained the last complete credential-free job snapshot in the Nautilus extension, so an atomic state/configuration refresh cannot temporarily erase the TuxInDrive menu after a pin changes.
- Added direct extension regression tests for sibling-file isolation and last-known-good menu metadata. The complete suite now contains 151 automated tests.

## 0.20.4 — reliable per-file offline availability

- Fixed a single-file VFS race: TuxInDrive now waits for rclone to publish the exact, complete cache object before it records the file as available offline.
- Replaced FUSE file resolution in the Nautilus action route with lexical mount-relative matching; the engine still performs its symlink-safe confinement check before opening content.
- Added true individual-file regression coverage with delayed rclone cache publication and provider-option cache paths. The complete suite now contains 148 automated tests.

## 0.20.3 — explicit online-only/offline controls

- Stopped reconnect-time hydration: a streaming mount now verifies existing local pin markers without opening cloud files, so an old or root-level 0.20.2 pin cannot silently download the drive after startup.
- Restored the TuxInDrive Nautilus menu through an atomic, credential-free job snapshot; the extension uses that snapshot first and falls back to the full configuration only before the app has published runtime state.
- Added explicit **Keep available offline** and **Free local space (make online-only)** actions, including online-only child exceptions beneath an offline parent folder.
- Added a streaming-job control in the app to keep the complete drive offline or clear every offline rule/cache when Nautilus integration is unavailable.
- Added local pin manifests so reconnect verification performs no remote reads and green badges remain limited to locally confirmed content.
- Added upgrade, nested-rule, cache-release, snapshot and marker-confinement regression coverage; the complete suite now contains 145 automated tests.

## 0.20.2 — durable verified offline retention

- Replaced the one-time hydration heuristic with a live retention-policy transition: the first offline pin remounts the streaming drive with rclone's unaware age, size, and free-space eviction disabled, and the last unpin restores the normal bounded streaming cache.
- Rehydrates every persisted offline rule after a mount starts, so content cleared externally or partially evicted by an older release is downloaded again instead of being trusted blindly.
- Publishes green **Available offline** badges only for rules whose complete hydration finished in the current mount; pending, failed, stale, and disconnected pins no longer receive a false green state.
- Uses fast VFS fingerprints for pinned mounts to reduce remote metadata delay when opening already cached content, normalizes redundant parent/child rules, and rolls back the configured policy if remounting fails.
- Added retention-policy, remount, rule-normalization, and verified-badge regression coverage; the complete suite now contains 140 tests.

## 0.20.1 — reliable Nautilus offline-action dispatch

- Routed **Always keep available offline** and **Free local space** through registered in-process application actions when TuxInDrive is running, with the command-line path retained as a compatibility fallback.
- Removed the unrelated cloud-account discovery gate from hydration requests against an already mounted streaming drive.
- Queued cold-start requests until the streaming mount is ready, accepted both supported command-line option forms, and rejected duplicate hydration requests.
- Added visible desktop failure notifications and made Nautilus invalidate badges for atomic configuration/state-file replacements.

## 0.20.0 — reliable offline pinning, folder groups and GitHub sync

- Fixed **Always keep available offline** for both streaming-drive roots and nested items, with rollback on failed hydration and symlink-safe path handling.
- Added per-item Nautilus hydration metadata: blue synchronization arrows while content downloads and a green check with **Available offline** only after full hydration finishes.
- Added editable internal groups for synchronized folders. Creating, renaming, moving entries between, or deleting groups changes only TuxInDrive list organization and never moves local/cloud files.
- Added GitHub repository synchronization through system Git: clone, automatic commit, fetch, safe rebase and push for two-way jobs; fast-forward-only download mode; guarded upload-only mode; actionable conflict/authentication failures.
- GitHub credentials remain with the system SSH agent or Git credential helper. TuxInDrive rejects credential-bearing repository URLs and stores no GitHub token.
- Added GitHub URL/branch validation, offline hydration, group migration, package/icon and Git command regression coverage. The complete suite now contains 132 tests.

## 0.19.2 — visible functional Nautilus status badges

- Replaced the penguin-branded Nautilus status emblems with six compact functional badges designed to remain readable at normal Files icon sizes.
- Assigned every state a dedicated color, silhouette, and white foreground symbol: green check for synchronized, blue rotation arrows for synchronizing, teal cloud/download for files on demand, purple pause bars for paused, amber clock/diamond for pending, and red exclamation/octagon for error.
- Kept the existing Nautilus state mapping, live cache refresh, context actions, provider identity, and application branding unchanged.
- Added an SVG regression test that rejects a reused state color, missing accessibility description, wrong state identity, or return of the former penguin palette.
- Updated the illustrated user guide, roadmap, release packaging, and signed v2 update channel.

## 0.19.1 — signed updater trust bridge

- Restored automatic updates for 0.18.1 without weakening signature checks. The legacy `latest.json` channel remains signed by the original offline key and points only to 0.19.1.
- Moved 0.19.1 and later clients to the separately signed `latest-v2.json` channel using the rotated offline key, preventing a single static manifest from being interpreted under two trust roots.
- Added release tests that verify both manifests target the exact current Debian package and validate under their respective Ed25519 public keys.
- Kept the complete 0.19.0 critical/high remediation unchanged.

## 0.19.0 — critical/high security remediation

- Closed the in-app updater's privilege-boundary race. A fixed PolicyKit helper now independently retrieves and verifies the signed manifest, copies the user-owned package through a no-follow file descriptor into a root-only directory, verifies the immutable copy's SHA-256 and Debian identity, and only then invokes APT.
- Replaced shared peer authorization with a distinct SFTP listener and one-key authorization file per enabled device. Read-only/receive-only endpoints are server read-only; send-only devices receive an isolated inbox instead of workspace visibility.
- Moved one-time drops to dedicated per-invitation roots and ports, so a modified SFTP client cannot browse the containing workspace while its invitation remains active.
- Added persistent per-device endpoint allocation and multi-port Onion publication while retaining host-key pinning, direct/Tor policies and existing read/write behavior.
- Bounded collaborative operation counts and JSON size/schema, replaced recursive CRDT traversal, and rejected unsafe operation graphs.
- Hardened ODT/ODS import against ZIP bombs, duplicate/traversal entries, excessive archive/XML sizes and unsafe XML entities by using `defusedxml` and explicit resource limits.
- Added eight focused updater, peer-isolation, archive and deep/cyclic-CRDT regression tests; the complete suite now contains 125 tests.
- Documented the remaining medium hardening work in the roadmap and updated the repository and in-app security guidance.
- Rotated the offline update signing trust root. Version 0.19.1 subsequently introduced a separately signed legacy bridge after the original release key was recovered from protected storage.

## 0.18.1 — Arabic and Hebrew localization

- Added complete Arabic and Hebrew primary-interface translations and all 18 offline documentation chapters.
- Added explicit right-to-left rendering for Arabic/Hebrew labels, help search, topic titles and documentation bodies while retaining the established application layout and control positions.
- Extended localization parity and directionality regression tests to all six supported languages.

## 0.18.0 — in-app documentation and multilingual interface

- Added an offline, searchable Help Center with 18 chapters covering every primary cloud, streaming, recovery, peer, privacy, collaboration, migration, update and diagnostics workflow.
- Added persistent English, German, French and Spanish language selection from a flag menu in the top bar.
- Localized primary navigation, account and synchronized-folder actions without restarting or interrupting background transfers.
- Documented practical user HOWTOs in the app and repository, including safety boundaries and troubleshooting guidance.
- Added localization fallback, translated-help completeness and packaging regression tests.

## 0.17.0 — local-first collaborative documents

- Added an operation-based CRDT for offline multi-peer Markdown/plain-text editing with deterministic convergence and explicit interoperable checkpoints.
- Stored collaboration state separately as immutable per-device operation files suitable for the existing folder synchronizer.
- Added optional AES-256-GCM authenticated, expiring cursor/selection presence that is disabled without a shared key and excluded from long-lived audit logs.
- Added immutable comments, suggestions, tracked-change records, mentions, approvals and file tasks.
- Added structured experimental ODT and ODS import/export with deterministic archives, formula/style metadata, original XML recovery and round-trip warnings.
- Kept DOCX, XLSX, PDF and unproven binary formats in safe lease/version/review mode.
- Added the GTK collaborative editor under peer sharing, seven focused tests and updated documentation.
- Removed the experimental macOS package workflow and sources; release CI now produces the adaptive `.deb` and SBOM only.
- Published the signed 0.17.0 in-app update manifest and added a CI regression test that rejects manifest/package/version drift.

## 0.16.0 — adaptive Debian/GNOME packaging

- Added an experimental macOS 13+ Apple-silicon `.app`/`.pkg` CI build with Keychain-backed rclone configuration encryption, LaunchAgent login startup, native URL opening, pinned macOS rclone bootstrap and optional macFUSE handling. Finder integration, notarization and the automatic updater are not yet available.
- Added install-time and user-session host capability discovery with human-readable and JSON output through `tuxindrive --system-check`.
- Reduced the mandatory package set to the secure GTK/Secret-Service core and moved Nautilus, tray, FUSE, Tor, NAT, network-policy, QR, notification and update integrations to recommendations.
- Added per-feature availability and remediation reporting so an absent optional integration does not block unrelated cloud synchronization.
- Declared amd64 and arm64 as the supported verified-rclone bootstrap architectures and documented the current Debian, Ubuntu, GNOME and file-manager boundaries.
- Added packaging and platform-discovery regression tests and included the installation capability snapshot in `/var/lib/tuxindrive`.

- Raised Python-package installations to `cryptography` 50.0.0 or newer after the 0.15.1 dependency audit identified PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf in the previously allowed 46.x series.
- Kept Ubuntu `.deb` installations on the distribution-maintained `python3-cryptography` package so Ubuntu security backports remain installable without an impossible upstream-version constraint.
- Updated release packaging, SBOM paths, installer metadata and documentation to 0.16.0.

## 0.15.1 — comprehensive security hardening

- Added Ed25519-signed, expiring update manifests, bounded downloads, Debian package identity checks, and an external release-signing trust root.
- Bound Tor-only and no-public-IP peer endpoints to loopback and added explicit invitation transport allowlists that remove forbidden relay/direct fallback.
- Added descriptor-walk path confinement to reject symlink escapes during incremental transfer, delta application, recovery, integrity repair, and offline hydration.
- Signed block-delta instructions with the sender's Ed25519 identity, authorized signers on receipt, bounded delta resources, and retained safe full-transfer fallback.
- Fixed peer-role synchronization mapping; immediately rebuilds authorization and terminates sessions after consuming a one-time drop.
- Randomized and readiness-tested per-remote Tor SOCKS listeners, isolated Tor SSH wrappers, restricted pluggable-transport executables, strict relay host verification, and NAT mapping cleanup.
- Raised the cryptography dependency floor to 46.0.5, required rclone 1.75.0+, strengthened new profile backups to scrypt N=131072 with a 14-character minimum, bounded profiles, and excluded bridge material from non-sensitive backups.
- Added automatic rclone configuration encryption backed by GNOME Secret Service, while preserving independently encrypted advanced-user configurations.
- Hardened log/config permissions, sensitive child-process visibility, Python launcher isolation, Nautilus executable paths, CI action pinning, dependency auditing, static analysis, and SBOM generation.
- Retained peer sharing and one-time drops. Per-key server-side role/drop isolation remains explicitly deferred to the planned peer server authorization layer.

## 0.15.0 — Tor transport and fail-closed workspace privacy

- Added isolated Tor v3 Onion Services for peer workspaces with persistent or ephemeral service identity and no automatic clearnet fallback.
- Added per-device Tor v3 client authorization, invitation/QR transfer, key rotation by re-issuance, revocation files, and Tor reload handling alongside existing SSH identity and host-key checks.
- Added workspace transport policies for direct-only, Tor-only, no-relay, no-public-IP-discovery, and never-provider-cloud operation; violations stop or pause traffic and enter the private audit timeline.
- Added bridge and pluggable-transport profiles stored only in private Tor configuration, excluded from invitations, subprocess arguments, and TuxInDrive logs.
- Added GTK peer-workspace controls, protocol-v5 invitations, migration-safe configuration fields, Tor/torsocks/obfs4 package dependencies, and automated security tests.

## 0.14.0 — encrypted TuxInDrive Profiles and device migration

- Added a TuxInDrive Profile linked to an existing Google Drive, OneDrive, Dropbox, Box, or pCloud OAuth account; no TuxInDrive-operated account server stores the profile.
- Added local AES-256-GCM authenticated encryption with a memory-hard scrypt password derivation and a standard private cloud object path.
- Added backup discovery after OAuth account connection, password-protected metadata inspection, and in-app device restore with a local pre-migration configuration copy.
- Configuration-only backup is the safe default. OAuth credentials and peer private identities are included and restored only through an explicit sensitive-migration checkbox.
- Added wrong-password, tamper, cloud copy, settings migration, secret opt-in and private-permission tests; updated documentation, dependencies, package and update metadata.

## 0.13.1 — provider icons and compact job controls

- Job and account rows now consistently use the connected provider's icon instead of substituting the TuxInDrive/state icon.
- Synchronization state remains available in row text, tooltips, the health dashboard and Nautilus state emblems.
- Added an application-scoped GTK switch style, explicit size request and centered alignment to prevent oversized enable controls across Ubuntu themes and display scaling.
- Updated visual documentation, packaging metadata, regression checks and the verified update manifest.

## 0.13.0 — controlled peer access and operational visibility

- Added read/write, read-only, send-only and receive-only roles to named peer devices and protocol-v4 invitations, with migration-safe read/write defaults.
- Enforced role direction in complete and incremental synchronization; all-receive endpoints also launch the SFTP service in server-side read-only mode.
- Added expiring, upload-only encrypted file-drop invitations scoped to random hidden inboxes, with persistent first-file consumption markers.
- Added a private permission-restricted audit timeline for synchronization, policy, peer, block-delta and file-drop events.
- Added a provider capability matrix covering streaming, polling, hashes, server moves, versions and safe share links.
- Made job modes and share-link controls adapt to conservative provider capabilities and explain fallbacks in the folder dialog.
- Added a three-page operations dashboard for job/mount/callback health, audit events and provider capabilities.
- Expanded migration, role, expiry, direction, audit and capability regression coverage and updated the installer/documentation.

## 0.12.0 — efficient peer transfer, connectivity and desktop policies

- Added verified 4 MiB block-level delta transactions for direct peer callback updates, with BLAKE2 block checks, final SHA-256 verification and atomic receiver replacement.
- Added best-effort UPnP/NAT-PMP port mapping and an optional SSH reverse-tunnel relay that forwards encrypted SFTP traffic without storing file content or receiving TuxInDrive keys.
- Added persistent per-file/per-folder **Always keep available offline** and **Free local space** actions for streaming drives in Nautilus.
- Made Nautilus integration optional in Settings while retaining the default-on behavior.
- Added opt-in metered-network, battery-threshold and daily schedule policies; **Maximum usage** remains the unrestricted default.
- Added installer dependencies, migration-safe configuration fields, tests, release documentation and roadmap status updates.

## 0.11.4 — exact Google Drive folder navigation

- Resolves the selected Google Drive folder from its direct parent when `rclone lsjson --stat` omits the private item ID.
- Preserves My Drive, Shared-with-me, and Shared Drive scopes while resolving nested folders.
- Opens the selected folder's private Drive URL instead of falling back to the Drive home page.

## 0.11.3 — reliable Nautilus request delivery

- Replaced the desktop-dependent Nautilus D-Bus action discovery for online folders with a registered GApplication command-line request.
- Requests are forwarded to the primary TuxInDrive instance, logged on receipt, and handled without foregrounding the application window.

## 0.11.2 — monitored online-folder launch

- The Nautilus online-folder action no longer foregrounds TuxInDrive.
- Provider URLs are opened through a monitored `xdg-open` process, with its exit status and diagnostic output checked.
- Failed launches now produce a desktop notification and activity-log error containing the actionable desktop-handler detail.

## 0.11.1 — reliable desktop browser handoff

- Opens provider web folders through GNOME's registered default URI handler, fixing silent browser-launch failures when the action originates in Nautilus over D-Bus.
- Reports browser-launch failures in both the application activity message and diagnostic log instead of claiming that the folder opened.

## 0.11.0 — provider web folders and live Nautilus states

- Added **Open online/cloud folder** to the Nautilus TuxInDrive submenu.
- Opens exact Google Drive, Dropbox, Box, and supported OneDrive paths where provider identifiers allow it; otherwise opens the safe account root and explains the fallback.
- Never creates a public share link while opening an online folder.
- Added an atomic local runtime-state channel watched by Nautilus.
- Added live synchronized, synchronizing, streaming, paused, pending, and error emblems with automatic metadata invalidation.
- Added provider URL and no-public-link regression coverage.

## 0.10.3 — Nautilus 4.1 compatibility

- Fixed extension startup on Ubuntu 26.04 where Nautilus preloads GI namespace version 4.1.
- Removed the incorrect exact `Nautilus` 4.0 namespace requirement, following GNOME's host-loaded extension model.
- Restores TuxInDrive context menus, status metadata, and state emblems on Nautilus 4.1 while remaining compatible with Nautilus 4.0.
- Tracker and GSConnect warnings emitted during `nautilus -q` are unrelated desktop-service messages and do not affect TuxInDrive.

## 0.10.2 — visible Nautilus status emblems

- Fixed the Nautilus 4 `InfoProvider` callback contract and explicit completion result.
- Added packaged TuxInDrive emblems for synchronized, files-on-demand, and error states.
- Removed reliance on optional theme-specific emblem names.
- Icon cache refresh remains part of package installation; restart Nautilus once after upgrading.

## 0.10.1 — disconnected streaming mount recovery

- Fixed Nautilus directory failures caused by an orphaned FUSE endpoint returning `Transport endpoint is not connected`.
- Streaming-process failure now lazily detaches the kernel mount before automatic retry.
- Application startup recovers untracked configured streaming mounts left behind by a crash or forced shutdown.
- Nautilus status/menu matching now uses lexical local paths and never resolves or stats a streaming endpoint.
- Added regression coverage for startup cleanup and unexpected streaming-process exits.

## 0.10.0 — Nautilus desktop integration

- Added a native Nautilus 4 extension for Ubuntu 26.04.
- Added a TuxInDrive context submenu on configured local folders and their contents.
- Added safe **Show in TuxInDrive**, **Synchronize this TuxInDrive folder now**, and **Open TuxInDrive activity logs** actions.
- Added Nautilus status metadata and synchronized/error emblems for configured paths.
- Routed actions through the running TuxInDrive application so Nautilus never starts a competing transfer engine; startup-time requests wait for runtime readiness.
- Added extension packaging, dependency resolution, documentation, and automated coverage.

## 0.9.0 — multi-peer collaboration, leases, and local pairing

- Added multiple named authorized devices per shared folder, including enable/disable controls and immediate public-key revocation when the share is saved.
- Migrates legacy single-key peer shares automatically.
- Added cooperative expiring edit leases for peer jobs; active foreign leases pause incremental transfers and complete reconciliations.
- Added optional LAN-only multicast discovery without a central directory or intermediary storage.
- Added pinned host-key fingerprint presentation and explicit verification guidance for discovered peers.
- Added offline QR invitation generation and QR-image import using local `qrencode` and `zbarimg` tools installed by the Debian package.
- Added invitation protocol v2 with share identity and lease duration while retaining v1 import compatibility.
- Expanded automated coverage to 61 tests.

## 0.8.0 — recovery, integrity, and encrypted vaults

- Added per-job local version history and recycle recovery with configurable retention and one-click restore.
- Added dated backup handling for replaced/deleted data during normal synchronization.
- Added ransomware and mass-change protection for full-sync previews and incremental callback batches.
- Added automatic pausing when configured path/percentage/deletion thresholds or ransomware-like filename patterns are detected.
- Added non-destructive integrity audits and selected-path repair from an explicitly chosen local or cloud/peer authority.
- Added a conflict review center for content mismatches.
- Added client-side encrypted cloud vaults with encrypted content, file names, and directory names over an existing provider account.
- Added recovery, protection, audit, conflict, and vault controls to the GTK interface.
- Expanded automated coverage to 56 tests and updated the Ubuntu 26.04 Debian package and update manifest.

## 0.7.0 — direct encrypted peer collaboration

- Added direct peer-to-peer shared folders over authenticated encrypted SFTP with no intermediary file storage.
- Added generated Ed25519 identities, exchanged public keys, pinned host verification, and editable IP/DNS/port settings.
- Added Proton Drive credential setup and an on-demand in-app 2FA challenge.

## 0.6.x — provider expansion and authentication hardening

- Expanded the supported cloud set to Google Drive, OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, and Nextcloud.
- Added guided provider credentials where browser OAuth is unavailable.
- Added remote validation before an account is shown as connected.

## 0.5.x — branding and verified updates

- Added TuxInDrive penguin branding and provider-specific account icons.
- Added in-app update checking, visible progress, SHA-256 package verification, and PolicyKit-authorized installation.

## 0.4.x — selective sync, callbacks, and streaming

- Added the visual cloud folder tree, multi-folder selection, in-app activity logs, and activity-state icons.
- Added incremental saved-file callbacks, temporary-file suppression, moves/deletions, and clickable exception rules.
- Added FUSE files-on-demand streaming, hybrid synchronized/streamed layouts, mount diagnostics, and restart handling.

## 0.2.x–0.3.x — desktop runtime and synchronization foundation

- Added the GTK application, tray status, crash/startup diagnostics, OAuth account setup, and Debian packaging.
- Added two-way/one-way synchronization, conflict policies, deletion limits, Google location discovery, and transfer-engine compatibility handling.
