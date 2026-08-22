# TuxInDrive User Guide

<p align="center"><img src="../branding/tuxindrive-logo.png" width="150" alt="TuxInDrive circular black-and-white penguin logo with a red bow tie"></p>

This guide covers TuxInDrive 0.26.22 on Linux, Windows, macOS and Android. Windows and macOS retain the Linux GTK desktop layout, while Android reorganizes accounts, synchronized folders, cloud files, activity and settings for touch displays. Platform-specific installation and signing details are in [Platform support](PLATFORM_SUPPORT.md). Administrators and developers can continue with the [documentation index](README.md), [operations guide](OPERATIONS.md), and [architecture reference](ARCHITECTURE.md).

Credentials for rclone-backed providers are kept in rclone's authenticated encrypted configuration. TuxInDrive generates its configuration key locally and stores it in GNOME Secret Service; existing rclone configurations already encrypted by an advanced user are left under that user's password-command setup. Proton's official CLI separately stores its browser session in Secret Service under `ch.proton.drive/drive-sdk-cli`; TuxInDrive never reads or exports it. Do not delete either secret until the related accounts have been disconnected.

Version 0.26.22 is the supported security baseline. Upgrade older installations before reconnecting cloud or peer accounts. See [Security hardening and secure operation](SECURITY_HARDENING.md) for the complete control inventory and post-upgrade checklist.

### Upgrading from TuxDrive

The 0.25.0 upgrade changes all visible product names to TuxInDrive. Existing private configuration, state, cache, recovery, Proton and peer directories remain in place when present, and the new application reads them directly. Existing encrypted rclone keys, profiles and peer invitations remain valid. Compatibility aliases keep the old command and enabled user service functional, but new documentation and desktop integration use `tuxindrive`. No synchronized local or cloud folder is renamed.

> The screenshots use sample names and paths. They do not contain real account information.

## 1. Install and start

Download the package for your platform. On Ubuntu or Debian, install it with one command:

```bash
sudo apt install ./tuxindrive_0.26.22_all.deb
```

Launch **TuxInDrive** from Ubuntu's application menu. TuxInDrive remains active in the system tray when its window is closed. On first start it verifies or installs its private cloud transfer engine.

### Windows and macOS

Run the Windows setup executable or drag TuxInDrive from the macOS DMG to Applications. Both packages open the same account sidebar, synchronized-folder cards, settings and dialogs as Linux. Windows stores secrets in Credential Manager and needs WinFsp for streaming drives; macOS uses Keychain and needs macFUSE. File-manager badges remain Linux/Nautilus-only in 0.26.22.

### Android

Install the APK, then:

1. Open **Accounts**, enter the 14-character-or-longer profile passphrase, and either import a newly created credential-enabled TuxInDrive profile (`.tdx`) through Android's system file picker or choose **Scan encrypted profile QR** and scan every numbered frame shown by **Show mobile transfer QR** on the desktop. Success reports how many cloud accounts were unlocked and verified.
2. Open **Sync**, select a cloud account and optional cloud subfolder, then choose the Android directory through the system folder picker. TuxInDrive retains only the URI permission explicitly granted by Android.
3. Select Wi-Fi and charging constraints, automatic scheduling, and the global bandwidth ceiling, then choose **Sync now**. WorkManager owns deferred work and a foreground notification identifies long transfers.
4. Use **Files** to browse a connected cloud root without granting broad device storage access. File transfer uses the selected synchronized tree. **Activity** shows current and previous results; **Settings** controls background constraints, bandwidth, traffic display, and signed updates.

Android stages data in app-private storage, retains durable two-way baselines, keeps conflict copies, and blocks suspicious deletion batches before reconciling the selected Storage Access Framework tree. One process-wide network controller serializes browsing, synchronization, and update downloads; the native rclone core receives the configured byte rate. Android does not expose a transparent FUSE drive because the operating system does not permit desktop-style unrestricted mounts.

Encrypted profile backups are stored visibly as `TuxInDrive/TuxInDrive-Profile.tdx`. To move one to a phone, create a fresh backup with **Include credentials** enabled, then download/select that file or use the encrypted QR option. Android verifies the profile passphrase, the embedded rclone unlock key, and at least one usable remote before replacing its previous configuration; it stores the key through Android Keystore for restart continuity. A configuration-only or older credential backup without that key is rejected with an actionable message. The old hidden `.tuxdrive-profile` object is recognized for desktop migration but should not be used for new phone transfers.

![Main window overview](assets/01-main-window.svg)

The main window contains:

1. **Add account** (`+`) — connect Google Drive or Microsoft OneDrive.
2. **Cloud accounts** — connection and aggregate activity state.
3. **Account menu** — open online, reconnect OAuth, or remove an unused account.
4. **Add folder** — create a synchronized or streaming job.
5. **Provider icon and status** — each account/job keeps its Google Drive, OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, Nextcloud, GitHub, peer, or vault icon; the adjacent text and Nautilus emblem communicate synchronization state.
6. **Job controls** — sync/mount, stop, open, share, edit, log, and remove.
7. **Compact enable switch** — pause or resume an individual job without enlarging the row under high-DPI GTK themes.
8. **Live activity log** — current application and transfer activity.
9. **Settings** — visual design, startup, notification, and minimized-start preferences.
10. **Language flag** — switch English, German, French, Spanish, Arabic or Hebrew immediately; the choice is retained for future starts.
11. **Help (`?`)** — open searchable offline documentation with function descriptions and practical how-to guides.

### Choose a visual design

Open **Settings → Visual design**, choose one of the three designs, then select **Save**:

- **Nordic Glass** — the default airy blue-white workspace with soft shadows and crisp GNOME controls.
- **Bento Cloud** — violet accents, pastel cards, and live tiles for connected services, active synchronizations, and protected folders.
- **Midnight Sync** — a focused navy interface with cyan status accents, high contrast, and a dark GTK preference.

The change is immediate after saving and persists in `~/.config/tuxindrive/config.json`. It affects presentation only: connected accounts, job order, group membership, collapsed groups, local/cloud paths, and active transfers remain unchanged. An unknown value from a future or damaged configuration safely falls back to Nordic Glass.

### In-app documentation and language

Select **?** in the top bar. Choose a chapter on the left or type a word in the search field; matching titles and bodies remain visible. The documentation is installed with TuxInDrive, works offline, and does not send search terms anywhere. It covers all major user functions and safety boundaries in 18 chapters.

Select the flag next to **?** and choose **🇬🇧 English**, **🇩🇪 Deutsch**, **🇫🇷 Français**, **🇪🇸 Español**, **🇸🇦 العربية**, or **🇮🇱 עברית**. TuxInDrive saves the language in `~/.config/tuxindrive/config.json` and rebuilds only the visible window; background synchronization, mounts and peer listeners continue. Arabic and Hebrew labels, search fields, topic titles and documentation bodies render right-to-left, but the window, sidebar and controls retain their familiar positions. Provider-generated OAuth questions, raw rclone errors, logs and some advanced dialogs remain in their technical source language to preserve diagnostic accuracy.

The black-and-white penguin inside a white circle, with its red bow tie, identifies TuxInDrive itself. It is the same mark in the window header, dialogs, launcher, taskbar or dock, system tray, Android launcher, installers, and repository documentation. Content and wording outside the source circle are not part of the TuxInDrive identity. Each cloud service keeps its own provider icon while connected and in the account chooser; blue sync and red error badges communicate changing activity without altering the primary mark.

### Update TuxInDrive

Open **Settings** and select **Check for updates**. A progress window shows repository checking, the available-version result, download percentage, package verification, system installation, and the final success or failure. If a newer version is available, choose **Download and install**. After the desktop check, Ubuntu authorizes a fixed TuxInDrive helper—not arbitrary APT arguments. The helper independently retrieves the signed manifest, copies the package into root-only staging and rechecks the digest and Debian identity before installation. When installation completes, restart TuxInDrive. A failure leaves the existing installation unchanged.

When moving from 0.18.1, the legacy channel signed by its already trusted key first installs the fixed 0.19.1 bridge. Restart TuxInDrive, then use **Settings → Check for updates** again: 0.19.1 reads the separately signed v2 channel and installs the current 0.26.22 release. Never bypass a signature warning. If the error persists, close and reopen the update dialog to refetch the manifest; manual package installation remains the recovery path when a proxy or cache serves stale metadata.

### Rename an item in TuxInDrive

Select **Rename** on a synchronized or streaming job and enter the preferred display title. This changes only the label shown inside TuxInDrive; it does not rename or move the local folder or its cloud folder.

### Organize synchronized folders into internal groups

Select **New group** and enter an editable name such as Work, Personal, Customers, or Archive. Each synchronized-folder row has a drag handle at its left edge:

1. Press the three-line handle, move the pointer until the folder drag icon follows it, and release above or below another visible folder to change its saved position. Version 0.22.0 uses GTK's recognized same-application UTF-8 target so the drop receives the folder identifier.
2. Drop a folder on a named group header to move it to that group and append it after the group's existing folders.
3. Drop it on the **Ungrouped** header to remove its group membership.
4. Select the arrow in a group header to minimize the group. Its full rows disappear and one compact provider icon per synchronized folder remains beside the group name. Hover an icon to see the folder and service; select the arrow again to expand the group.

Order, group membership and minimized state are saved immediately and restored after restart. **Group** on a folder row remains a keyboard-friendly dialog alternative. The pencil button renames a group; the trash button deletes only the group and returns its entries to Ungrouped. These operations change TuxInDrive list metadata only: local folders, cloud paths, GitHub repositories, synchronization state, and file content are never moved or deleted.

### Synchronize a GitHub repository

Select **Connect account → GitHub** and enter a credential-free HTTPS URL such as `https://github.com/owner/repository.git` or an SSH URL such as `git@github.com:owner/repository.git`. Select a branch, an empty local folder or matching existing clone, synchronization mode, interval, commit author name/email, and optional internal group.

- **Two-way** stages and commits all local working-tree changes, fetches the configured branch, rebases local commits, and pushes. A rebase conflict is aborted automatically so the pre-run local state is restored; inspect the job log and resolve the histories manually.
- **Download-only** requires a clean working tree and applies remote changes only by fast-forward. It never commits or pushes local changes.
- **Upload-only** commits local changes but refuses to push when the GitHub branch contains commits missing locally.

TuxInDrive sets `GIT_TERMINAL_PROMPT=0` and never asks for or stores a GitHub token. Configure an SSH key/agent or a system Git credential helper before using private repositories or write access. Credential-bearing URLs, non-GitHub hosts, malformed branches, mismatched existing origins, non-empty non-repository folders, and unsafe non-fast-forward operations are rejected.

### Encrypted TuxInDrive Profile and device migration

![Encrypted profile backup and restore](assets/10-profile-migration.svg)

Open **Settings → TuxInDrive Profile / migrate** after connecting Google Drive, OneDrive, Dropbox, Box, or pCloud. Choose the account that will hold the profile, enter and confirm a unique backup password of at least 14 characters, then choose **Store encrypted backup**. New version-2 profiles use AES-256-GCM with scrypt `N=131072`; version-1 profiles remain readable for desktop migration. TuxInDrive encrypts locally before uploading `TuxInDrive/TuxInDrive-Profile.tdx`. TuxInDrive operates no account or configuration server and cannot see or recover the password. For a phone, enable credential inclusion before storing a `.tdx`, or choose **Show mobile transfer QR**; the QR path always includes only the cloud configuration and its unlock key, omits peer private files, and remains protected by the same profile passphrase.

On a replacement or additional computer:

1. Install TuxInDrive and connect the same OAuth provider account.
2. TuxInDrive detects the standard encrypted profile object and reports that a profile is available.
3. Open **Settings → TuxInDrive Profile / migrate**, enter the password, and choose **Inspect cloud backup** to review its source device, version, account count, job count, and credential scope.
4. Choose **Restore this device**. The configuration is validated before replacement and the previous local file is retained as `config.json.before-migration`.
5. Restart or reconnect jobs as needed. If the backup excluded credentials, authorize the restored provider remotes on this computer.

By default the bundle contains job definitions, display names, filters, policies, peer public metadata, and application settings—but no rclone OAuth/credential file or peer private identity. **Include OAuth credentials and peer private keys** is a sensitive, explicit opt-in intended for full device migration. Use it only with a strong unique backup password and trusted cloud account. The same checkbox must be enabled during restore to write those protected credentials. Losing the password makes the backup unrecoverable; exposing it and the encrypted bundle together can expose every opted-in account and peer identity.

## 2. Connect a cloud account

Select `+` or **Connect account**, then choose Google Drive, Microsoft OneDrive, Dropbox, Box, pCloud, MEGA, Proton Drive, or Nextcloud.

![OAuth account connection](assets/02-oauth.svg)

- **Account key** is TuxInDrive's local identifier. Use letters, numbers, dot, dash, or underscore.
- **Display name** is the friendly name shown in the sidebar.
- **OAuth client ID/secret** are optional for personal testing. A dedicated provider application is recommended for regular or organizational use.
- Google Drive, OneDrive, Dropbox, Box, and pCloud normally open browser OAuth. Sign in on the provider's page and approve access; TuxInDrive does not receive the cloud password.
- MEGA uses explicit provider credentials. Nextcloud asks for the server URL, username, and preferably an app password. Secret values are protected before rclone stores them in its private configuration; they are never stored in TuxInDrive's account JSON.
- Every provider exposes the same lazy-loading folder tree and multi-folder selection. The capability note disables modes the provider cannot safely support.
- Proton Drive uses Proton's official CLI and browser login. It supports scheduled two-way, download-only, and upload-only jobs, but not streaming or real-time callbacks because the official CLI exposes neither a mount API nor a sync-event API.
- If the browser callback port is busy, cancel the old authorization window and retry. TuxInDrive stops stale OAuth callback processes before opening a new session.

### Proton Drive authentication

Select **Connect account → Proton Drive → Install CLI and connect**. On amd64 or arm64 Linux, TuxInDrive reads [Proton's official CLI manifest](https://proton.me/download/drive/cli/index.html), downloads the matching official executable into `~/.local/share/tuxindrive/tools/`, and installs it only after its SHA-512 checksum matches Proton's published value. No `sudo` or terminal command is required. Keep the dialog open while entering the password and any two-factor code on Proton's page. TuxInDrive supplies no password, OTP secret, mailbox password, token, or callback data to the CLI; after login, it validates a machine-readable listing of `/my-files` before saving the account.

The official CLI maintains one active Proton account session. To change or refresh it, open the account menu and select **Reconnect / refresh credentials**, then complete browser authorization again. Removing the account runs the official logout command after all jobs have been removed.

Legacy Proton/rclone accounts are paused after upgrading. Reconnect them in the browser; TuxInDrive preserves their synchronized-folder definitions, switches them to the official backend, disables any old streaming job with an actionable edit message, and removes the unused encrypted rclone remote when possible. No legacy password is copied into the official session.

Native Proton synchronization is intentionally conservative. Nested exceptions and transient files are excluded, symbolic links stop the run, mass-change thresholds are checked before transfer, and one-sided deletions are restored instead of being propagated. `Local wins` and `Cloud wins` control replacement order; `Keep both` is the safe conflict default. Proton's official CLI does not yet expose an atomic newer-wins primitive, so a Proton job configured as `Newer wins` falls back to non-destructive keep-both behavior.

The account menu provides:

- **Open online** — opens the provider website.
- **Reconnect OAuth** — refreshes authorization without deleting jobs.
- **Remove account** — available after all jobs using that account are removed.

### Google cloud locations

TuxInDrive lists these separately:

- **My Drive**
- **Shared with me**
- every available **Shared Drive**

Changing the cloud location refreshes the visual folder tree. This prevents a remote preconfigured for one Shared Drive from hiding My Drive or other shared locations.

## 3. Direct encrypted multi-peer sharing

Select the network icon or open **Settings → Peer-to-peer sharing**. One sharing computer runs an authenticated SFTP endpoint backed by its selected folder. Any number of explicitly authorized TuxInDrive devices can connect with their individual keys. File data travels directly between endpoints and is not stored by TuxInDrive, GitHub, a discovery directory, or a cloud provider.

### Collaborative Markdown and text

1. Put a `.md`, `.markdown`, or `.txt` document in a synchronized peer or cloud folder.
2. Open **Peer-to-peer sharing → Collaborate → Open collaborative editor** and select it.
3. Give the device a stable name and choose **Open/import**. The first device imports the ordinary file into a separate hidden compatibility operation store.
4. Edit locally, including while offline. Choose **Merge peer changes** to persist the local delta and merge operations received from other devices. Every peer converges from the same operation set regardless of arrival order.
5. Choose **Export checkpoint** to update the ordinary Markdown/text file atomically for editors that do not understand TuxInDrive state.

The review row adds anchored comments, suggestions, tracked-change records, approvals, mentions in text and assigned file tasks as immutable events. Entering the same presence passphrase on participating devices enables AES-256-GCM authenticated cursor/selection presence. Presence expires in 5–300 seconds, is optional and is not written to the permanent peer audit timeline. A wrong presence key fails authentication instead of displaying untrusted cursor data.

Do not manually edit the hidden collaboration metadata directory. TuxInDrive rejects a changed immutable operation identifier. Back up that directory with the exported document if future collaborative editing must remain possible.

### ODT, ODS and binary office files

ODT and ODS support is explicitly experimental. TuxInDrive imports ODT paragraphs, heading/style references, comments and tracked-change markers, and imports ODS sheets, cell coordinates, text, styles and formulas. Export is deterministic. When an edit would flatten inline XML, TuxInDrive warns and stores the original `content.xml` as `TuxInDrive/original-content.xml` inside the new ODF archive for recovery. Always retain local version history and review the exported file in LibreOffice.

DOCX, XLSX and PDF are never routed to real-time editing. They use safe file leases, local version history, conflict review and approval workflows until format-specific convergence and round-trip testing proves real-time modification safe.

### Tor v3 Onion workspaces

On **Share a folder**, choose **Tor only (fail closed)** and enable **Publish a Tor v3 Onion Service**. A persistent service keeps its address across restarts; disabling persistence creates a disposable service identity. Tor-only startup fails visibly if Tor cannot publish the service, and TuxInDrive does not retry over the public address, LAN, NAT mapping, or relay.

Enable **Require per-device Onion client authorization** for private Onion discovery. TuxInDrive creates a separate X25519 authorization credential for the selected named device when its invitation is copied or rendered as QR. The host stores only that device's public authorization material; the client secret is transferred in the invitation. Exchange it through an authenticated channel and treat the QR as a password. Re-issue to rotate. Revocation removes the device file and requests a Tor reload; allow for Tor reload/restart timing before assuming that an already established circuit has ended. SSH device authorization and pinned host verification still apply after Tor accepts the circuit.

The restrictions are workspace-specific:

- **Direct only** refuses Onion and relay endpoints.
- **Tor only** refuses direct, LAN, NAT and relay fallback.
- **Never use a relay** rejects configured forwarding relays.
- **Do not discover or advertise a public IP** disables public addressing and router mapping.
- **Never use provider cloud** records the workspace's isolation requirement and prevents it from being treated as a cloud-backed job.

An incompatible transport produces a **blocked** event in the audit timeline. It never silently degrades. Bridge and pluggable-transport values are advanced censorship-resistance settings, not proof of anonymity. They are stored with mode `0600` in the isolated Tor instance and excluded from invitations and TuxInDrive subprocess arguments/logs.

![Direct peer sharing setup](assets/05-peer-sharing.svg)

![Multi-peer authorization, leases, and LAN pairing](assets/08-multi-peer-pairing.svg)

### Approve collaborators

Each installation creates a private Ed25519 identity. For local collaboration, the joining device sends only its public identity and display name as an access request; the owner must compare its fingerprint and explicitly approve it. Manual public-key exchange remains available for offline invitations and advanced remote setups. A device can be disabled temporarily or revoked by selecting it, choosing **Revoke selected**, then sharing the folder again.

### On the computer sharing the folder

1. Open **Share a folder**, choose a local folder, and click **Share this folder**. No collaborator key or network address is required for the local workflow.
2. TuxInDrive advertises the folder name and pinned host fingerprint on the local network. It does not start a file endpoint while nobody is approved.
3. On the joining computer, open **Find on LAN**, scan, select the folder, and choose **Request access**.
4. On the sharing computer, select the waiting device under **People and approval requests**, compare its `SHA256:` identity fingerprint with the person, choose the intended role, and click **Approve selected request**.
5. The joining computer scans again, selects the now-approved result, chooses a local synchronized folder, and connects. The invitation is scoped to that approved identity and the SFTP listener accepts only its SSH key.
6. Revoke or disable a device and share again to restart the listeners and terminate its active session. Manual key entry, invitations, QR pairing, Tor, relay, address, port, and lease controls remain available.

The IP/DNS address, port, folder, authorized devices, discovery state, lease duration, NAT behavior and optional relay remain editable. Saving restarts the endpoint with the new settings. Stopping or deleting a share never deletes files.

### NAT traversal and optional no-storage relay

**Automatically request UPnP/NAT-PMP port mapping** is disabled for new shares. Enable it explicitly under advanced settings only when the folder must be reachable beyond the LAN. TuxInDrive first asks the router to expose the selected peer port using UPnP, then tries NAT-PMP when available. This is best-effort: router policy, carrier-grade NAT and firewalls can still prevent direct access.

For those cases, enter an SSH relay hostname, SSH user, SSH port and unused public forwarding port. TuxInDrive creates a reverse SSH tunnel from the sharing computer. A connecting peer still uses TuxInDrive's pinned, encrypted SFTP session inside that tunnel; the relay forwards ciphertext, receives no TuxInDrive private key and stores no file body. The relay operator must enable remote TCP forwarding/GatewayPorts for the selected account. Leaving relay fields blank preserves direct-only operation.

### Block-level peer delta transfer

**Use block-level delta transfer** is enabled by default on new jobs. For direct peer callback updates, TuxInDrive divides a file into 4 MiB content-addressed blocks and compares the new BLAKE2 manifest with the last successfully transferred version. Only changed blocks plus a small instruction are uploaded through the authenticated, host-key-pinned transport into the peer transaction queue. The receiving TuxInDrive verifies every block, reconstructs a temporary file, validates its complete SHA-256 and atomically replaces the destination. A first transfer or missing manifest sends every block. Cloud backends continue using their provider/rclone native transfer behavior.

### LAN discovery and QR pairing

If **Visible on this local network** is enabled, open **Find on LAN → Scan local network** on another computer. Discovery uses local-scope UDP multicast and initially advertises only the share name, address, port, public host key, share ID, and lease duration. It does not expose file contents or authenticate a person and does not normally cross routers.

Select a result and choose **Request access**. The request contains the joining device's public identity, display name, random request ID, and target share; it cannot authorize itself. The owner compares the complete `SHA256:` device fingerprint and explicitly approves or rejects it. Requests are deduplicated, rate limited, capped, and expire after ten minutes. After approval, a scan returns an invitation scoped to that device's identity token; the SFTP endpoint still enforces the complete SSH key and the client pins the host key. Alternatively, use the retained invitation QR path. QR encoding and decoding occur locally; no online QR service sees the invitation.

### On the computer connecting to the folder

1. Open **Connect to a peer**, paste the invitation, and select **Load invitation**.
2. Review the displayed IP/DNS address, port, and host public key with the sharing user.
3. Select a local folder and choose **Save and connect**.
4. TuxInDrive first creates a temporary connection, pins and verifies the host key, and lists the peer folder. Only after that succeeds does it save the connection and start two-way synchronization.

The saved peer entry lets you continuously edit a changing IP/DNS address or port. Changes are verified before replacing the working endpoint. The same move, deletion, conflict, callback, exception, and logging rules used by cloud two-way synchronization apply.

### Safe edit leases

Peer jobs enable cooperative edit leases by default. Before an incremental local upload or deletion, TuxInDrive writes a short lease record into the hidden compatibility lease area and confirms ownership. It releases the record after transfer. A complete reconciliation pauses while a foreign, unexpired lease exists. Lease metadata is excluded from ordinary synchronization.

Leases reduce accidental simultaneous overwrites between TuxInDrive peers, but they are advisory application locks: they do not prevent another program, a non-TuxInDrive SFTP client, or a malicious authorized device from writing. A crash may leave a record until expiry; the timeout prevents permanent lockout. Use an application-specific collaboration system for databases or real-time coauthoring.

### Directional peer roles

Each named authorized device can be assigned one role before its invitation is copied:

| Role | Paired TuxInDrive behavior |
|---|---|
| **Read and write** | Two-way synchronization with the normal conflict, lease and deletion protections. |
| **Read-only** | Copies new/changed host content locally without deleting local extras or uploading changes. |
| **Send-only** | Uploads the device's selected local folder; it does not download host changes. |
| **Receive-only** | Mirrors host content locally, including allowed deletions; it never uploads local changes. |

Select the device row before choosing **Copy invitation** or **Show invitation QR**. The invitation carries the selected device's server endpoint and role. TuxInDrive 0.19.1 runs a distinct listener and one-key authorization file for every enabled device: read-only/receive-only is enforced by the server, send-only is rooted in a private inbox, and read/write sees the selected workspace. A generic SFTP client therefore cannot use a role-limited key to obtain broader workspace access.

### One-time encrypted file drop

Select a saved/running share, enter the sender's device name and public identity key, choose an expiry from 1–168 hours, then select **Create one-time file drop**. TuxInDrive creates a random hidden inbox with its own port and one-key server endpoint, then copies the invitation. The sender loads it, chooses a local folder, and sends over encrypted, host-key-pinned SFTP.

The server root itself is the drop inbox, so even a modified client cannot browse the parent workspace. The invitation expires at the encoded UTC time and is retired after a successful send. The host records a consumed marker and restarts endpoints without the temporary key. Ordinary synchronization excludes the hidden drop metadata area. A connection already authenticated when the first file arrives may finish its current transfer; strict per-drop file/byte quotas are scheduled hardening.

### Peer and synchronization audit timeline

The chart button in the title bar opens **Sync health and audit**. Its audit page records job starts, completions, failures, policy deferrals, verified peer connections, block-delta application, and one-time-drop creation/consumption. Records are stored locally in `~/.local/share/tuxindrive/audit.jsonl` with user-only permissions, capped by automatic compaction, and never contain credentials or private keys. Paths and peer display names are operational metadata; protect the local user account if those names are sensitive.

### Network and security limitations

- The sharing computer must remain running and TuxInDrive must remain active.
- For internet access, TuxInDrive first attempts UPnP/NAT-PMP. If automatic mapping is unavailable, configure a manual port forward, use a peer-reachable VPN, or enable the optional no-storage SSH relay. Carrier-grade NAT commonly requires the VPN or relay option.
- Permit only the selected port in the host firewall. Restrict it to the other peer's source IP where practical.
- The connecting public key authenticates the guest; the invitation's pinned host public key authenticates the server. If either key changes unexpectedly, stop and verify with the other user instead of bypassing validation.
- LAN discovery is convenience, not trust. Always compare the complete fingerprint.
- Revocation prevents future authentication after the share restarts; it cannot retract copies already downloaded by that device.
- Directional roles are enforced by both TuxInDrive jobs and per-key SFTP endpoints. This prevents broader access than the assigned root/mode, but it does not make files intentionally shared with a collaborator safe from that collaborator. Revoke lost or untrusted device keys immediately.
- Protocol-v5 invitations explicitly list allowed transports. **Tor only**, **No relay**, and **No public IP discovery** fail closed; TuxInDrive pauses and logs a policy event instead of silently falling back to clearnet.
- This is direct encrypted transport, not anonymous communication. Endpoint IP addresses are visible to each peer and to intervening network operators.
- Keep backups of important collaborative data: two-way synchronization intentionally propagates allowed changes and deletions.

## 4. Add synchronized folders

Select **Add folder**. Choose the account, drive/location, and one or more cloud folders in the tree.

The **Provider capabilities** row updates when the account changes. It explains whether the backend supports streaming, change polling, hashes and safe share links. Unsupported modes are omitted and unsafe actions such as share-link creation are disabled. Capabilities are conservative TuxInDrive defaults; Nextcloud and organizational provider configurations can vary, so live validation and the scheduled reconciliation safety net remain important.

![Selective synchronization dialog](assets/03-sync-setup.svg)

### Folder tree

- Expand arrows to load child folders on demand.
- Select **Entire cloud drive** for the full selected location.
- Select multiple folders to create one job and local folder per selection.
- The local folder chooser determines where downloaded data is stored.

### Synchronization modes

| Mode | Behaviour |
|---|---|
| **Two-way sync** | Changes, moves, and allowed deletions propagate in both directions. |
| **Download mirror** | Cloud is authoritative; local content mirrors it. |
| **Upload mirror** | Local content is authoritative; cloud content mirrors it. |
| **Streaming drive (files on demand)** | The cloud tree is mounted through FUSE; contents download only when opened. |

### Job options

- **Sync interval** — periodic complete reconciliation. It remains active as a safety net.
- **Real-time callbacks** — watches local saves (about two seconds) and polls cloud changes (about 30 seconds), transferring only changed paths.
- **Conflict handling** — keep both, newer wins, local wins, or cloud wins.
- **Maximum deletions** — safety ceiling for one synchronization run.
- **Local version history** — retains replaced/deleted content for recovery; enabled by default.
- **Version retention** — number of days local recovery entries are retained.
- **Ransomware protection** — previews established jobs and pauses suspicious change bursts.
- **Mass-change path/percentage limits** — job-specific thresholds that trigger the safety pause.
- **Bandwidth limit** — rclone notation such as `10M`.
- **Google security warning** — unsafe opt-in for files Google marks as malware/spam. Leave disabled unless the file is trusted.
- **Synchronization exceptions** — clickable rules; add a pattern or remove it with the minus button.

## 5. Operate a synchronization job

Each job offers:

- **Sync now** — start a complete reconciliation immediately.
- **Stop** — cancel the active transfer.
- **Open folder** — open the local folder in Files.
- **Open online folder** — open the synchronized provider folder or GitHub branch in the default browser without creating a public share link. Providers that do not expose an exact private folder URL safely open their authenticated Drive root and report that fallback.
- **History** — inspect and restore local versions or recycled files.
- **Verify** — compare both sides and repair reviewed paths from the chosen authority.
- **Conflicts** — open the conflict-focused review center.
- **Edit** — change the mode, paths, selection, interval, conflict handling, and rules.
- **Group** — organize the entry inside TuxInDrive without moving either synchronized endpoint.
- **View log** — open the directory containing transfer logs.
- **Trash button** — remove the job configuration without deleting local or cloud files.
- **Switch** — enable or pause automatic operation.

Status icons and labels change for idle/connected, synchronizing, paused, and error states. The account icon summarizes all jobs belonging to that account.

### Sync health dashboard

Select the chart icon in the title bar. **Sync health** shows each job's current running/mounted/error/paused state, mode, peer access role, callback-monitor state, last run, and latest detail. **Audit timeline** shows recent structured operational events. **Provider capabilities** compares all eleven TuxInDrive backends across streaming, polling, hashes, server moves and share links. Reopen the dashboard to refresh its point-in-time snapshot.

### Nautilus integration

Version 0.10.0 installs a native extension for Ubuntu Files (Nautilus 4). Right-click a configured synchronization folder, a subfolder, a file inside it, or the empty background of that folder and open the **TuxInDrive** submenu:

- **Show in TuxInDrive** opens the application and displays the containing job's current status.
- **Synchronize this TuxInDrive folder now** starts the containing normal synchronization job using the same conflict, deletion, ransomware, exception, and lease protections as the main window. Multiple selected files must belong to the same job.
- **Open TuxInDrive activity logs** opens the diagnostic log directory.
- **Open online/cloud folder** opens the matching private provider page where the backend exposes a safe item ID/path. Google Drive, Dropbox, Box, and supported OneDrive configurations can open exact items; other providers open their account root when available. This action never creates a public sharing link.

Configured paths expose TuxInDrive status metadata and a live state emblem to Nautilus. Files-on-demand drives show their streaming status; their content is still fetched by opening the file, so the explicit synchronization action is intentionally omitted.
TuxInDrive 0.10.2 added packaged status emblems and explicit Nautilus 4 metadata completion, so badge availability no longer depends on the desktop icon theme.

TuxInDrive 0.10.3 supports the Nautilus 4.0 and 4.1 GI namespaces used across supported Ubuntu installations. It intentionally does not request an exact minor namespace because Nautilus loads its own version before importing extensions.

TuxInDrive publishes job state and a minimal job/path snapshot through a private atomic cache file watched by the extension. Badges refresh among pending, synchronizing, synchronized, streaming, paused, and error states when application state changes. The snapshot contains job identifiers, local paths, modes and availability rules only—never OAuth tokens, passwords, private keys, provider configuration or file content. Version 0.25.1 keeps the last complete snapshot and normalized synchronized-folder roots in memory, then reloads them only after the metadata monitor reports an atomic update; opening a large folder therefore does not re-read and reparse JSON for every icon. The extension coalesces config/state events emitted when a pin completes and stores only stable URIs rather than Nautilus-owned FileInfo wrappers. It reacquires current cached FileInfo objects for badge invalidation and emits Nautilus's dedicated menu-update signal. Every menu item is created with Nautilus 4.1's documented four constructor fields; pending-action sensitivity is then applied with the writable GObject property. The TuxInDrive submenu therefore remains present while its file action changes from **Keep available offline** to **Free local space (make online-only)**, and a transient read cannot repaint verified offline files as cloud-only.

When **Keep available offline** is used on one file, TuxInDrive reads that complete file in an isolated helper and briefly waits for rclone to publish the matching full-size VFS cache object before showing the green check. It does not resolve or stat the selected FUSE path during Nautilus routing; the transfer engine validates the mount-relative path and rejects symlink escapes immediately before hydration. The helper may run for any total duration while bytes continue arriving. If no bytes arrive for 60 seconds, TuxInDrive cancels the blocked reader and retries once; a second stall rolls back the rule, clears the blue pending badge and reports an error. If the provider does not publish a complete cache object within ten seconds after a completed read, TuxInDrive likewise reports an error and does not leave a false offline marker.

Version 0.19.2 removes the TuxInDrive/penguin mark from these overlays and makes every badge purely functional. The mapping is deliberately redundant—each state has its own color, silhouette, and symbol:

| State | Badge | Meaning |
|---|---|---|
| Synchronized | Green circle with check | The normal synchronization baseline has completed. |
| Synchronizing | Blue circle with rotation arrows | A transfer is currently running. |
| Files on demand | Teal rounded square with cloud/download | The path is a connected streaming drive. |
| Paused | Purple square with pause bars | Automatic operation is disabled or stopped. |
| Pending | Amber diamond with clock | The job has not completed its initial synchronization. |
| Error | Red octagon with exclamation | The job needs attention; open TuxInDrive or its logs for detail. |

Nautilus integration is enabled by default. Disable **Settings → Enable Nautilus integration** to hide all TuxInDrive menus, metadata and emblems; restart Files with `nautilus -q` after changing the flag. Synchronization and streaming continue without the extension.

The extension sends requests to TuxInDrive's single application instance. If TuxInDrive is closed, it starts in the background and waits for the verified transfer runtime before starting a requested job. It never runs a second independent transfer engine inside Nautilus.

After first installation or upgrade, close and reopen Files. If the submenu does not appear, run `nautilus -q` once and reopen Files. Non-local URIs, unconfigured folders, and disabled jobs do not receive synchronization actions.

![TuxInDrive actions and status inside Nautilus](assets/09-nautilus-integration.svg)

## 6. Incremental synchronization

When **Sync saved file changes immediately** is enabled:

1. TuxInDrive debounces editor save sequences.
2. It compares local and cloud snapshots.
3. Only created, changed, moved, or deleted paths are transferred.
4. Echo events created by TuxInDrive's own transfer are absorbed to avoid loops.
5. If the same path changed on both sides, TuxInDrive runs the normal reconciliation path.

LibreOffice/Microsoft Office lock files, editor swap files, browser partial downloads, and `.part` files are ignored automatically. A temporary file that disappears during transfer is treated as a harmless skipped event.

## 7. Streaming files on demand

A streaming drive exposes real file names, folders, sizes, and modification times without downloading file bodies. Opening a file reads it in chunks and places accessed content in TuxInDrive's private VFS cache. Writes are uploaded after the write-back delay.

### Per-file offline availability

Select a file or folder, right-click that selected item and choose **TuxInDrive → Keep available offline**. A file selection reads and tags only that exact file; a selected folder is deliberately recursive. The empty folder-background menu does not expose an availability action, preventing an accidental recursive request for the current folder or drive root. Whole-drive retention remains available through the explicit **Keep drive offline** button in TuxInDrive. TuxInDrive stores a versioned persistent rule and local pin manifest using rclone's actual mount-relative cache layout, without remounting the FUSE drive. Blue rotation arrows and **Downloading for offline availability** remain visible until hydration finishes. A green check and **Available offline** appear only after local verification. Reconnecting a drive checks local manifests without a remote read and never recreates missing cache content automatically. Test availability before disconnecting the network, especially for very large trees.

Choose **Free local space (make online-only)** to remove that rule and matching cached content. The most specific rule wins, so an individual child can be made online-only even when its parent folder remains offline; a later explicit child pin can override that exception. Choosing online-only on the streaming root clears every pin/exception and the job's streaming cache. The streaming-job button in the app offers the same whole-drive reset when Nautilus is unavailable. Unsynchronized local write-back content is never intentionally discarded; disconnect the drive cleanly and confirm uploads before freeing space.

The mount uses one stable retention policy because rclone's generic LRU quota cannot exclude pinned files. TuxInDrive therefore applies its own conservative quota, configured in **Settings** as maximum cache GiB and minimum free-space GiB. Cleanup considers only complete, inactive, unpinned objects; pin markers, write-back metadata, recent activity, symlinks, or invalid/uncertain state prevent eviction. Use the per-item online-only action or whole-drive reset when immediate space recovery is required.

For ordinary synchronized folders on Linux, local saves are detected through recursive inotify watches instead of repeated full-tree scans. New directories are watched dynamically. Kernel queue overflow, watch failure, rename ambiguity, suspend/reconnect inconsistency, or other uncertainty triggers a complete reconciliation before incremental synchronization continues. Remote checks normally begin at 30 seconds after activity and back off through 60, 120 and 300 seconds while idle; Proton uses a more conservative 60/120/300/600-second schedule, while direct peers can use 10/30/60/120 seconds. A failed scan retains pending local/remote changes and retries them rather than treating the failure as a clean baseline.

![Streaming and hybrid folder layout](assets/04-streaming.svg)

### Standalone streaming drive

Choose an empty mount folder such as:

```text
~/TuxInDriveStreaming/GoogleDrive
```

Select **Start streaming**. TuxInDrive reports connected only after Linux confirms the FUSE mount. **Open drive** opens the mounted tree; **Disconnect** unmounts it.

### Hybrid downloaded + streamed layout

A streaming folder may be an empty child of a normal synchronized tree:

```text
~/TuxInDrive/GoogleDrive/
├── Finance/       downloaded/two-way
├── Projects/      downloaded/two-way
└── Online/        streaming/files on demand
```

TuxInDrive automatically excludes `/Online` and `/Online/**` from the parent job's complete sync and incremental watcher. This prevents recursive transfer of mounted cloud files.

Safety rules:

- the streaming mount folder must be empty before connection;
- a streaming folder may be a **child** of a normal job;
- a streaming folder cannot be the **parent** of another sync job;
- two normal jobs and two streaming jobs cannot overlap.

If the mount exits unexpectedly, TuxInDrive updates the status and retries up to three times in five minutes.

## 8. Exceptions and blocked files

![Exceptions and interactive recovery](assets/05-exceptions-recovery.svg)

Exception rules use rclone filter syntax. Common examples:

| Rule | Result |
|---|---|
| `/Archive/private.zip` | Excludes one exact path. |
| `*.tmp` | Excludes temporary files at any level. |
| `/Cache/**` | Excludes a directory subtree. |
| `*.iso` | Excludes all ISO images. |

When Google blocks a file as suspected malware or spam, TuxInDrive shows an interactive decision:

- **Exclude file and retry** — recommended; adds an exact clickable exception rule.
- **Allow unsafe download and retry** — explicitly accepts the provider warning for that job.
- **Cancel** — leaves the job stopped for manual review.

To remove an exception, choose **Edit**, find **Synchronization exceptions**, and click the minus button beside the rule.

## 9. Recovery, protection, verification, and vaults

![Safety and encrypted vault controls](assets/07-safety-vault.svg)

### Local version history and recycle recovery

Each normal sync job enables **Local version history** by default. Before an incoming cloud/peer replacement or deletion changes an existing local file, TuxInDrive copies the current version into its private recovery area. Full bisync runs also direct replaced versions into dated backup directories on both sides. Set **Version retention (days)** in **Edit**; expired local entries are pruned after incoming changes.

Select **History** on a job to see the file, saved time, reason, and size. Select an entry and choose **Restore selected**. If a current file exists, it is archived before restoration, and TuxInDrive queues synchronization. Local recovery files live under `~/.local/share/tuxindrive/recovery`. The cloud-side hidden compatibility version area is application data and should not be selected as a second sync root.

### Ransomware and mass-change protection

For an initialized job, TuxInDrive performs a non-destructive dry run before a scheduled or manual full sync. Ordinary bulk edits pause only when both the unique changed-path count and changed percentage reach the configured thresholds (500 paths and 80 percent by default). A deletion burst above its ceiling or at least five known ransomware-like filename suffixes pauses independently. Real-time callback batches pass through the same gate.

When protection pauses a job, the enable switch is turned off and the preview log is retained. Review the activity and job log, disconnect a compromised computer if necessary, restore files from **History**, and run **Verify**. Re-enable the job only after the source of the changes is understood. Thresholds are safeguards, not malware detection; they do not replace endpoint security or independent backups.

### Integrity audit and repair

Select **Verify** to compare the local tree with its cloud or peer tree. The audit uses available hashes; encrypted vaults use downloaded content verification because ciphertext hashes cannot be compared directly. It reports content differences, local-only paths, remote-only paths, and verification errors without changing files.

Tick only reviewed findings, then choose **Use local versions** to upload local-only and changed files or **Use cloud/peer versions** to download cloud-only and changed files. One-sided files absent from the authoritative side are removed only after a recovery copy is retained where possible. TuxInDrive asks for confirmation and repairs only those paths. Run **Verify** again after repair; a completed transfer is not itself proof that every byte now matches.

### Conflict review center

Select **Conflicts** to show content mismatches requiring an authoritative side. Choose the reviewed items, then use the local or cloud/peer versions. Keep-both synchronization still creates dated `tuxindrive-conflict` copies when automatic resolution is disabled; inspect those alongside the center before removing either copy.

### Encrypted cloud vaults

Connect the underlying cloud account first. Select **Connect account → Create encrypted vault**, choose that account, and enter a new dedicated folder such as `TuxInDriveEncrypted`. Choose filename encryption, enter a strong password twice, and optionally add a filename salt. TuxInDrive creates a client-side crypt remote: file bodies, and by default file and directory names, are encrypted before upload. The new vault then works with the same visual folder selection, sync, streaming, history, and audit controls.

Never point a vault at a folder containing ordinary unencrypted files, never edit ciphertext through the underlying account, and do not configure both the vault and its backing folder as sync jobs. TuxInDrive cannot recover the vault password or salt. Store both in a password manager and test recovery with non-critical data before relying on the vault.

## 10. Tray and settings

![Tray controls, settings, and logs](assets/06-tray-logs.svg)

### Global bandwidth, network, battery and schedule policies

The environmental policy defaults to **Maximum usage**, so metered, battery,
and schedule gates do not defer work. Independently, the default global
bandwidth ceiling is `10M`. Set it empty for unlimited traffic, use one value
such as `5M` for both directions, or use `UPLOAD:DOWNLOAD` such as `2M:10M`.
The stricter global or per-folder value always wins.

Keep **Automatically reserve bandwidth for other applications** enabled unless
this device has a dedicated connection. The default reserves 20% of the ceiling
and divides the rest across enabled streaming drives plus sync and update lanes,
preventing separate rclone processes from multiplying the limit. Increase the
headroom for calls, gaming, or a router that becomes unresponsive under load.

The controller covers scheduled/manual/incremental synchronization, streaming,
metadata scans, verification and repair, update downloads, GitHub, Proton, and
Android. It also limits simultaneous native network work and jitters metadata
scans to avoid synchronized bursts. Select **Hide** on the network panel to stop
its periodic sampling and rendering, or use **Show network usage** in Settings
to restore it. This affects only device-wide current rates and daily totals; it
does not turn transfer limiting on or off or delete accumulated totals.

To add environmental constraints, select **Apply network, battery and schedule policies** and configure any combination of:

- disallowing NetworkManager connections marked metered;
- a battery percentage below which transfers pause while AC power is disconnected (`0` disables it);
- a daily `HH:MM` start/end window, including an overnight window such as `22:00`–`06:00`.

The gate runs before manual, callback and scheduled jobs. Deferred jobs show the policy reason and are reconsidered by the regular scheduler. Metadata already displayed by a mounted streaming filesystem can remain visible, but opening non-cached content still requires network access. See [Operations](OPERATIONS.md#network-policy) for congestion-safe settings.

The tray menu contains:

- **Open TuxInDrive**
- **Synchronize all now**
- **Pause all synchronization**
- **Open diagnostic logs**
- **Quit**

Settings control:

- automatic start after sign-in;
- desktop notifications;
- starting minimized;
- visual theme and language;
- shared upload/download limit, device traffic panel, and live-log rendering;
- streaming cache size, free-space reserve, and refresh mode;
- encrypted profile backup/restore and signed update checks.

### Optional TuxInDrive Server preview

The separate Linux server can keep selected synchronization jobs running
without the desktop, coordinate encrypted offline messages and collaboration
operations, publish short-lived device rendezvous envelopes, store encrypted
content-addressed objects, relay already encrypted peer traffic to explicitly
allowlisted destinations, and expose read-only health/audit tools. Existing
cloud and direct peer jobs do not begin using it automatically.

The integration is off by default. To connect, install and initialize the
server `.deb`. Open **TuxInDrive Server** from the Linux Applications menu to
configure its roles and limits, create tenant tokens, manage the background
service and inspect its logs without command-line work. The server window is
maximized and scrollable; closing it does not stop the service. Then open the
client **Settings**, select **Enable TuxInDrive server
integration (preview)**, and enter its origin and bootstrap token. The local
default is `http://127.0.0.1:9443`; every non-local address must use HTTPS. Use
**Test server connection** before saving. The token is saved in the operating
system credential store, never in `config.json`; an optional private CA file
can authenticate an internal HTTPS deployment. Clearing the checkbox stops the
client integration without changing server-side data or ordinary jobs.

Server installation, role configuration, API behavior and current preview
limits are described in the [server operator guide](SERVER.md).

Closing the main window hides it; synchronization continues in the tray. Use **Quit** to stop the application and unmount streaming drives.

## 11. Logs and diagnostics

| Location | Purpose |
|---|---|
| `~/.local/state/tuxindrive/startup.log` | Launcher and missing-runtime failures. |
| `~/.local/state/tuxindrive/tuxindrive.log` | Application lifecycle and job state. |
| `~/.local/state/tuxindrive/crash.log` | Uncaught Python/thread and native crash details. |
| `~/.cache/tuxindrive/logs/` | Individual synchronization and mount logs. |

Print diagnostic paths with:

```bash
tuxindrive --diagnostics
```

The expandable **Live activity log** shows recent application and transfer
messages directly in the UI. Its **Hide** button stops file-tail reading and
rendering; re-enable **Show and render the Live activity log** in Settings.
Desktop dialogs open at 92% of the active monitor's usable work area, leaving
room for window decorations and desktop panels without forced maximization.
Their controls use an automatically scrolling canvas, so a smaller display or
later resize never makes content unreachable. Android Settings is likewise
scrollable on small screens.

## 12. Troubleshooting

### Streaming folder is empty

1. Confirm the job button says **Open drive**, not **Start streaming**.
2. The mount folder must be empty before connection.
3. If nested, it must be a child—not the parent—of a normal sync job.
4. Open **View log** and look for FUSE, mount, authentication, or unsupported-flag errors.
5. Disconnect and select **Start streaming** again.

Version 0.10.1 writes a streaming preflight block containing the TuxInDrive version, remote, mount point, rclone path, `/dev/fuse` availability, and `fusermount3` location. It automatically detaches an orphaned FUSE mount left by a crash or unexpected rclone exit and waits up to 45 seconds for large cloud trees. The Nautilus extension uses lexical path matching, so it does not resolve or stat disconnected streaming endpoints. The app displays the most relevant mount failure directly while the full command activity remains in the job log.

### Proton Drive asks for a legacy username and password

The account still uses the retired rclone login. Open the account menu, choose **Reconnect / refresh credentials**, then select **Install CLI and connect** and finish browser authorization. TuxInDrive retains existing folder definitions, validates `/my-files`, and never asks for the Proton password or 2FA code.

### Job reports recovery sync required

TuxInDrive pauses automatic operation after a critical bisync abort to avoid repeated destructive resyncs. Review the log, resolve the cause, enable the job, and select **Sync now**.

### Google shows only part of the account

Edit/add the job and select the correct location: My Drive, Shared with me, or the intended Shared Drive. Then browse that location's tree.

### Google shared client warning

For continued organizational use, register a Google desktop OAuth client and reconnect the account with its client ID/secret. Do not commit credentials or OAuth tokens.

### Application does not start

Run:

```bash
tuxindrive --diagnostics
cat ~/.local/state/tuxindrive/startup.log
cat ~/.local/state/tuxindrive/crash.log
```

Reinstall the current package with `sudo apt install ./tuxindrive_0.26.22_all.deb`.

## 13. Data safety

- Back up important data before introducing any bidirectional synchronization tool.
- Review conflict and maximum-deletion settings before the first run.
- Keep unsafe Google flagged-file access disabled unless the content is trusted.
- Do not point multiple normal jobs at overlapping local folders.
- Removing a TuxInDrive job does not delete its local or cloud files.

### Security upgrade checklist for 0.26.22

1. Install `tuxindrive_0.26.22_all.deb`; the upgrade closes an older running TuxInDrive instance. Reopen TuxInDrive and restart Nautilus.
2. Confirm **Settings → Check for updates** reports 0.26.22 and no signature or expiry error.
3. Reconnect each provider once and verify that `~/.config/rclone/rclone.conf` is encrypted and mode `0600`; do not print or upload it.
4. Confirm the `TuxInDrive rclone configuration` entry exists in GNOME Passwords and Keys/Secret Service. Do not delete it without an export/recovery plan.
5. Review peer invitations, revoke unused device and Onion credentials, and exchange replacements through an authenticated channel when compromise is suspected.
6. Run **Verify** on important jobs, inspect the health dashboard, and test recovery using a non-critical file.
7. Keep an independent backup. Update signing protects installer authenticity; it does not protect data from a compromised desktop account.
8. Review the global directional bandwidth ceiling and keep it below the reliably available link capacity; confirm incremental, scan, verification, update, GitHub, Proton, and Android activity shares the expected controller.
