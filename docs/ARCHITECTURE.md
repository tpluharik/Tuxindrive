# TuxInDrive architecture

This document describes how TuxInDrive 0.26.28 is implemented. Job failures
persist a bounded structured reference (reason, time, reported source path and
exact private log path); the desktop error dialog reads at most the final 64
KiB of that one confined log, redacts common credential forms, and never starts
a provider or conflict scan. It complements
the task-oriented [user guide](USER_GUIDE.md), persisted-field
[configuration reference](CONFIGURATION.md), and threat-focused
[security guide](SECURITY_HARDENING.md).

## System overview

TuxInDrive is a local orchestration layer around provider APIs, rclone, Git,
the official Proton Drive CLI, operating-system credential stores, and
platform file APIs. The desktop application is Python with GTK 3. Android is a
native Kotlin/Jetpack Compose application embedding rclone through gomobile.
Cloud data does not pass through a TuxInDrive service unless the user explicitly
enables the separate server preview and selects one of its opaque coordination
roles. Enabling it does not reroute existing cloud or direct-peer transfers.

```text
Desktop GTK / Android Compose UI
              |
       persisted models
              |
 policy + admission + safety controls
              |
  +-----------+-----------+----------------+
  |                       |                |
rclone processes / RC   native Git    Proton CLI
  |                       |                |
cloud, SFTP, crypt      github.com     Proton Drive
```

The desktop process owns configuration and job scheduling. Transfer tools own
provider protocols. This separation keeps OAuth/provider compatibility in
rclone while TuxInDrive implements user intent, safety previews, concurrency,
recovery, audit, desktop integration, and release verification.

## Desktop process

`TuxInDriveApplication` in `src/tuxindrive/app.py` is the composition root. It:

1. Loads `AppConfig` through `ConfigStore`.
2. Creates the shared `GlobalBandwidthController`.
3. Creates the signed `UpdateManager`, `RcloneClient`, `ProtonDriveClient`,
   `SyncEngine`, peer manager, policy manager and UI controller.
4. Registers command-line and single-instance application actions.
5. Builds `MainWindow`, account dialogs, job dialogs, integrity/recovery views,
   settings, help and status/tray integration.

Long operations run outside the GTK main loop. Completion is returned to GTK
through idle callbacks. UI refreshes are coalesced so logs and status updates
do not force unnecessary full-window reconstruction.

### Local synchronized-folder search

`search_index.py` maintains a rebuildable SQLite cache under the platform cache
root. Each refresh walks configured local synchronization roots with no-follow
filesystem operations, applies the job's exclusion patterns, and upserts only
name/path metadata under a scan generation. A complete refresh deletes older
generations; cancellation or the per-root 250,000-entry bound retains the last
complete unseen rows. Removed jobs are pruned.

Unicode NFKC/casefolded search text supports case-insensitive multi-token
matching without storing file bodies. The database and parent directory use
private permissions on POSIX systems, and SQLite WAL mode lets the GTK search
window query the last committed snapshot while a background refresh runs.
Streaming/FUSE jobs are excluded so index construction cannot enumerate a
remote directory or hydrate content. Opening a result re-resolves it, rejects a
new symbolic link, and confirms confinement to the indexed root.

`file_preview.py` is an opt-in selected-result path and is not called by index
construction or ordinary search. The search dialog gates it behind a
non-persistent, default-off feature switch, reuses the live root-confinement
check, and performs parsing on a worker thread. A monotonically increasing
request serial prevents a slow prior selection from replacing a newer preview
or repopulating a disabled/closed panel.

The preview service opens regular files with no-follow semantics and bounded
reads. Text and image inputs have fixed limits. ZIP-based office documents
have entry-count, member-size, expanded-size and compression-ratio limits and
use `defusedxml`; archive paths and duplicates are rejected. Optional PDF text
extraction receives a private temporary copy, a fixed three-page argument
list, an eight-second timeout and no shell. GTK decodes image bytes only after
the 32 MiB boundary and scales dimensions for the panel.

## Persisted model

`src/tuxindrive/models.py` defines five persisted aggregates:

- `Account`: provider identity and provider-specific metadata.
- `SyncJob`: local/remote mapping, mode, safety controls and runtime status.
- `FolderGroup`: display-only ordering and collapsed state.
- `PeerShare`: server-side peer authorization, roles, drops and transport rules.
- `AppSettings`: application, network, cache, profile and presentation settings.

`ConfigStore` serializes the model as UTF-8 JSON. Writes use a private temporary
file, `fsync`, and atomic replacement. An unchanged object is not rewritten.
Invalid JSON is moved aside with an `.invalid` suffix instead of being silently
overwritten. The complete field contract is in [Configuration](CONFIGURATION.md).

## Provider abstraction

`Provider` identifies Google Drive, OneDrive, Dropbox, Box, pCloud, MEGA,
Proton Drive, Nextcloud, S3-compatible storage, generic WebDAV, generic SFTP,
GitHub, peer SFTP, and encrypted vault accounts.
`capabilities.py` records whether each provider supports browser OAuth,
streaming, change polling, hashes, server moves, share links and versions.
The UI consults this matrix before offering a synchronization mode or action.

OAuth-capable rclone providers are configured through `RcloneClient`. MEGA,
Nextcloud, S3-compatible storage, WebDAV, and SFTP use explicit protocol fields.
Rclone configuration is encrypted and its password is retrieved through the
platform credential store. GitHub and Proton use dedicated native adapters
rather than pretending to be ordinary rclone remotes. Capability records are
intentionally conservative: generic WebDAV and SFTP do not expose public-link
creation, and every generated link must still be HTTPS.

## Synchronization engine

`SyncEngine` in `engine.py` owns command construction, process tracking,
callbacks, streaming mounts, queue admission and result normalization.

### Full jobs

- Two-way jobs use `rclone bisync`. The first run is an explicit resync/merge;
  later runs reuse durable baseline files stored under application data.
- Download mirrors use remote-to-local copy semantics.
- Upload mirrors use local-to-remote copy semantics.
- Streaming jobs use `rclone mount` with full VFS caching and a stable mount
  policy for the mount lifetime.
- GitHub jobs use fetch/rebase/commit/push operations implemented in
  `github_sync.py`.
- Official Proton jobs use `proton-drive` machine-readable list, upload and
  download operations implemented in `proton.py`.

Before destructive established jobs, the engine can run a dry preview and
apply mass-change/ransomware limits. Result objects contain success, message,
log path, incremental/dry-run state and special recovery conditions.

Every rclone-backed full job receives the persisted selective filter arguments
from `SyncJob.selective_args()`: normalized extension includes, a maximum byte
size, and a maximum modification age. The native Proton adapter evaluates the
same model before upload/download, while `search_index.py` omits locally
unselected files. Empty extension and zero size/age values preserve the prior
unfiltered behavior.

`search_index.py` stores metadata by default. A persisted, default-off feature
flag permits bounded text extraction through `file_preview.index_text_path`
for supported ordinary local files. Streaming roots are structurally
ineligible, so enabling content search cannot hydrate cloud placeholders.
`rclone.copy_between_remotes` provides non-destructive, preview-first
cloud-to-cloud copy with server-side transfer hints and global admission.

`managed_policy.py` parses the fixed root-controlled Linux policy path and
constrains provider availability, bandwidth, content indexing, cloud copy and
audit export. `recovery_advisor.py` maps persisted redacted failures to offline
operator guidance; it does not probe providers while an error dialog opens.

### Incremental callbacks

`callbacks.py` combines event-driven local monitoring with adaptive remote
reconciliation. Local inotify events are normalized and transient editor files
are excluded. Remote changes are detected with targeted or recursive `lsjson`
queries. Provider failures increase backoff. Successful scan intervals include
random jitter, preventing many jobs from issuing metadata requests at the same
instant.

Incremental work reserves the job ID under the engine lock **before** waiting
for a global network slot. This prevents a full job and a callback job for the
same mapping from starting concurrently. Multiple ordinary paths are batched
through private `--files-from-raw` manifests; incoming content is staged and
installed through confined filesystem operations.

### Global bandwidth controller

`bandwidth.py` supplies one application-wide control plane:

- validates a global rate such as `10M` or directional `2M:10M`;
- chooses the stricter global/per-job rate independently for upload/download;
- by default reserves configurable headroom and divides the remainder by one
  ordinary lane, one responsive update lane, and every enabled persistent
  streaming drive, because
  rclone's limit is otherwise process-local rather than application-global;
- adds rclone `--bwlimit` arguments to synchronization, mounts, scans,
  verification, repair and delta work;
- admits metadata, updates, native Git and Proton operations through a shared
  semaphore; native operations that cannot accept a byte-rate flag run
  exclusively while limiting is enabled;
- rate-limits application-managed update downloads with a shared byte clock
  and a separately budgeted responsive admission lane;
- produces bounded scan jitter.

The controller is a portable application-level safety mechanism, not an OS
traffic shaper. A long-lived streaming mount owns its own provider connection,
so automatic mode gives every configured mount a conservative stable share;
unused shares are deliberately not borrowed because doing so could recreate a
burst when another mount becomes active.

## Streaming and offline availability

`mount_command()` starts rclone VFS with full caching. Directory entries can be
browsed without downloading file bodies. Reads hydrate chunks into the cache;
writes are committed through rclone. `cache_manager.py` applies maximum-cache
and minimum-free-space rules while protecting pinned, open, dirty and recently
used content.

Offline rules are stored per job. Exact files and explicitly selected folders
are hydrated and verified. Online-only exceptions may override a parent pin.
Changing a rule does not remount the drive. `nautilus_support.py` and the
packaged extension expose the same operations in Linux file-manager menus.

## Safety, recovery and integrity

- `security.py` provides descriptor-based path confinement, no-follow checks,
  atomic installation and signed peer transaction verification.
- `recovery.py` archives replaced/deleted content, applies retention, detects
  mass changes and runs bandwidth-controlled `rclone check` audits/repairs.
- `delta.py` plans BLAKE2-identified blocks and final SHA-256 verification for
  peer delta transfers.
- Conflict policies are translated into rclone/native-provider behavior. The
  integrity UI attaches a resolution to each reviewed row and `recovery.py`
  confines every write. Keep-both retains the local path and atomically installs
  the remote bytes under a dated conflict filename.
- Vault accounts are rclone crypt layers over an existing provider remote.

## Peer and collaboration implementation

`peer.py` manages Ed25519/SSH identities, invitations, host-key pinning,
per-device authorization, request/approval LAN discovery, edit leases and isolated SFTP
listeners. Roles are enforced at both job direction and server authorization.
One-time drops use dedicated roots and expire/consume independently.

`tor.py` writes private Tor service/client configuration and enforces direct,
Tor-only or automatic transport policy. Optional NAT traversal and SSH reverse
relay setup never replace SSH host-key verification.

`collaboration.py` implements local operation logs, a bounded text CRDT,
presence/review metadata, checkpoints, and defensive ODT/ODS import/export.
Archive entry count, expanded bytes, compression ratio, paths and XML entities
are validated before structured document processing.

## GitHub implementation

`github_sync.py` accepts only credential-free `https://github.com/...` or
`git@github.com:...` repository URLs and validated branch names. Credentials
stay in the system Git helper or SSH agent. A download mirror fetches the
configured branch. Two-way mode stages/commits local changes, fetches, rebases
and pushes. Interactive prompts are disabled so background jobs fail clearly
instead of hanging.

## Proton Drive implementation

`proton.py` discovers or installs Proton's official CLI from Proton's signed
release metadata, verifies its SHA-512 digest, stores the executable privately,
and starts browser authentication. TuxInDrive never accepts Proton passwords or
2FA codes. The CLI owns its Secret Service session. The adapter confines
provider paths, redacts errors, rejects symlinks and uses non-destructive
deletion behavior. Streaming is unavailable because the CLI exposes no mount
API.

## Signed updater

`updater.py` selects a platform-specific `latest-v2.json`, verifies its Ed25519
signature and expiry, validates the URL origin and version-bound filename, then
downloads at most 1 GiB and verifies SHA-256. Linux passes the package to a
fixed PolicyKit helper. The helper copies into a root-only staging directory,
rechecks digest and Debian identity, and invokes APT. Windows opens the verified
installer; macOS opens the verified DMG. Android implements the same signature,
origin, filename, size and digest checks in `AndroidUpdater.kt`.
`AndroidUpdateWorker.kt` schedules default-on checks for the sideload flavor,
applies network and battery constraints, reuses only a digest-matching cached
APK, and posts an installer notification. The system package installer retains
the final approval boundary. Store builds compile with self-update disabled.

## Android implementation

Android is a native Compose application rather than a GTK port:

- `MainActivity.kt` renders Accounts, Sync, Files, optional Activity and a
  scrollable Settings screen; persistent visibility flags stop network/activity
  rendering when those surfaces are hidden.
- `RcloneCore.kt` wraps the embedded gomobile RPC API, private rclone config,
  browsing, bisync and the runtime bandwidth limit.
- `MobileSyncWorker.kt` uses WorkManager constraints and a foreground service.
- `AndroidUpdateWorker.kt` performs rate-limited signed-channel checks and
  verified atomic downloads without granting silent-install privileges.
  It mirrors a Storage Access Framework tree into app-private storage, checks
  deletion thresholds, runs bisync, then reconciles back to the selected tree.
- `MobileNetworkController` serializes browsing, sync and update downloads.
- `NetworkUsageMeter.kt` records current and daily device totals.
- `ProfileImporter.kt` decrypts the desktop profile, requires the separately
  protected rclone unlock key, and exposes both only to the transactional
  app-private import path. `ProfileQr.kt` assembles bounded multi-frame QR
  transfers with sequence and SHA-256 validation. `MobileCredentialStore.kt`
  encrypts the imported unlock key with Android Keystore so restart does not
  relock the configuration.

Only persisted URI permissions grant Android folder access. Unique WorkManager
names and a process mutex prevent duplicate scheduled/manual jobs.

## Server implementation

`server.py` is a GTK-free composition root for `tuxindrive-server`. It loads a
validated schema-1 server configuration, refuses non-loopback HTTP, hashes
bearer tokens before comparison, applies per-source request admission, creates
`ServerStore`, and starts only the roles named in `enabled_roles`.

`HeadlessAgent` composes `ConfigStore`, `GlobalBandwidthController`,
`ProtonDriveClient`, `SyncEngine`, `TransferPolicy`, and `PeerManager`. It can
schedule normal cloud/Git/Proton jobs, start enabled peer endpoints (including
configured Tor peer services), and expose redacted status plus explicit
sync/dry-run/cancel operations without importing GTK. Streaming/FUSE jobs are
deliberately not scheduled by the system service.

`server_store.py` owns private SQLite mailbox, rendezvous, content-addressed
object, collaboration and audit tables. Tenant identity comes from the
authenticated token mapping; payload columns remain opaque bytes, TTL/quota
checks run under one store lock, and WAL/full-sync durability is enabled.

`server_client.py` enforces origin-only URLs, HTTPS outside loopback, normal CA
verification, bounded JSON and authenticated requests. `server_credentials.py`
stores the bearer token in the platform credential service under a URL-derived
key. `AppSettings.server_integration_enabled` defaults to false, so no server
request occurs until the user explicitly enables integration.

The versioned API also provides an allowlisted bounded `CONNECT` relay, signed
manifest attestation and read-only MCP JSON-RPC. See [Server preview](SERVER.md).

`server_gui.py` is a separate GTK composition root for local administration;
the daemon and `server_service.py` remain GTK-free. The GUI exposes the complete
configuration schema, service lifecycle, tenant/bootstrap tokens and journal
view without changing the headless API or systemd execution path.

`server_admin.py` is the narrow PolicyKit privilege boundary used by that GUI.
It accepts fixed operations and fixed system paths only, never a shell command
or arbitrary destination. Configuration writes must arrive through a
caller-owned, mode-0600, non-symlink regular staging file; the helper parses and
validates the complete `ServerConfig`, writes atomically and restores the
service account ownership before returning.

## Platform integration

- Linux: Secret Service, systemd user service, AppIndicator, Nautilus 4,
  PolicyKit and FUSE.
- Windows: Credential Manager, installer/portable packages, WinFsp and portable
  process groups.
- macOS: Keychain, application DMG, macFUSE and native `open` integration.
- Android: app sandbox, SAF, WorkManager, foreground notifications and package
  installer intents.

See [Platform support](PLATFORM_SUPPORT.md) for the supported matrix.

## Brand asset pipeline

`branding/tuxindrive-logo.png` is the transparent high-resolution master: a black-and-white penguin inside a white circle with a red bow tie. Desktop windows resolve this master from the source tree, PyInstaller bundle, or installed Debian documentation path and fall back to the icon theme only when no packaged asset is available. Linux packages install the scalable mark plus 16–256 px hicolor variants; the syncing and attention icons retain the mark and add distinct blue/red state badges.

PyInstaller receives the checked-in Windows ICO and macOS ICNS explicitly, so executable, installer, application bundle, taskbar, and dock identities do not depend on host defaults. Android adaptive icons use the same transparent master over a neutral black background, while a separate alpha-only resource supplies the system-themed monochrome icon. README and user-documentation images reference the master directly. Provider and Nautilus state icons remain function-specific and are not replaced by the application brand.

## Module map

| Module | Responsibility |
|---|---|
| `app.py` | GTK application, dialogs, settings, scheduling and UI composition. |
| `models.py`, `config.py` | Persisted schema and atomic private configuration. |
| `engine.py`, `callbacks.py` | Full/incremental sync, mounts, process state and reconciliation. |
| `bandwidth.py`, `policies.py` | Global network admission/rates and environmental policy decisions. |
| `rclone.py`, `bootstrap.py` | Provider configuration and transfer-runtime discovery/bootstrap. |
| `github_sync.py`, `proton.py` | Native GitHub and Proton backends. |
| `recovery.py`, `security.py`, `delta.py` | Recovery, destructive-change guards, confinement and verified deltas. |
| `peer.py`, `tor.py`, `collaboration.py` | Peer transport, privacy policy, leases and collaborative documents. |
| `cache_manager.py`, `nautilus_support.py` | Streaming-cache retention and Linux file-manager integration. |
| `migration.py` | Encrypted profile backup and device restore. |
| `updater.py`, `update_helper.py` | Signed platform updates and privileged Linux installation. |
| `network_usage.py`, `audit.py`, `diagnostics.py` | Usage accounting, local audit timeline and support diagnostics. |
| `capabilities.py`, `platform_support.py` | Provider/platform feature gating and integration discovery. |
| `themes.py`, `i18n.py`, `help_content.py` | Presentation, localization and offline help. |

## Extension points

Adding a provider requires a `Provider` record, capabilities, connection UI,
icons, redaction rules, command/backend routing, tests, and user/security docs.
Adding a persisted field requires a backward-compatible default in the model,
validation in `from_dict`, UI behavior, round-trip tests and an entry in
[Configuration](CONFIGURATION.md). New network paths must use the global
controller. New incoming filesystem paths must use confinement helpers and
negative traversal/symlink tests.
