# TuxInDrive configuration reference

This reference describes the persisted desktop configuration in TuxInDrive
0.26.22. Normal changes should be made in **Settings**, **Connect account**, or
**Add/Edit folder**. Stop TuxInDrive and make a backup before manually editing
JSON; a syntactically valid but inconsistent mapping can still synchronize the
wrong location.

## State locations

TuxInDrive uses platform-native roots and a `tuxindrive` subdirectory. An
existing `tuxdrive` directory is deliberately reused after an upgrade so that
credentials, peer identities, history, and cached files are not lost.

| State | Linux | Windows | macOS |
|---|---|---|---|
| Configuration | `$XDG_CONFIG_HOME/tuxindrive/config.json` or `~/.config/tuxindrive/config.json` | `%APPDATA%\tuxindrive\config.json` | `~/Library/Application Support/tuxindrive/config.json` |
| Application data | `$XDG_DATA_HOME/tuxindrive` or `~/.local/share/tuxindrive` | `%LOCALAPPDATA%\tuxindrive` | `~/Library/Application Support/tuxindrive` |
| Cache | `$XDG_CACHE_HOME/tuxindrive` or `~/.cache/tuxindrive` | `%LOCALAPPDATA%\Cache\tuxindrive` | `~/Library/Caches/tuxindrive` |
| Logs | `$XDG_STATE_HOME/tuxindrive` or `~/.local/state/tuxindrive` | `%LOCALAPPDATA%\Logs\tuxindrive` | `~/Library/Logs/tuxindrive` |

The configuration directory is mode `0700` and `config.json` is mode `0600`
on systems that support POSIX permissions. Saves use a private temporary file,
flush it to disk, and atomically replace the previous file. Identical state is
not rewritten. Invalid JSON is moved to `config.json.invalid` and startup
reports the error rather than silently replacing user state.

Provider credentials are not stored in `config.json`. Rclone secrets are in
its encrypted private configuration and the encryption password is in Secret
Service, Credential Manager, or Keychain. GitHub credentials remain in the Git
credential helper/SSH agent; Proton sessions remain in Secret Service.

## Top-level document

```json
{
  "accounts": [],
  "jobs": [],
  "folder_groups": [],
  "peer_shares": [],
  "settings": {}
}
```

Unknown fields are ignored when loading. Missing fields receive the defaults
defined by the current model, which provides forward-compatible upgrades.
Enumerated values are strict; malformed configuration is rejected. Runtime
job state (`initialized`, last run/status/error) is persisted with the job.

## Application settings

| Field | Default | Meaning |
|---|---:|---|
| `launch_at_login` | `true` | Start through the platform login integration. |
| `notifications` | `true` | Show completion, warning, and error notifications. |
| `start_minimized` | `false` | Open in background/status area when possible. |
| `rclone_path` | `rclone` | Selected rclone executable or command name. |
| `proton_drive_path` | `proton-drive` | Official Proton Drive CLI executable. |
| `nautilus_integration` | `true` | Enable supported Linux file-manager actions. |
| `language` | `en` | Interface language code. |
| `visual_theme` | `nordic_glass` | Validated visual theme identifier. |
| `network_policy` | `maximum` | Transfer policy selected in Settings. |
| `global_bandwidth_limit` | `10M` | Shared upload/download ceiling; empty means unlimited. |
| `automatic_bandwidth_control` | `true` | Reserve headroom and divide the ceiling across simultaneous process-local consumers. |
| `bandwidth_headroom_percent` | `20` | Portion retained for other applications/devices; clamped to 0–80%. |
| `allow_metered_networks` | `true` | Permit scheduled work on metered connections. |
| `pause_below_battery_percent` | `0` | Pause threshold; zero disables battery pausing. |
| `schedule_start`, `schedule_end` | empty | Optional daily transfer window. |
| `profile_remote` | empty | Account chosen for encrypted profile backups. |
| `profile_last_backup` | empty | Timestamp of the last successful profile backup. |
| `streaming_cache_max_gib` | `20` | Maximum streaming cache target, clamped to 1–1024 GiB. |
| `streaming_cache_min_free_gib` | `5` | Free-space reserve, clamped to 1–1024 GiB. |
| `streaming_refresh_mode` | `realtime` | `realtime`, `balanced`, or `low_traffic`. |
| `show_network_usage` | `true` | Feature flag for the current/daily traffic panel. |
| `show_live_activity_log` | `true` | Feature flag for live-log rendering and visibility. |
| `server_integration_enabled` | `false` | Preview feature flag. False means no server client is created and no request is made. |
| `server_url` | `http://127.0.0.1:9443` | Server origin only; remote plain HTTP, embedded credentials, paths, queries and fragments are rejected. Loopback HTTP matches the local server default; remote servers require HTTPS. |
| `server_ca_file` | empty | Optional PEM CA for a privately issued server certificate. |
| `config_version` | `1` | Persisted schema generation. |

### Bandwidth syntax and scope

Rates use rclone-style suffixes such as `512K`, `10M`, or `1G`. One value
limits both directions. `UPLOAD:DOWNLOAD`, for example `2M:10M`, sets separate
ceilings. A job-specific `bandwidth_limit` can only make the effective limit
stricter. The global controller covers synchronization, streaming mounts,
metadata scans, verification/repair, updates, native GitHub operations, Proton
operations, and Android network work. Native operations without a byte-rate
option are serialized while the global limit is active.

Automatic bandwidth protection is enabled by default because rclone limits are
process-local. It first keeps the configured headroom free, then divides the
remaining rate by one ordinary transfer, one responsive update, and every
enabled streaming drive. For example, `10M` with 20% headroom and two streaming
drives gives each possible consumer 2 MiB/s, keeping their worst-case aggregate
at 8 MiB/s. Disabling the option restores the literal legacy per-process limit and
can therefore multiply total traffic when several streaming drives are active.

The network usage panel is a device-interface meter, not per-job accounting.
Its current rates and local-day totals can include traffic from other
applications. Its Hide button and Settings switch both stop periodic meter
sampling and rendering without deleting accumulated totals; neither disables
the bandwidth controller. Hiding the Live activity log similarly stops reading
and rendering log tails until the display is re-enabled in Settings.

The server bearer token is intentionally absent from this configuration. It is
stored under a URL-derived entry in Secret Service, Credential Manager, or
Keychain. Changing the URL selects another credential entry. The server's own
schema, role, quota, retention and TLS fields are documented in
[Server preview](SERVER.md#configuration).

## Accounts

Every account has `remote`, `provider`, `display_name`, `created_at`, and
`backend`. Provider values are `google_drive`, `onedrive`, `dropbox`, `box`,
`pcloud`, `mega`, `proton_drive`, `nextcloud`, `github`, `peer`, and `vault`.

Specialized fields are used only by their backend:

| Backend | Fields |
|---|---|
| Peer | `peer_host`, `peer_port`, pinned `peer_host_key` |
| Vault | `vault_base_remote`, `vault_base_path` |
| GitHub | `repository_url`, `repository_branch`, `git_author_name`, `git_author_email` |
| Proton | `backend` is `proton_cli`; unsupported combinations normalize to `rclone` |

Account names are internal identifiers referenced by jobs. Do not rename them
directly without updating every `account_remote` reference.

## Synchronization jobs

| Group | Fields and behavior |
|---|---|
| Identity | `id`, `name`, `account_remote`, `enabled`, optional `group_id` |
| Mapping | `local_path`, `remote_path`, `remote_scope`, `cloud_location_name` |
| Mode | `two_way`, `download_only`, `upload_only`, or `virtual_drive` |
| Scheduling | `interval_minutes`, `realtime_sync` |
| Selection | `exclude_patterns`, `offline_paths`, `online_only_paths` |
| Conflicts | `keep_both`, `newer_wins`, `local_wins`, or `cloud_wins` |
| Transfer | `bandwidth_limit`, `block_delta_transfer`, `peer_delta` |
| Deletion safety | `max_delete`, `ransomware_protection`, `mass_change_limit`, `mass_change_percent` |
| Recovery | `version_history`, `version_retention_days` |
| Provider consent | `acknowledge_google_abuse` |
| Peer policy | `peer_leases`, `peer_lease_minutes`, `peer_role`, `one_time_drop_id` |
| GitHub | `repository_url`, `repository_branch`, `git_author_name`, `git_author_email` |
| Runtime | `initialized`, `last_run`, `last_status`, `last_error` |

Defaults are a five-minute, real-time, two-way job; conflict copies; version
history retained 30 days; a 100-delete cap; and ordinary bulk-change thresholds
of 500 changed paths and 80 percent. Both bulk thresholds must be reached;
deletion ceilings and ransomware-shaped filename suffixes remain independent
hard stops. Default excludes are `.Trash-*/**`, `*.part`, and
temporary Office lock files (`~$*`).

`remote_scope` is a provider-selected root (for example a Shared Drive), while
`remote_path` is relative to it. The engine will not run overlapping local
roots except for the explicitly safe layout of a synchronized folder above a
separate streaming mount. Initial two-way synchronization establishes a
baseline; clearing `initialized` is a recovery action and can require a merge.

## Folder groups

`FolderGroup` contains `id`, `name`, `created_at`, and `collapsed`. Groups only
organize the interface; they do not alter scheduling, paths, or security.

## Peer shares

A peer share stores its `id`, `name`, confined `local_path`, advertised host,
listener `port`, enable/status state, discovery and transport preferences.
Authorization is an array of named public keys with an enabled flag and role
(`read_write`, `read_only`, `send_only`, or `receive_only`). One-time drops add
an inbox, public key, expiry, consumed flag, and isolated server port.

Connectivity fields cover LAN discovery, optional NAT traversal, SSH relay
host/user/ports, and direct/Tor/automatic policy. Privacy controls can disable
relays and public-IP discovery, require no provider cloud, enable a persistent
onion service and client authorization, and store bridge/transport lines.
Private keys are separate private files, never fields in this document.

## Encrypted profile backup

The current searchable cloud object is
`TuxInDrive/TuxInDrive-Profile.tdx`; the old hidden location
`.tuxdrive-profile/tuxdrive-profile.tdx` is still detected and migrated.
Profiles use AES-GCM with a scrypt-derived key, a minimum 14-character
passphrase, authenticated metadata, and a 128 MiB input limit. Credentials are
optional. Restore first preserves `config.json.before-migration`.

Android imports the same `.tdx` file through the system file picker. For a
phone transfer, create it with credentials included, then download the visible
object or choose it from a Drive provider exposed by Android's picker; do not
rename it to `.json`. Android rejects a configuration-only profile because it
does not contain the encrypted rclone configuration required to connect. New
credential-enabled profiles also carry rclone's independent random
configuration unlock key inside the authenticated AES-GCM envelope. Android
validates that the imported configuration can be unlocked and contains at
least one remote before replacing the previous file, then protects the unlock
key with Android Keystore for subsequent launches.

**Show mobile transfer QR** creates a compact credential-enabled profile in
memory, compresses the still-encrypted `.tdx` bytes, and divides them into at
most 256 QR frames. Each frame binds one transfer ID, sequence position, total,
and SHA-256 digest. Android accepts frames in any order, rejects mixed,
oversized, malformed, incomplete, or modified sets, and decrypts only after all
frames pass integrity verification. Peer private files are omitted from QR
transfers. Profiles larger than the 2 MiB QR safety limit must use the `.tdx`
file path.

## Environment and command-line integration

Linux honors `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, and
`XDG_STATE_HOME`. The desktop also reads normal platform variables for display,
session, notification, credential-store, and desktop integration behavior.
Build-time secrets and signing keys are intentionally not application
configuration; see [Release process](RELEASES.md).

For operational changes, backup and recovery, see [Operations](OPERATIONS.md).
