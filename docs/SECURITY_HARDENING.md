# TuxInDrive 0.26.25 security hardening and secure operation

This document explains the controls retained through TuxInDrive 0.26.25, including critical/high remediation, approval-based peer sharing, explicit online-only/offline retention, GitHub and Proton boundaries, global traffic control, signed platform updates, encrypted desktop-to-mobile migration, what changed for existing users, which data remain sensitive, what the controls do not guarantee, and how maintainers verify a release. It complements the concise vulnerability-reporting policy in [`SECURITY.md`](../SECURITY.md), implementation [architecture](ARCHITECTURE.md), and operational [runbook](OPERATIONS.md).

> **Audit status (2026-08-22):** version 0.26.20 closed the audited server
> configuration-boundary, bounded-network, Android updater and sensitive-path
> findings with regression coverage. It also pins Python release tooling,
> suppresses package-manager auto-updates, publishes a dependency SBOM and uses
> a release environment. Fully immutable Windows/macOS package inputs,
> Authenticode, Developer ID signing/notarization and signed provenance remain
> tracked release-infrastructure work. See the
> [full audit and remediation status](SECURITY_AUDIT_2026-08-22.md).

## Supported baseline and immediate action

Version 0.25.0 changes product identifiers without changing cryptographic trust roots or silently relocating sensitive state. Fresh installations use TuxInDrive directories; upgrades use an existing legacy directory when no new directory exists. The credential helper checks the TuxInDrive Secret Service entry first and the pre-rebrand entry second. Existing encrypted profile formats, peer invitations and hidden remote metadata remain readable. The signed update bridge retains the old repository/package alias required by 0.24.x, while accepting only the two exact official GitHub raw prefixes and a filename matching the signed version.

Version **0.26.25** is the supported baseline. It retains root-side update re-verification, per-key peer endpoints, isolated send/drop roots, bounded ODF/CRDT parsing, verified GitHub rename migration, durable bisync baselines, guarded reinitialization, exact offline rules, stable VFS policy, bounded FUSE reads, URI-safe Nautilus integration, signed platform channels, encrypted QR/file profile migration, and the global bandwidth/admission controller. Its default-on aggregate protection reserves configurable headroom and divides process-local rclone limits across every possible concurrent consumer, preventing several mounts and a synchronization from each receiving the complete ceiling. Local peer shares may be advertised before a collaborator is known, but no file endpoint starts until the owner approves a displayed device fingerprint; approved advertisements are recipient-scoped and the listener still enforces the complete SSH key. Pending requests expire, deduplicate, are capped globally, and are rate limited per source. Router mapping is opt-in. Python/PyPI installations require `cryptography>=50.0.0,<51`; Debian installations use the distribution-maintained `python3-cryptography` package so vendor backports remain valid.

Version 0.23.0 preserves those controls while adding event-driven monitoring and cache limits. Inotify queue overflow triggers full reconciliation; executable-validation caches are invalidated by binary identity changes; atomic writes remain mandatory for changed configuration; and cache cleanup refuses to evict pinned, dirty, active, symlinked or ambiguously described objects. Invalid pin metadata disables eviction for that job rather than guessing.

Upgrade, restart TuxInDrive and Nautilus, verify cloud access, inspect peer authorization, run an integrity check on important jobs, and retain an independent backup. Do not continue using a package whose signed update manifest has expired or failed verification.

The 0.19.1 release completes a trust-root rotation without disabling verification. The legacy `latest.json` manifest is signed by the original offline key embedded in 0.18.1 and is restricted to the 0.19.1 bridge package. Version 0.19.1 reads `latest-v2.json`, signed by the rotated offline key, for all later updates. Both private keys remain outside the repository with mode `0600`; the original key should be retired after the documented legacy-support window.

## Security control inventory

| Area | 0.26.25 behavior | Security purpose |
|---|---|---|
| Updates | Desktop verification plus independent privileged manifest retrieval, signature/expiry validation, no-follow copy to root-only staging, SHA-256 and Debian identity verification before APT; Android automatic checks retain the same signed manifest/digest boundary and require system installer approval | Prevent unsigned, replayed, substituted, oversized, wrong-package and verification-to-install race attacks without creating a silent mobile install path |
| Cloud credentials | rclone authenticated encrypted configuration; random config key in GNOME Secret Service; password-command retrieval; private permissions; sensitive child processes disable same-user dumpability | Keep tokens/passwords out of TuxInDrive JSON, ordinary arguments, and world-readable files |
| Proton Drive authorization | Official `proton-drive auth login` browser flow; forced `keychain` credential store; session owned by Proton CLI under `ch.proton.drive/drive-sdk-cli`; `/my-files` validation; one native account | TuxInDrive never receives, exports, logs, or passes the Proton password, 2FA code, or session |
| Filesystem writes | Relative-path validation plus descriptor-based no-follow traversal and atomic replacement for incremental downloads, deltas, recovery, hydration, and repair | Resist traversal and symlink-swap writes outside the configured root |
| Peer deltas | Canonical signed instructions, authorized Ed25519 signer, bounded block count/size, BLAKE2 block checks, final SHA-256, atomic install, full-file fallback | Reject unauthenticated, tampered, or resource-abusive delta transactions |
| Tor transport | Tor-only/no-public-IP services bind loopback; explicit invitation transport allowlists; randomized per-remote SOCKS listeners; readiness checks; no silent clearnet fallback | Enforce workspace transport policy and reduce accidental address exposure |
| Bridges and relays | Packaged pluggable-transport executable allowlist; bridge material excluded from invitations, arguments, logs, and ordinary profile backup; strict SSH host verification and batch mode | Reduce credential leakage and command/path injection opportunities |
| Peer roles | One listener and authorization file per key; server read-only for read/receive roles; private inbox root for send-only | Prevent hostile generic clients from bypassing a role label |
| One-time drops | Dedicated key/port/inbox root, consumption marker, authorization rebuild, endpoint restart and expiry validation | Prevent parent-workspace browsing and retire a temporary grant promptly after use |
| Collaborative inputs | Defused XML, ZIP count/size/ratio/path limits, bounded operation JSON/schema/count and iterative CRDT traversal | Prevent archive/XML/operation resource-exhaustion attacks arriving through sync or peers |
| Configuration backup | Version-2 AES-256-GCM, scrypt `N=131072`, unique minimum 14-character password, 128 MiB bundle limit; credential profiles bind rclone data to its separate unlock key; Linux reads/writes that key through packaged Secret Service with stdin-only storage; QR frames retain encryption plus sequence/digest and 2 MiB/256-frame limits; Android Keystore protects the imported key | Increase offline-guessing cost, prevent incomplete/mixed mobile migration and bound memory/storage abuse while preserving desktop read compatibility |
| Runtime | Isolated Python launcher, cleared Python environment, mode-0600 logs/config, mode-0700 state directories, systemd `UMask=0077`, `PrivateTmp`, and `LockPersonality` | Reduce environment injection and accidental local disclosure |
| Transfer engine | rclone 1.75.0+ plus required safety capabilities; bounded verified bootstrap archive with unique safe member extraction | Reject unsupported or unsafe engines and malicious archives |
| GitHub repositories | Credential-free GitHub-only URLs, validated branches/origins, noninteractive system Git credentials, fast-forward/rebase guards, conflict abort | Avoid token leakage, command injection and silent Git history overwrite |
| Offline hydration | Root/child confinement, symlink rejection, progress-based inactivity timeout with one isolated retry, failed-pin rollback, exact file rules, stable no-remount retention, explicit nested online-only exceptions, and confined local pin manifests checked without remote reads | Avoid indefinitely blocked helpers, stale pending badges, sibling downloads, detached Nautilus views, silent reconnect downloads, false offline claims, generic-cache eviction of pinned content, and path escape |
| CI/release | Commit-pinned GitHub Actions, tests, compile checks, high-severity Bandit, `pip-audit`, Debian installation matrices, CycloneDX SBOM, and signed-manifest verification; platform package-manager and PyInstaller inputs are not yet fully immutable | Detect regressions while TID-2026-03 tracks remaining supply-chain and native-signing work |
| Optional server | Default-off client flag; loopback default; TLS required off-loopback; token digests; root-owned read-only configuration; randomized descriptor-relative atomic saves; role controls; opaque payloads; sizes/TTLs/quotas/rate limits; bounded request/relay concurrency and deadlines; tenant-isolated SQLite; bandwidth-controlled allowlisted relay; read-only MCP; systemd task/descriptor/memory ceilings | Preserve the privileged boundary and prevent one authenticated tenant/source from consuming unbounded server resources; still a preview, not an internet-scale public service |

## Dependency advisory response

The 0.15.1 workflow installed `cryptography` 46.0.7 and `pip-audit` reported PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf. The highest required fixed version was 50.0.0, so 0.16.0 raises the upstream floor to 50.0.0 rather than ignoring the audit.

There are two installation trust paths:

- Python/PyPI builds resolve the explicit `>=50.0.0,<51` requirement and are checked by `pip-audit`.
- The Ubuntu `.deb` depends on Ubuntu's `python3-cryptography`. Distribution security teams may backport fixes without changing the apparent upstream major version, so administrators must follow Ubuntu Security Notices and installed package changelogs. An upstream-version-only Debian constraint could incorrectly reject a patched Ubuntu package.

Never interpret a green dependency audit as proof that application logic is safe. Conversely, do not replace a distribution security assessment with an upstream version comparison alone.

## Credential and key locations

| Data | Normal location | Protection and backup advice |
|---|---|---|
| TuxInDrive settings | `~/.config/tuxindrive/config.json` | Mode `0600`; contains job/account metadata, paths, peer public material, and policy—not the managed rclone config password |
| rclone configuration | `~/.config/rclone/rclone.conf` | Authenticated encrypted form; treat as sensitive even when encrypted |
| rclone config password | GNOME Secret Service entry `TuxInDrive rclone configuration` | Do not delete or copy into scripts; include in a tested device-migration plan |
| Peer private identity | TuxInDrive private data directory | Mode `0600`; never send it—exchange only public keys and verified fingerprints |
| Tor service/client authorization | Private TuxInDrive Tor state | Treat client invitations/QR as passwords; revoke unused devices and account for Tor reload timing |
| Update signing private key | Offline release environment only | Never commit, ship, log, or store beside public artifacts |
| Recovery/version data | `~/.local/share/tuxindrive/recovery` and remote hidden compatibility version metadata | Sensitive filenames/content may be retained; include it in retention and secure-erasure policy |
| Logs and audit | `~/.local/state/tuxindrive`, `~/.cache/tuxindrive/logs`, `~/.local/share/tuxindrive/audit.jsonl` | Private permissions; may reveal paths, peer names, timing, errors, and operational metadata |

## Upgrade and migration behavior

On first secure rclone use, TuxInDrive detects an unencrypted managed configuration, generates a random password, stores it in GNOME Secret Service, asks rclone to encrypt the configuration, and records a private managed marker. An already encrypted advanced-user setup is preserved. If Secret Service is unavailable, configuration migration must fail visibly rather than writing a password into TuxInDrive JSON.

Existing jobs, provider remotes, peer public metadata, recovery data, and version-1 encrypted profile backups remain usable. Create new profile backups after upgrading so they receive the stronger version-2 scrypt parameters. Test restore on non-critical data before deleting an older backup.

### Official Proton Drive boundary

Version 0.24.1 replaces new and reconnected Proton/rclone credential login with Proton's official CLI and repairs clean-machine bootstrap. TuxInDrive accepts the release manifest only from Proton's exact HTTPS endpoint, selects only the supported amd64/arm64 Linux path, bounds both manifest and binary size, and installs the executable only after constant-time comparison with Proton's published SHA-512 checksum. Partial or mismatched downloads are discarded, replacement is atomic, and the managed tool directory/executable use private permissions. TuxInDrive removes `PROTON_DRIVE_CACHE_DIR` from the child environment and forces `PROTON_DRIVE_CREDENTIALS_STORE=keychain`, preventing inherited `unsafe_file` test configuration from writing a plaintext session. Installation and browser authorization are cancellable; validation and every file operation use bounded subprocess timeouts. Diagnostic reflection removes authorization URLs and token/session/cookie assignments.

All remote paths are confined to `/my-files`; unsafe path components and control characters are rejected. Remote entry names cannot contain separators or traversal components. Local synchronization refuses symlink roots or descendants before the official CLI writes, honors nested/transient exclusions, checks persisted local/remote snapshots for mass changes before transfer, and stores those snapshots atomically with mode `0600`. Proton jobs never enter rclone callback or mount paths. Because Proton's official CLI has no mount or atomic sync API, files-on-demand and real-time callbacks are disabled. One-sided deletions are restored instead of propagated, prioritizing recoverability; live-provider tests remain required before relying on the backend for unique data.

## Trust boundaries and residual risk

The synchronized-folder search index stores metadata only in the private cache
root. Refreshes do not open file bodies, do not follow symbolic links, honor
job exclusions, and do not enumerate files-on-demand mounts. Search terms stay
inside the local SQLite query path and are not sent to a provider, server, or
telemetry endpoint. Before a result is opened, the live path is resolved again
and must remain inside its configured root. Filenames and local paths are still
sensitive metadata, so the index directory/file use `0700`/`0600` modes where
POSIX permissions exist and should not be copied into diagnostics casually.

The 0.26.25 search preview path does not change that indexing guarantee.
It is default-off, is activated only inside one search window, and reads only
the selected local result after repeating the root-confinement and no-symlink
checks. Reads, output, archive expansion, compression ratio, PDF pages and PDF
runtime are bounded; XML uses `defusedxml`, and the external PDF utility gets
a private copy through a fixed argument list without a shell. Preview still
increases attack surface in local image/document decoders, so it remains an
explicit user action and should not be used on an untrusted file when a visual
preview is unnecessary.

- TuxInDrive cannot protect files after malware or another process compromises the desktop user account.
- Provider OAuth and rclone still grant the configured cloud permissions. A malicious provider, revoked token, policy change, or provider-side corruption remains outside TuxInDrive's control.
- Tor hides direct routing in Tor-only mode but does not guarantee anonymity against endpoint compromise, traffic correlation, invitation leakage, or a global observer.
- Relays see addresses, timing, connection duration, and byte volume even when they cannot decrypt nested SFTP content.
- Local recovery, cache, names, logs, and audit records expose operational metadata unless the endpoint/storage is separately protected.
- The stable streaming cache does not use rclone's generic LRU quota because it cannot distinguish pinned from ordinary files. Opened content can therefore consume local disk until the user applies **Free local space** to an item or resets the streaming drive to online-only.
- Synchronization deliberately propagates valid changes and deletions. Mass-change limits, history, and verification reduce impact but do not replace immutable or offline backup.
- The preview server sees client IP, tenant and opaque routing identifiers,
  timing, payload sizes, configured relay targets and encrypted retention. It
  does not become zero-knowledge merely because payload columns are opaque:
  clients must encrypt and sign before upload. A stolen bearer token authorizes
  its tenant until rotated. Internet-scale deployment and federation require
  external review before production claims.

### Intentionally retained peer-server limitation

Peer sharing and one-time drops remain enabled with per-key isolation. Read/write peers retain the selected workspace, read/receive peers receive a server read-only view, and send-only/drop peers receive private inbox roots. Collaborators remain trusted for content they are legitimately allowed to read or modify. Per-endpoint quotas, operation telemetry and immediate upload-session termination remain scheduled in the roadmap.

## Operator verification checklist

1. Install only the repository package whose SHA-256 matches the signed manifest.
2. Confirm the running version is 0.26.25 and the platform update check reports a valid signature, origin, filename, digest, size, architecture and expiry.
3. Verify configuration/state directories are owned by the user and not group/world accessible.
4. Confirm the rclone config is encrypted and the Secret Service entry is recoverable through an approved migration procedure.
5. Review enabled cloud accounts, jobs, exception rules, peer keys, roles, Tor client credentials, relay settings, and public/NAT exposure.
6. Exercise restore, conflict review, integrity verification, and ransomware/mass-change pause with test files.
7. Inspect logs for repeated authentication failures, policy blocks, unexpected fallback attempts, delta signature failures, and update verification errors.
8. Maintain an offline or immutable backup and document recovery objectives separately from TuxInDrive's convenience history.
9. Configure the global upload/download ceiling below reliable link capacity and confirm scans, verification, updates, GitHub, Proton and Android share the controller; never treat traffic shaping as an integrity or access-control boundary.

## Maintainer release verification

Run the unit suite, compilation, shell syntax, `git diff --check`, Bandit, `pip-audit`, package build/inspection, SBOM generation, signed-manifest parsing, package digest comparison, and a clean-machine install/upgrade test. Real provider, FUSE, Nautilus, LAN, NAT, relay, Onion, 2FA, suspend/resume, and large-tree tests remain mandatory manual gates because mocks cannot validate those operating-system and provider boundaries.

Any new credential field must be available to every relevant user/account flow, stored only in the established encrypted/Secret-Service path, redacted from UI errors, logs, and diagnostics, included in explicit sensitive migration only, and covered by round-trip, wrong-secret, permission, and upgrade tests.
