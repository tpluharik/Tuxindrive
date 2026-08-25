# TuxInDrive

<p align="center"><img src="branding/tuxindrive-logo.png" width="180" alt="TuxInDrive circular black-and-white penguin logo with a red bow tie"></p>

<p align="center">
  <a href="https://github.com/sponsors/tpluharik"><img src="https://img.shields.io/badge/Sponsor-TuxInDrive-EA4AAA?logo=githubsponsors&amp;logoColor=white" alt="Sponsor TuxInDrive through GitHub Sponsors"></a>
</p>

<p align="center"><strong>Like TuxInDrive?</strong> <a href="https://github.com/sponsors/tpluharik">Sponsor its continued development on GitHub</a>.</p>

TuxInDrive is a native Linux, Windows, macOS and Android client for **Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, Nextcloud, S3-compatible storage, WebDAV, SFTP, and GitHub repositories**. Linux, Windows and macOS share the GTK desktop interface; Android uses a native mobile layout over the same rclone synchronization engine and platform-safe storage controls.

📥 **[Official downloads](docs/DOWNLOADS.md)** · 📚 **[Complete documentation index](docs/README.md)** · 📘 **[Illustrated user guide](docs/USER_GUIDE.md)** · 🏗️ **[Technical architecture](docs/ARCHITECTURE.md)** · 📦 **[Marketplace distribution](docs/MARKETPLACE_DISTRIBUTION.md)**

Release maintainers can reuse the factual [0.26.23 community announcement notes](docs/ANNOUNCEMENT_0.26.23.md) when inviting testers and contributors.

⚙️ **[Configuration](docs/CONFIGURATION.md)** · 🩺 **[Operations](docs/OPERATIONS.md)** · 📦 **[Release process](docs/RELEASES.md)** · 🧪 **[Testing](docs/TESTING.md)** · 🛡️ **[Security](docs/SECURITY_HARDENING.md)** · 💡 **[Roadmap](docs/ROADMAP.md)** · 📝 **[History](CHANGELOG.md)**

🔐 **[Security policy, trust boundaries, and vulnerability reporting](SECURITY.md)**

🖊️ **[Code signing policy](docs/CODE_SIGNING_POLICY.md)** — free code signing
provided by SignPath.io, certificate by SignPath Foundation; official release
signing is restricted to verified GitHub-hosted builds and manual approval.

🖥️ **[Self-hosted TuxInDrive Server preview](docs/SERVER.md)** — separate Linux `.deb` with its own graphical administration application, headless synchronization/peer agent, encrypted mailbox/rendezvous/object/collaboration roles, allowlisted relay, attestation and read-only MCP. Client integration is disabled by default behind a Settings feature flag.

## TuxInDrive rebrand and upgrade compatibility

The primary TuxInDrive identity is the penguin inside a white circle with a red bow tie. The artwork outside the source circle and its former wording are not part of the application brand. The same mark is embedded in the GTK header and dialogs, Linux icon theme, Windows executable and installer, macOS application bundle, Android adaptive/themed launcher icon, repository overview, and user documentation.

Version 0.26.28 adds immediate **Error details** beside **View log**, including
the persisted reason, reported source path, endpoints, timestamp, exact job log,
and a bounded redacted error excerpt without waiting for a conflict scan. It
retains S3-compatible, generic WebDAV, and SFTP accounts; per-job selection by
file extension, maximum size, and maximum age; searchable version history; and
a per-file graphical conflict resolver with a non-destructive **Keep both**
choice. A separate, explicitly confirmed action can create an HTTPS provider
share link only where the capability matrix declares that safe.
It retains the marketplace metadata from 0.26.26, secure automatic Android
updates, opt-in bounded previews, private filename search, monitor-safe dialogs,
aggregate bandwidth protection, and bidirectional integrity repair.
Existing accounts, synchronized content, collaboration approvals, encrypted
profiles and updater trust roots remain compatible.

The old `tuxdrive` executable and user-service names remain aliases for upgrade continuity. The Debian package identity and signed download alias intentionally remain legacy compatibility identifiers so the already released 0.24.x updater can authenticate and install 0.25.0 after the GitHub repository rename.

## Community and development

TuxInDrive is publicly readable. Direct repository writes remain restricted to maintainers, while everyone can participate through [Issues](https://github.com/tpluharik/TuxInDrive/issues), comments, forks, and pull requests.

- [Report a bug](https://github.com/tpluharik/TuxInDrive/issues/new?template=bug_report.yml)
- [Suggest a feature](https://github.com/tpluharik/TuxInDrive/issues/new?template=feature_request.yml)
- [Contribution guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

The current 0.26.28 desktop targets Ubuntu 24.04/26.04, Debian 12/13, Windows 10/11 x64 and macOS 12+; Android 8+ uses its native mobile interface. The main window remains freely resizable; settings and other dialogs open at a monitor-safe maximum and keep oversized controls reachable through local scrolling. **Nordic Glass**, **Bento Cloud**, and **Midnight Sync** are persistent visual designs. Folder grouping/reordering changes only interface metadata, while explicit offline/online-only controls, streaming mounts, GitHub synchronization, searchable offline help, private cross-folder filename search with default-off previews, six-language localization and functional Nautilus badges preserve their established behavior.

Idle and active traffic share one global controller. Event-driven local monitoring, adaptive remote backoff, bounded jitter, atomic incremental admission, unchanged-state write suppression, visibility-aware network/log rendering and conservative pin-aware cache limits reduce background work without weakening reconciliation, signed updates, mass-change protection, conflict handling or path confinement. A local collaboration host selects a folder and advertises it on the LAN; no file endpoint starts until the owner approves the requesting device fingerprint.

Proton Drive uses Proton's official browser-authenticated CLI on supported Linux systems. TuxInDrive verifies Proton's published SHA-512 before a private install and never receives the password or two-factor code. Scheduled two-way, download-only and upload-only jobs are confined to `/my-files`, honor nested exclusions and mass-change checks, and use non-destructive deletion behavior. Proton streaming remains disabled because the official CLI exposes no supported mount API.

### Current security baseline

- Python/PyPI installations require `cryptography>=50.0.0,<51` following PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf. Ubuntu `.deb` installations use Ubuntu's maintained `python3-cryptography` package so official security backports remain valid.
- CI blocks releases on high-severity Bandit findings or audited vulnerable Python dependencies and produces a CycloneDX SBOM with the Debian installer.
- The optional server keeps `/etc/tuxindrive-server` root-owned, confines service writes to runtime state, bounds authenticated request/relay concurrency, and applies request/relay deadlines plus systemd resource ceilings.
- Android update downloads remain signature/digest bound, accept only explicit HTTPS GitHub release redirect origins, are installed from a durable atomic cache file, and request sideload permission only in the sideload build. The sideload app now checks automatically, respects network/battery constraints, and notifies the user before Android's mandatory installer approval.
- The complete control inventory, upgrade procedure, credential migration behavior, residual risks, and operator checklist are in the [security-hardening guide](docs/SECURITY_HARDENING.md).

The following controls are enforced in 0.26.28:

- Signed and expiring update manifests are verified in both the desktop process and a fixed privileged helper. The helper stages the package in a root-only directory and rechecks its digest and Debian identity before APT executes it.
- Tor-only/no-public-IP shares bind SFTP to loopback, and protocol-v5 invitations carry an explicit transport allowlist so direct-only and no-relay policies cannot silently fall back.
- Incremental download, recovery, integrity repair, offline hydration, and block-delta paths reject symlinked parents/targets outside their configured root.
- Block-delta instructions are signed with the sender's Ed25519 peer identity and accepted only from an authorized device; unavailable delta signing safely falls back to a complete file transfer.
- Encrypted profile backups use a stronger scrypt work factor and 14-character minimum for new backups while retaining read compatibility with version-1 profiles.
- OAuth/configuration subprocesses disable same-user process inspection on Linux; logs/configuration files use explicit private permissions; the launcher runs Python in isolated mode.
- Provider tokens/passwords for rclone-backed services are migrated into rclone's authenticated encrypted configuration; its random key is retrieved from GNOME Secret Service and never committed to application JSON. Proton's official CLI separately owns its browser session in Linux Secret Service; TuxInDrive never reads or exports it.
- Each authorized peer key receives an isolated listener and authorization file. Read-only/receive-only restrictions are applied by the server, while send-only and one-time-drop devices are rooted in private inboxes rather than the shared workspace.
- Collaborative operation logs and ODT/ODS imports have explicit count, byte, compression-ratio and schema limits; unsafe XML entities are rejected before document processing.
- GitHub synchronization accepts only credential-free `github.com` HTTPS or SSH clone URLs, validates branch names, disables interactive credential prompts, and delegates secrets to the system SSH agent or Git credential helper.
- One global controller applies the stricter application/job rate to every rclone path, serializes native network operations while limited, rate-limits updates, jitters scans, and reserves incremental jobs before network waits. These congestion controls do not bypass authentication, integrity, deletion, or path-confinement checks.

### 0.24.1 official Proton Drive browser authorization

- Choose **Connect account → Proton Drive → Install CLI and connect**. TuxInDrive downloads only the platform binary named in [Proton's official CLI manifest](https://proton.me/download/drive/cli/index.html), verifies its published SHA-512 checksum, stores it under the current user's private TuxInDrive data, then starts browser authorization. Complete password and 2FA entry only on Proton's page; TuxInDrive validates `/my-files` before saving the account.
- The official CLI supports one active Proton account session. Reconnect replaces that session safely. Existing legacy Proton/rclone jobs are paused until browser migration succeeds; the legacy encrypted rclone remote is then removed when possible.
- Choose two-way, download-only or upload-only synchronization. Proton jobs run on the configured schedule, never start rclone callbacks, and cannot select Streaming drive. The system check reports whether the optional official CLI is installed.

### 0.21.1 drag-and-drop groups, online-only/offline availability and GitHub

- Right-click a streamed file, folder, or drive root and choose **Keep available offline**. Blue arrows remain while TuxInDrive explicitly reads the complete selection into the durable VFS cache; a green check appears only after local verification. Reconnects never start that download automatically. Choose **Free local space (make online-only)** to remove the rule and cached bytes. A child can be made online-only even when its parent is pinned. The streaming-job button in TuxInDrive provides a whole-drive fallback if Nautilus integration is unavailable.
- Pinning or releasing one item never reconnects the streaming mount. File rules are exact; folder and drive-root rules are recursive only when those objects are explicitly selected. The stable retention cache is released through the per-item or whole-drive online-only controls.
- Select **New group** to create list-only groups such as Work, Personal, or Customers. Press the three-line handle on a synchronized-folder row, move the pointer, then release above/below another folder or on a group header. TuxInDrive 0.21.1 transfers the row identifier through GTK's recognized same-application text target so the drop completes instead of ending after the initial selection gesture. Select the group arrow to minimize it: full rows are hidden and one provider icon per synchronized folder remains beside the group name. The saved order, membership and minimized state survive restarts. **Group** remains an accessible dialog alternative. Renaming, reordering, grouping, minimizing or deleting groups never moves or deletes files.
- Select **Connect account → GitHub**, enter a credential-free repository URL, branch, local folder, mode, and commit identity. Two-way mode automatically commits local changes, fetches, rebases and pushes. Configure an SSH key or system Git credential helper for private/write access.

### 0.22.0 selectable visual designs

- Open **Settings → Visual design**, choose **Nordic Glass**, **Bento Cloud**, or **Midnight Sync**, then select **Save**. The new design is applied immediately and retained after restart.
- Nordic Glass is the airy blue-white default; Bento Cloud uses violet accents, pastel summary tiles, and friendly rounded cards; Midnight Sync uses navy surfaces, cyan state accents, and high contrast.
- Theme selection changes only application presentation. Account connections, synchronized-folder order, group membership/collapse state, local/cloud paths, and transfer behavior remain untouched.

### 0.15.0 private Onion workspaces

- Publish a peer workspace as a persistent or ephemeral Tor v3 Onion Service without opening an inbound public port.
- Issue and revoke a separate Onion client credential for each named device, carried by the existing offline invitation/QR workflow and protected again by pinned SSH identities.
- Enforce direct-only or Tor-only operation plus no-relay, no-public-IP-discovery and never-provider-cloud restrictions. TuxInDrive records a blocked audit event instead of silently switching transports.
- Configure advanced bridge/pluggable-transport profiles without copying bridge material into invitations, command lines, or application logs.

### 0.9.0 release highlights

This release expands private collaboration: each shared folder can authorize multiple named devices with immediate key revocation, peer jobs coordinate expiring edit leases, local shares can be discovered without a directory server, and invitations can be exchanged as offline QR images. Existing single-peer 0.7/0.8 configurations migrate automatically. See the [changelog](CHANGELOG.md) and [roadmap](docs/ROADMAP.md).

### 0.10.0 desktop integration

Nautilus now shows TuxInDrive status metadata and a right-click **TuxInDrive** submenu for configured folders and their contents. It can show the job in TuxInDrive, run its safety-checked synchronization, or open activity logs. Actions are sent to the single running application instance; if needed, Nautilus starts TuxInDrive in the background and waits until its transfer runtime is ready.

Version 0.10.1 hardens that integration against disconnected FUSE endpoints: the extension performs no path-resolution I/O, unexpected streaming exits detach stale kernel mounts immediately, and startup recovers orphaned configured mounts before reconnecting.

Version 0.10.2 corrects the Nautilus 4 information-provider callback and packages dedicated green synchronized, blue streaming, and red error emblems, ensuring badges do not depend on the active Ubuntu icon theme.

Version 0.10.3 removes an exact GI minor-version pin that blocked the extension after Ubuntu 26.04 preloaded Nautilus 4.1. The extension now follows GNOME's host-loaded namespace model and supports both Nautilus 4.0 and 4.1.

Version 0.19.2 replaces the penguin status overlays with compact, high-contrast functional badges. Synchronized, synchronizing, files-on-demand, paused, pending, and error use a green check, blue rotation arrows, teal cloud/download, purple pause, amber clock/diamond, and red exclamation/octagon respectively. Color, silhouette, and glyph all differ, so status is not communicated by color alone.

### 0.12.0 efficient transfer and connectivity policies

Version 0.12.0 adds verified block-level delta transactions for direct peer updates, automatic UPnP/NAT-PMP traversal, an optional SSH reverse-tunnel relay that forwards encrypted bytes without storing file content, per-file streaming availability controls in Nautilus, an optional default-on Nautilus integration flag, and metered-network/battery/schedule policies. Policy mode defaults to **Maximum usage**, preserving unrestricted behavior until the user explicitly enables controls.

### 0.13.0 controlled collaboration and operational visibility

Version 0.13.0 adds read/write, read-only, send-only and receive-only peer invitations; expiring upload-only encrypted file drops; a private local peer/sync audit timeline; a provider capability matrix that adapts mode and sharing controls; and a consolidated health dashboard showing running, mounted, callback, last-run and failure state. Existing peer invitations/configurations migrate to read/write behavior.

### 0.14.0 encrypted profiles and device migration

TuxInDrive Profile links the application to an existing Google Drive, OneDrive, Dropbox, Box, or pCloud OAuth account and stores a locally encrypted configuration backup in that user-owned cloud. On a new desktop, connect the same provider and restore from Settings. For Android, create a credential-enabled profile and either select the searchable `.tdx` file or scan the encrypted multi-frame QR transfer shown by the desktop. AES-256-GCM authentication and a memory-hard scrypt key derivation protect the bundle; its passphrase never leaves the devices. OAuth tokens, the separate rclone unlock key, and peer private keys remain excluded unless the user explicitly enables sensitive migration; the compact QR profile includes cloud credentials but deliberately omits peer private files.

## What works

- eleven storage providers: Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, Nextcloud, S3-compatible storage, WebDAV, and SFTP
- encrypted TuxInDrive Profile backup stored in a linked OAuth account, with discovery after provider connection and password-protected restore on a new device
- configuration-only backup by default; OAuth credentials and peer private keys require an explicit sensitive-migration opt-in
- provider-native browser OAuth where available, Proton's official browser-authenticated CLI, plus guided credential or app-password configuration for MEGA and Nextcloud
- Proton Drive authorization never accepts a password or two-factor code in TuxInDrive; the official CLI stores its single active session under service `ch.proton.drive/drive-sdk-cli` in Linux Secret Service and `/my-files` is tested before the account is saved
- scheduled non-streaming Proton synchronization through official upload/download operations, with nested exceptions, symlink refusal, redacted diagnostics, mass-change protection and non-destructive deletion behavior
- direct peer-to-peer collaborative folders between two TuxInDrive computers over encrypted SFTP, with no intermediary file server
- block-level peer delta transactions signed by the sender identity, with BLAKE2 block verification, final SHA-256 validation, atomic receiver replacement, and safe full-file fallback
- automatic UPnP/NAT-PMP port mapping and optional encrypted reverse-tunnel relay; the relay forwards ciphertext and stores no file content or TuxInDrive keys
- multi-peer shared folders with named device keys, enable/disable controls, immediate revocation, and an isolated authenticated server endpoint per device
- per-device read/write, read-only, send-only and receive-only roles enforced at both transfer and SFTP server boundaries; send-only devices see only their dedicated inbox
- expiring, dedicated-root encrypted file-drop invitations that cannot browse the containing workspace and retire after the first received file
- a private append-only peer and synchronization audit timeline with job, result, peer, path, and bounded diagnostic detail
- an operations dashboard showing sync/mount/callback health, recent failures, peer access mode, audit events, and provider capabilities
- a provider capability matrix for streaming, polling, hashes, server moves, share links and versions; unsupported modes/actions are disabled with an explanation
- cooperative expiring edit leases that pause peer synchronization instead of overwriting a file another device is actively editing
- optional LAN multicast discovery with host-key fingerprint confirmation, explicit owner approval, recipient-scoped invitations, and no central discovery service
- offline QR invitation display and QR-image import; no online QR service receives pairing data
- generated Ed25519 identities, exchanged public keys, host-key pinning, editable IP/DNS address and port, and per-share folder selection
- OAuth 2.0 authorization in the default web browser for Google Drive, OneDrive, Dropbox, Box, and pCloud—no provider password is given to TuxInDrive for those OAuth flows
- multiple accounts from either provider
- two-way synchronization with retained conflict copies
- per-job local version history and recycle recovery with configurable retention and one-click restore
- ransomware and mass-change protection that dry-runs established jobs, pauses suspicious rewrite/deletion bursts, and requires review before retry
- on-demand integrity audits with selected-path repair from either the local or cloud/peer side
- a conflict review center for choosing the authoritative version instead of silently overwriting differences
- client-side encrypted cloud vaults layered over an existing cloud account, including content, filename, and directory-name encryption
- rename and folder-move tracking to avoid unnecessary duplicate transfers
- download-only and upload-only mirror modes
- visual, lazy-loading cloud folder tree with multi-folder selective synchronization
- one private local filename/path index and desktop search window spanning all configured synchronized folders; content, symlinks and files-on-demand mounts are never scanned
- a default-off selected-result preview for bounded local text, image, PDF and office formats; enabling it does not add file contents to the search index
- separate Google location browsing for My Drive, Shared with me, and every Shared Drive
- a FUSE virtual-drive mode with full VFS caching for files-on-demand behavior
- streaming drives expose the complete cloud tree without downloading file contents; opening a file fetches it in chunks and keeps a bounded local cache
- Nautilus **Keep available offline** and **Free local space (make online-only)** controls for individual streamed files and folders
- streaming mount health checks, automatic restart after an unexpected disconnect, and prevention of overlapping/non-empty mount points
- hybrid layouts: a streaming drive may live inside a normal synchronized tree and is automatically excluded from parent full/incremental synchronization
- automatic background synchronization at a configurable interval
- real-time incremental synchronization: local save callbacks and cloud delta polling transfer only changed paths
- debounced change handling, move/delete propagation, and full-sync fallback for simultaneous conflicts
- automatic suppression of LibreOffice, Microsoft Office, browser, editor, and partial-download temporary files
- pause/resume, sync now, cancellation, and tray controls
- native Nautilus 4 status/emblem integration and context actions for configured TuxInDrive paths
- Nautilus integration can be disabled in Settings and is enabled by default
- optional metered-network, battery-threshold and daily schedule policies; these environmental gates remain disabled by the default Maximum policy
- one application-wide upload/download ceiling, including directional values such as `2M:10M`, shared by synchronization, streaming, scans, verification, updates, GitHub, Proton, and Android
- optional current-rate and daily-total network panel, controlled independently by a Settings feature flag
- live Nautilus state transitions and safe **Open online/cloud folder** navigation without public-link creation
- launch at login, desktop notifications, daily diagnostic logs
- clickable per-job exception rules with add/remove controls, deletion safety ceiling, bandwidth limits, and conflict policy
- interactive blocked-file recovery: safely exclude the file or explicitly allow and retry
- explicit per-job opt-in for Google files flagged as malware or spam; disabled by default
- refresh/reconnect OAuth and account removal from the desktop UI
- import of existing Google Drive and OneDrive remotes from rclone
- live in-app activity and synchronization logs
- account, folder, and tray icons with connected, synchronizing, paused, and error states
- original TuxInDrive penguin branding throughout the launcher, windows, tray, dialogs, installer, and documentation
- provider-specific icons for branded services and clear system icons for protocol backends in account selection and connected-account views
- in-app repository update checks with an Ed25519-signed expiring manifest, HTTPS download, SHA-256 verification, Debian identity check, and an independently verifying root-side PolicyKit helper
- update window with visible checking, download percentage, verification, installation, success, and failure states
- one-click display-name editing that does not rename local or cloud folders
- streaming preflight diagnostics, stale FUSE mount recovery, detailed mount logs, and a 45-second connection window
- startup, application, thread-exception, and native crash logging

## Install

| Platform | Package | Notes |
| --- | --- | --- |
| Ubuntu/Debian | `tuxindrive_0.26.28_all.deb` | Signed in-app Debian updates remain supported. |
| Ubuntu/Debian Server | `tuxindrive-server_0.26.28_all.deb` | Separate preview service; explicit enablement, bearer token, and TLS for remote access. |
| Windows 10/11 x64 | `TuxInDrive-0.26.28-windows-x64-setup.exe` | Same GTK desktop UI; install WinFsp for streaming drives. |
| macOS 12+ | `TuxInDrive-0.26.28-macos-*.dmg` | Same GTK desktop UI; install macFUSE for streaming drives. |
| Android 8+ | `TuxInDrive-0.26.28-android.apk` | Native phone/tablet UI, SAF folder access and OS-managed background sync. |

### Ubuntu and Debian

Ubuntu 22.04 LTS, 24.04 LTS, and 26.04 LTS can install the Launchpad build from the
official TuxInDrive PPA:

```bash
sudo add-apt-repository ppa:tpluharik77/tuxindrive
sudo apt update
sudo apt install tuxdrive
```

The archive keeps the historical binary package name `tuxdrive` so existing
signed-updater installations upgrade cleanly; the installed application and
commands are named TuxInDrive. Alternatively, download the release `.deb` and
run:

```bash
sudo apt install ./tuxindrive_0.26.28_all.deb
```

Open **TuxInDrive** from the application menu. Choose **Connect account**, select a provider, and complete its guided authorization. Then add a local synchronized folder or virtual drive. The same visual cloud tree and multi-folder selection are used for supported storage providers; GitHub uses a dedicated repository/branch/local-folder dialog.

The server is a separate package. Download it from the matching GitHub Release
and keep the required `./` local-file prefix:

```bash
cd ~/Downloads
sudo apt install ./tuxindrive-server_0.26.28_all.deb
```

Continue with the bootstrap token, service start, local health check, TLS rules,
and desktop feature flag in the [server operator guide](docs/SERVER.md).

For a streaming drive, choose an empty mount folder. It may be a child of a normal synchronized tree, for example `~/TuxInDrive/tpluarikgdrive/Online`, and TuxInDrive automatically excludes that subtree from the parent sync. A streaming drive must not be the parent of another sync job. Once connected, opening the mount folder loads the remote directory tree while file bodies remain online until opened.

For local collaboration, open the network icon, select **Share a folder**, choose the folder, and click **Share this folder**. Another user opens **Find on LAN**, scans, selects the folder, and chooses **Request access**. The owner compares the displayed device fingerprint and chooses **Approve selected request**; after the requester scans again, the recipient-scoped connection can be loaded and synchronized into a chosen local folder. No SFTP file endpoint exists before approval. Manual invitations, QR exchange, roles, Tor, relay, address, port, and opt-in router mapping remain available for advanced or remote use.

APT installs the secure graphical core and normally installs supported optional recommendations. The same package adapts when an integration is unavailable; check the actual logged-in desktop with `tuxindrive --system-check`. TuxInDrive installs a pinned, SHA-256-verified rclone engine into the user's private application directory when needed. Virtual drives require FUSE access; on managed systems an administrator may need to permit user mounts. See the [distribution compatibility table and adaptive installation guide](docs/PLATFORM_SUPPORT.md).

## Build from source

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
sh scripts/build-deb.sh
sh scripts/build-server-deb.sh
```

Maintainers can produce a signed Launchpad source upload with
`scripts/build-ppa-source.sh jammy` or `scripts/build-ppa-source.sh noble`.
Launchpad receives source packages and builds the final binaries inside the
matching Ubuntu series.

The Debian installers are written to `dist/tuxindrive_0.26.28_all.deb` and `dist/tuxindrive-server_0.26.28_all.deb`. Windows, macOS and Android artifacts are built by `.github/workflows/platform-packages.yml` on their native build hosts. Durable packages are attached to the matching GitHub Release; dedicated signed client channel manifests and package-location pointers live under [`releases/`](releases/README.md).

### Local-first collaborative documents

Open **Peer-to-peer sharing → Collaborate → Open collaborative editor**. Markdown and plain text changes are stored as immutable per-device CRDT operations in a hidden compatibility operation store, so offline peers converge after the containing folder synchronizes. **Merge peer changes** records local edits and merges remote operations; **Export checkpoint** updates the ordinary `.md`/`.txt` file for any editor. Optional presence is AES-256-GCM encrypted, expires quickly and is not copied to the long-lived audit timeline. Comments, suggestions, tracked-change records, approvals, mentions and tasks are immutable workspace review events.

ODT paragraphs/styles/comments/tracked-change markers and ODS cells/formulas are imported structurally. Deterministic export retains the original `content.xml` inside the snapshot for recovery and warns where unsupported inline features may flatten. DOCX, XLSX, PDF and unknown binary formats deliberately remain under edit leases, local versions and review rather than making an unsafe real-time claim.

### Documentation and language

Select the **?** button in the top bar to open the searchable offline documentation center. Its 18 chapters describe accounts and OAuth, visual folder selection, synchronization modes, streaming/offline files, every job action, exceptions, recovery, integrity/conflicts, peer/Tor sharing, collaborative editing, encrypted migration, Nautilus, updates, transfer policies, diagnostics and safe removal. Each chapter includes practical user steps.

The flag selector switches **English**, **German**, **French**, **Spanish**, **Arabic**, or **Hebrew** immediately and stores the choice privately. Arabic and Hebrew labels and documentation use right-to-left text flow without moving the interface controls. Provider and rclone diagnostics may remain in their source language so technical evidence is not mistranslated.

The current suite contains 426 automated tests (414 Python and 12 Android JVM tests), including approval-based LAN discovery; encrypted `.tdx`/QR interoperability and malformed-frame rejection; aggregate automatic bandwidth protection and independent directional limits; protocol-provider capability guards; selective transfer rules; per-file recovery resolution; cross-platform network-counter failure handling; path, symlink and signing-key security; bounded opt-in search previews; recovery retention and confinement; visual themes; exact Nautilus 4.1 integration; bounded FUSE hydration; asynchronous cloud-folder editing; drag/drop groups; GitHub and Proton guards; signed update channels; bounded server requests and relays; server installation, isolation and GUI privilege boundaries; hostile ODF/CRDT input; Android serialization and input validation; responsive desktop-window constraints; release packaging; and six-language help parity. See [Testing and release verification](docs/TESTING.md) for details.

## Suggestions and roadmap

The [feature status and top-40 roadmap](docs/ROADMAP.md) records shipped safety and synchronization work plus the proposed path toward optional Tor/onion transport, reviewed group security, self-hosted encrypted services and local-first multi-peer document collaboration—described as a long-term “Signal for files and cooperation” direction rather than a current security claim. Community discussion should use the feature-request issue form.

## Update from the app

Open **Settings → Check for updates**. TuxInDrive verifies the signed manifest and download before asking for authorization. A fixed root-side helper then obtains the signed manifest independently, copies the untrusted package into a root-only staging directory through a no-follow descriptor, and rechecks its digest and Debian identity before APT runs. No user-supplied digest or cloud credential is trusted by the helper. Restart TuxInDrive after a successful update.

**0.18.1 → 0.19.1 → current trust-root transition:** 0.18.1 verifies an original-key-signed legacy manifest and first installs the fixed 0.19.1 bridge. Version 0.19.1 switches to the separately signed v2 channel and can then install 0.26.28 and later releases. On 0.18.1, run the in-app update check a second time after restarting 0.19.1. Never bypass a signature error; a continuing failure means the manifest is stale, intercepted, or the installed package predates this bridge.

## Crash and startup diagnostics

TuxInDrive logs before importing any GUI libraries, so even early startup failures leave evidence:

- `~/.local/state/tuxindrive/startup.log` — launcher output and missing-runtime errors
- `~/.local/state/tuxindrive/tuxindrive.log` — rotating application and synchronization lifecycle log
- `~/.local/state/tuxindrive/crash.log` — uncaught Python/thread exceptions and native fault traces
- `~/.cache/tuxindrive/logs/` — individual rclone synchronization logs

Run `tuxindrive --diagnostics` to print the main diagnostic locations.

## OAuth application configuration

TuxInDrive can use rclone's default OAuth application configuration for personal installations. For production distribution or organizational deployment, register dedicated desktop OAuth applications and enter the client ID and secret in the connection dialog:

### Google Drive

1. Create a project in Google Cloud Console and enable Google Drive API.
2. Configure the OAuth consent screen and required Drive scopes.
3. Create an OAuth client of type **Desktop app**.
4. Add the intended users while the consent screen is in testing, or complete Google's verification/publishing process.

### Microsoft OneDrive

1. Register a public/native client in Microsoft Entra ID.
2. Allow the appropriate account audience (organizational, personal, or both).
3. Add delegated Microsoft Graph file permissions and `offline_access`.
4. Enable the native-client redirect/loopback flow required by desktop authorization.

Do not commit client secrets, access tokens, refresh tokens, or an rclone configuration file to this repository.

## Storage and security

- TuxInDrive settings live in `~/.config/tuxindrive/config.json` with mode `0600`.
- OAuth tokens and credential-provider secrets remain in rclone's encrypted config (normally `~/.config/rclone/rclone.conf`). TuxInDrive stores the random config password in GNOME Secret Service and retrieves it through a password command rather than application JSON or process arguments.
- Operational logs live under `~/.cache/tuxindrive/logs` and do not contain a config dump.
- First two-way synchronization merges both sides and prefers the newer version for an initial same-path collision. Later unresolved conflicts retain renamed copies.
- Every synchronization enforces a configurable maximum deletion count. Established jobs also perform a non-destructive preview and pause suspicious mass changes.
- Local recovery data is stored under `~/.local/share/tuxindrive/recovery`; retention is configured per job. Cloud-side version backups are stored in the job remote's hidden compatibility version area.
- Encrypted vault passwords are protected in rclone's private configuration. They are not recoverable by TuxInDrive; keep them in a password manager.
- Upgrading from 0.15.0 or earlier automatically migrates an unencrypted managed rclone configuration into authenticated encrypted form when GNOME Secret Service is available. Existing independently encrypted advanced-user configurations are preserved.
- The updater accepts only a non-expired Ed25519-signed manifest, an approved repository URL, the declared SHA-256 digest, and a Debian package whose embedded name/version match the requested release.

For the complete threat boundaries, sensitive file locations, dependency response, verification commands, backup advice, and remaining peer-server limitation, read [Security hardening and secure operation](docs/SECURITY_HARDENING.md).

Back up important data before introducing any new synchronization tool. A mirror or bidirectional sync intentionally propagates changes and, within the configured safety ceiling, deletions.

## Parity and scope

TuxInDrive implements the core desktop behaviors of the Windows clients through public provider APIs and rclone. It does not copy Microsoft or Google's proprietary source code, branding, telemetry, private protocols, or Office integration. Version 0.13.0 provides Nautilus 4.0/4.1 live status metadata, packaged state emblems, safe provider navigation, context menus, persistent per-file/per-folder offline availability controls, adaptive provider controls and an operational dashboard. It does not provide a kernel-level placeholder API identical to Windows Cloud Files or Office coauthoring hooks. Streaming-drive mode is the Linux-native files-on-demand equivalent.

## License

MIT. rclone is a separate program distributed under its own license.
