# TuxInDrive testing and release verification

TuxInDrive treats synchronization, deletion propagation, authentication, mounting, and software updates as safety-sensitive behavior. Every change affecting these areas should add or update an automated test and describe any remaining manual verification.

## Run the automated suite

From the repository root:

```bash
python3 -m pip install .
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
cd android
gradle :app:testSideloadDebugUnitTest
```

The dependency-install step is required when using an isolated Python environment such as GitHub Actions. Python-package builds require `cryptography>=50.0.0,<51`; Ubuntu `.deb` installations use the distribution-maintained `python3-cryptography` package so official Ubuntu backported security fixes are recognized by APT rather than compared only by the upstream version string.

CI pins third-party actions by immutable commit, runs high-severity Bandit checks and `pip-audit`, and publishes a CycloneDX dependency SBOM with the package.

The TuxInDrive development suite contains **411 automated tests: 399 Python tests and 12 Android JVM tests**. Tests use temporary directories and mocked cloud/Git/Tor processes where possible, so they do not require or expose real credentials or personal files. Server coverage adds private initialization, launcher argument forwarding and private package-library isolation, schema/TLS/token validation, tenant-isolated opaque storage, expiry/quota bounds, bounded authenticated requests and relays, authenticated loopback HTTP, default-off client integration, shared agent/relay bandwidth control, relay rejection, read-only MCP, graphical package integration and its fixed no-shell privilege boundary. Desktop layout coverage verifies monitor-safe maximum dialog sizing, resizable client/server windows, scroll canvases without false window-sized minimums, and isolated scrolling for wide synchronized-folder actions. The server API integration tests use only a temporary loopback listener and random ciphertext-like bytes.

## Test groups

| Test module | Tests | What it verifies |
|---|---:|---|
| `test_audit.py` | 2 | Private audit persistence, filtering and malformed historical-line handling. |
| `test_bandwidth.py` | 13 | Directional syntax and invalid values, stricter global/job limits, automatic headroom/fair division, independent upload/download clocks, network-slot admission and release, update byte clock and bounded scan jitter. |
| `test_bootstrap.py` | 7 | Linux/macOS transfer-engine selection, rejection and identity-cached revalidation of incompatible/replaced rclone versions, supported CPU architectures, and pinned release checksums. |
| `test_capabilities.py` | 3 | Complete provider records and conservative adaptive-mode restrictions. |
| `test_config.py` | 12 | Round-trip persistence, bandwidth/theme/cache/visibility validation, legacy path compatibility, unchanged-write suppression, private permissions, and invalid configuration quarantine. |
| `test_delta.py` | 1 | Rolling BLAKE2 block signatures identify only modified ranges and calculate transferred bytes. |
| `test_diagnostics.py` | 1 | Startup failures are written before GTK imports, allowing diagnosis when the graphical runtime cannot start. |
| `test_platform_support.py` | 5 | Safe distribution parsing, Linux/macOS/Windows machine-readable capabilities and unsupported-architecture blocking. |
| `test_engine.py` | 53 | Full and incremental modes, atomic reservation, aggregate streaming budgets, global rates/admission, jitter/backoff, deletion/conflict safety, streaming/mount recovery, offline hydration, marker confinement, symlink rejection and engine replacement. |
| `test_file_preview.py` | 13 | Default-local bounded text/image/document previews, no-follow reads, folder non-enumeration, UTF handling, archive traversal/ZIP-bomb rejection, and shell-free page/time-limited PDF extraction. |
| `test_github_sync.py` | 6 | Credential-free GitHub URL/branch/item safety, redirect migration, global admission and guarded commit/fetch/rebase/push orchestration. |
| `test_folder_layout.py` | 11 | Persistent selection during asynchronous cloud-tree loading, safe account-switch defaults, before/after drag ordering, cross-group moves, group-header append, Ungrouped fallback, self-drop handling, endpoint-path preservation, GTK text-payload round-trip and malformed-payload rejection. |
| `test_i18n_help.py` | 3 | Six-language UI fallback, Arabic/Hebrew RTL detection, complete localized in-app help topics and localized drag/collapse guidance. |
| `test_migration.py` | 9 | AES-GCM profile round trips, wrong-password/tamper rejection, visible and legacy cloud discovery/migration, complete unlock-key handoff, compact mobile export, secret opt-in, private permissions and validation. |
| `test_offline_action.py` | 9 | Mounted-drive fast dispatch, cold-start queuing, both supported command-line availability option forms, lexical file routing without FUSE resolution, sibling-prefix rejection, exact file-rule isolation, nested offline/online-only precedence, and green-state publication only for locally verified rules. |
| `test_nautilus_extension.py` | 12 | Exact path/menu isolation, cached/coalesced badge refresh, URI lifecycle, Nautilus 4.1 construction, sensitivity and verified offline transitions. |
| `test_network_usage.py` | 10 | Linux/macOS/Windows counter parsing and failure handling, platform dispatch, current rates, daily reset, counter rollover and private persistent totals. |
| `test_packaging.py` | 17 | Debian/Windows/macOS/Android packaging, release-channel layout, native assets, automatic missing-version publication, upgrade process, Nautilus routing and emblem metadata. |
| `test_password_helper.py` | 8 | Private credential-helper input/output, packaged Secret Service fallback, migration-key storage and rejection behavior. |
| `test_profile_qr.py` | 3 | Stable desktop/Android QR protocol, multi-frame ordering/deduplication, bounds and incomplete/mixed/tampered transfer rejection. |
| `test_performance.py` | 12 | Inotify delivery/startup race, remote retry, overflow reconciliation, monitor safety, cache protection, fail-closed markers and performance hooks. |
| `test_process_control.py` | 4 | Portable process creation, cancellation, process-group cleanup and timeout behavior. |
| `test_proton.py` | 30 | Official CLI install/login/session, Secret Service, redaction/confinement, backend migration, safety previews, global admission and fail-closed routing. |
| `test_collaboration.py` | 11 | Offline CRDT convergence, iterative deep-chain handling, immutable/bounded operation state, checkpoints, review/presence, deterministic ODT/ODS round trips, ZIP-bomb rejection, unsafe XML rejection and binary fallback. |
| `test_peer.py` | 27 | Invitation compatibility, approval-based LAN requests/advertisements, roles/drops/transports, signed atomic deltas, isolated device roots, authorization/revocation, host-key pinning, leases and private identities. |
| `test_policies.py` | 7 | Maximum-usage defaults plus controlled battery, metered-network and normal/overnight schedule decisions, including fail-open probe handling. |
| `test_recovery.py` | 13 | Local archive/restore behavior, disabled retention, malformed/foreign record rejection, expiry pruning, mass-change and ransomware-suffix blocking, integrity-audit parsing and directional repairs. |
| `test_responsive_windows.py` | 5 | Monitor-safe, freely resizable client/server windows, local scrolling, wide-control isolation and search preview feature gating. |
| `test_search_index.py` | 11 | Private content-free metadata indexing, Unicode/token lookup, literal wildcard handling, stale pruning, exclusions, symlink rejection, paused roots, streaming avoidance and safety-limit retention. |
| `test_security.py` | 8 | Empty/absolute/parent path rejection, symlink refusal, confined atomic installation, Ed25519-only keys and signed transaction tamper detection. |
| `test_server.py` | 25 | Private initialization, race-resistant root configuration writes, shared agent/relay bandwidth control, package-launcher forwarding and private library isolation, TLS/URL/token validation, default-off client flag, opaque mailbox/object/rendezvous/collaboration isolation, expiry/quota bounds, bounded authenticated HTTP and relay admission, relay rejection, read-only MCP, GUI/desktop packaging and private staging-file permission rejection. |
| `test_themes.py` | 5 | Nordic Glass, Bento Cloud and Midnight Sync registration; shared components and distinct palettes; Midnight-only dark preference; persisted selection; safe legacy/invalid fallback. |
| `test_tor.py` | 4 | Fail-closed transport policy, private bridge handling, Onion client authorization validation and revocation. |
| `test_update_dialog.py` | 2 | Safe close behavior during active work and rejection of late callbacks after shutdown. |
| `test_rclone.py` | 19 | OAuth question parsing, callback handling, remote validation, provider behavior, Proton protection, and automatic Secret Service-backed rclone configuration encryption. |
| `test_updater.py` | 18 | Version validation/comparison, platform-channel selection, trusted URLs, expiry/checksum/tamper rejection, globally rate-limited downloads, size/partial cleanup, privileged immutable staging and signed release coherence. |

Android JVM coverage is kept beside the mobile source: `MobileValidationTest` contains 6 tests for bandwidth, automatic headroom, and version inputs, `MobileNetworkControllerTest` contains 2 tests for serialized access and exception-safe permit release, `ProfileQrTest` contains 2 cross-platform protocol/tamper tests, and `ProfileImporterTest` contains 2 tests for the encrypted rclone configuration plus its independent unlock key. Release CI runs `testSideloadReleaseUnitTest`; main-branch package CI runs `testSideloadDebugUnitTest` before lint and assembly. The Android build also needs the pinned `rclone.aar`; CI creates it before Gradle runs.

## Important safety invariants covered

- A first two-way synchronization uses the explicit recovery/merge path instead of assuming either side is empty.
- Later synchronizations do not silently repeat the initial resynchronization.
- Upload-only and download-only jobs preserve their configured direction.
- Streaming folders may be protected children of synchronized folders, but unsafe overlaps are rejected.
- Filename-index tests cover Unicode multi-token lookup, literal SQL wildcard characters, stale pruning, exclusion/symlink handling, paused jobs, virtual-drive avoidance, private permissions, and incomplete safety-limited refreshes.
- Search-preview tests cover default-off UI gating, live root confinement, no-follow and bounded reads, binary/oversized rejection, hostile archive entries and compression ratios, bounded office XML parsing, and fixed shell-free PDF extraction.
- Office lock files, editor temporary files and partial downloads are not synchronized.
- Google malware/spam acknowledgement is opt-in and scoped to one job.
- Peer invitations contain public SSH connection material only. A protocol-v5 Tor invitation may intentionally contain the receiving device's scoped Onion client secret and must be handled like a password; neither the host SSH identity nor the general TuxInDrive identity private key enters it.
- Tor-only policy rejects direct fallback, invalid Onion addresses are refused, client authorization is device-scoped/revocable, and Tor configuration/authorization files are private.
- Bridge credentials remain out of subprocess arguments, invitations, and application audit/log messages.
- A peer client pins the server host key and authenticates with its own private key.
- Proton accounts are not accepted until an official-CLI `/my-files` listing succeeds; no password/2FA/session enters TuxInDrive arguments or configuration, inherited plaintext credential-store overrides are rejected, and native jobs cannot enter rclone callback or mount paths.
- Update packages are not installed until both desktop and privileged helper verification succeed; the helper verifies a root-only staged copy and trusts neither a user-supplied digest nor the previously opened user-writable path.
- Incoming replacement/deletion recovery retains restorable content before changing the local file.
- Ransomware-like extensions and configured mass-change thresholds pause propagation.
- Integrity audit differences are parsed into explicit, selectable repair findings.
- A legacy one-key share migrates into the named-device model without losing access.
- Every enabled public key receives a distinct authorization file/listener; role-limited keys cannot share a broader endpoint and revoked/disabled keys are omitted.
- A foreign unexpired edit lease blocks acquisition instead of allowing an overwrite.
- LAN/QR invitations preserve the pinned host key and lease duration; protocol-v1 invitations remain importable.
- Nautilus actions route through the single application instance, and startup-time sync requests wait for runtime readiness.
- Peer delta blocks are individually BLAKE2-verified, the reconstructed file is SHA-256-verified, and replacement is atomic.
- Transfer policy defaults remain unrestricted; controlled mode defers jobs on configured battery, metered-network, and schedule conditions.
- The stricter global/job directional bandwidth limit reaches synchronization, streaming, scans, verification and repairs; native Git/Proton/update work shares admission, and scan jitter remains bounded.
- An incremental job reserves its ID before it waits for network admission, preventing a full or second incremental run for the same mapping from starting concurrently.
- Protocol-v4 peer invitations preserve roles, drop scope and expiry while legacy protocols remain importable.
- Expired one-time drops are rejected before a remote is saved.
- Read-only, send-only and receive-only jobs reject incremental changes from the prohibited direction; read-only copies do not delete local extras.
- Every provider has a capability record and unsupported peer streaming/unsafe Proton sharing controls are rejected by the adaptive model.
- Audit events are written with mode `0600`, can be filtered by job and ignore malformed historical lines safely.
- Encrypted profiles reveal no clear configuration, reject wrong passwords and modification, and exclude OAuth/peer secrets unless the sensitive option is explicitly selected. Credential-enabled profiles bind the rclone configuration to its separate unlock key; QR transfer remains encrypted, bounded and digest-verified, and omits peer private files.
- Restored configuration and opted-in credential/key files retain private `0600` permissions, while a local pre-migration configuration is kept for rollback.
- ODF archives are rejected before expansion when entry count, bytes, entry size, duplicate/path or compression-ratio limits fail; unsafe XML entities never enter the structured editor.
- Collaborative operation files are bounded regular JSON with validated identifiers/counters, a global count ceiling and non-recursive deterministic traversal.

## Build and inspect the Debian package

```bash
sh scripts/build-deb.sh
dpkg-deb --info dist/tuxindrive_0.26.25_all.deb
dpkg-deb --contents dist/tuxindrive_0.26.25_all.deb
sha256sum dist/tuxindrive_0.26.25_all.deb
```

The CI **Static security analysis** step must run before tests and packaging:

```bash
bandit -q -r src -lll
pip-audit -r requirements-security.txt
```

The release is blocked on any high-severity Bandit result or unresolved dependency advisory. Do not add an ignore merely to make CI green; document exploitability and a time-bounded exception in `SECURITY.md` if no fixed dependency exists. The 0.16.0 floor was introduced because 46.0.7 was affected by PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf.

Release manifests must be signed outside Git with the Ed25519 release key:

```bash
python3 scripts/sign-update.py --version 0.26.25 \
  --package dist/tuxindrive_0.26.25_all.deb \
  --output update/latest-v2.json \
  --private-key /secure/offline/TuxInDrive-update-signing-private.pem
```

Only the public key belongs in source control. Store the private key offline or in a protected release secret, restrict release environments, and rotate the embedded public key through a separately reviewed application release if compromise is suspected.

After signing, parse the manifest with `UpdateManager.parse_manifest`, compare its SHA-256 with the package, inspect the embedded Debian package/version, and confirm the expiry is in the future. `test_repository_manifest_matches_current_debian_release` now blocks CI if a version/package is committed without its matching signed manifest. A successful unit suite alone is not a release authorization.

The build script performs an additional import smoke test against the exact staged `/usr/lib` layout used after installation. It verifies the TuxInDrive version and confirms that the desktop application, updater, peer, and recovery modules are discoverable.

Build the separate headless server package and inspect its unit, launcher,
private bootstrap and installed module layout:

```bash
sh scripts/build-server-deb.sh
dpkg-deb --info dist/tuxindrive-server_0.26.25_all.deb
dpkg-deb --contents dist/tuxindrive-server_0.26.25_all.deb
PYTHONPATH=src python3 -m unittest -v tests.test_server
```

The HTTP tests open a temporary loopback socket. A sandbox that forbids every
socket must run that module in a namespace which permits loopback while still
blocking external traffic.

## Manual release matrix

Automated tests do **not** replace live provider and desktop testing. Before a stable release, maintainers should record results for this matrix:

| Area | Required manual scenario |
|---|---|
| Installation | Clean Ubuntu 26.04 install, upgrade from the previous package, application-menu launch and tray visibility. |
| OAuth | New Google Drive and OneDrive accounts, browser cancellation, reconnect and expired-token recovery. |
| Credential providers | MEGA and Nextcloud app-password flows; official Proton CLI install, browser login/2FA, `/my-files` validation, expired-session reconnect, legacy-rclone migration, logout, offline/online restart, nested exceptions, and one-sided deletion restoration. Confirm the password/2FA/session never appears in TuxInDrive configuration, logs, or process arguments. |
| Selective sync | Nested folder selection, multiple selected roots, rename/move, deletion and conflict copy. |
| Folder organization | Reorder folders before/after one another, move them across named groups and Ungrouped, restart the app, and confirm order/membership persist. Minimize each group and verify one provider icon per folder plus tooltip, drop into a minimized group, expand it, and confirm no local/cloud path changed. Repeat with keyboard using the Group dialog. |
| Streaming | Empty mount, file hydration on open, write-back, disconnect, unexpected mount loss and restart. |
| Offline availability | Pin individual streamed files/folders, disconnect networking, open pinned content, free local space, restart the mount, and confirm rules persist. |
| Block delta | Change one block in a multi-gigabyte peer file, verify reduced transmitted bytes in logs, corrupt a queued block, and confirm the receiver rejects it without replacing the destination. |
| Peer sharing | Three or more clean machines, simultaneous access, named-key revocation, disabled key, wrong key rejection, address edit, restart recovery and a large-file transfer. |
| Tor transport | Validate persistent/ephemeral Onion addresses, two separately authorized clients, QR import, revoked and rotated client authorization, Tor restart semantics, service failure, SOCKS failure, Tor-only clearnet refusal, no-relay/no-IP rules, bridges in a filtered-network lab and confirmation that secrets are absent from logs/process listings. |
| Peer roles | Exercise each role in both directions using both TuxInDrive and a generic SFTP client. Verify distinct ports/one-key files, server read-only behavior, send-only inbox roots, revocation and mixed-role isolation. |
| One-time drop | Test its dedicated port/root with a generic client, parent-workspace denial, expiry, first-file consumption, current-session completion, reconnect rejection and restart persistence. Confirm ordinary jobs exclude the hidden compatibility drop metadata. |
| Audit timeline | Produce success, failure, policy, peer, delta and drop events; verify local-only storage, permissions, compaction, path sensitivity and malformed-line recovery. |
| Capability UI | Change among all providers and confirm unsupported modes/actions disappear or disable while server-specific caveats remain visible. |
| Sync health | Verify running, mounted, paused, callback, last-run and error states against actual job behavior, then reopen to refresh the snapshot. |
| Main-window identity | Connect one account for every provider and confirm account/job rows retain the provider icon in idle, syncing, paused and error states. Test the compact enable switch with Ubuntu default, dark and high-DPI themes. |
| Visual designs | Select Nordic Glass, Bento Cloud, and Midnight Sync in Settings. Confirm immediate application after Save, restart persistence, rounded cards/buttons, readable hover/focus/disabled states, Bento summary counts, Midnight contrast, Nordic fallback, and unchanged folder/group/transfer state at 920×620 and common high-DPI scales. |
| Edit leases | Simultaneous save of the same file, foreign lease pause, normal release, application crash, lease expiry and retry. Confirm non-TuxInDrive writers are documented as outside advisory enforcement. |
| LAN/QR pairing | Discovery on one subnet, no discovery across a routed boundary, full fingerprint comparison, QR display/import, invalid image rejection and manual-pairing fallback. |
| Nautilus integration | Test enabled and disabled settings after restarting Nautilus; confirm menus/badges disappear when disabled and streaming items expose pin/free-space actions when enabled. |
| Internet peer sharing | Direct, UPnP, NAT-PMP and reverse-relay connections; verify host-key pinning, relay fallback, no retained relay content, tunnel recovery, and manual direct mode. |
| Transfer policies | Maximum environmental policy, metered connection, AC/battery transition, overnight schedule, invalid/disconnected NetworkManager state, global and job directional ceilings, streaming/update/Git/Proton admission, scan jitter, and queued retry. |
| Platform packages | Install and upgrade the signed Windows setup, macOS DMG and Android APK; verify dedicated channel manifests, durable Release URLs, platform/architecture rejection, Android certificate continuity and branded launcher icon. |
| Update | No-update result, valid update, corrupted package, symlink, same-user replacement race, manifest change, cancelled PolicyKit prompt and successful installation from root-only staging. |
| Diagnostics | Startup log, application log, per-job log and crash-log paths contain useful information without secrets. |
| Recovery | Replace and remotely delete test files, restore several versions, expire retention, and verify current-file archival before restore. |
| Mass-change safety | Preview a disposable large rename/deletion burst and ransomware-like suffix batch; confirm the job pauses before real propagation. |
| Integrity repair | Produce local-only, remote-only, changed and unreadable paths; repair reviewed subsets from each side and re-audit. |
| Encrypted vault | Create a dedicated vault, verify ciphertext/name encryption in the backing account, sync/stream through the vault, and confirm a wrong password cannot read data. |
| TuxInDrive Profile | Store configuration-only and sensitive backups on each supported OAuth provider; inspect and restore on a clean device, test `.tdx` and multi-frame QR Android import/restart, wrong passwords, mixed/missing frames, older missing-key profiles and tampered objects; confirm discovery, transactional rollback and that default backups do not migrate tokens or private keys. |

Use test accounts and disposable folders. Back up both sides before testing deletion, conflict, migration or bidirectional recovery behavior.

## Current coverage boundaries

The repository suite is primarily deterministic unit and command-construction testing. It does not currently provide:

- automated live-provider OAuth tests;
- a disposable two-host network integration environment;
- GTK screenshot regression testing;
- fault injection for power loss during transfers or configuration writes;
- multi-gigabyte performance and memory benchmarks;
- compatibility testing against every provider account type and regional endpoint.
- automatic interpretation of Ubuntu backported security patches from an upstream-looking package version;
- automated privileged PolicyKit/real-APT race testing in an isolated VM;
- sustained hostile peer/drop quota and session-termination testing beyond the dedicated-root authorization tests;
- sustained hostile authenticated slow-body and concurrent relay testing for the optional server beyond deterministic admission-limit tests;
- real-VM installed-package tests that prove the server cannot write `/etc/tuxindrive-server`; deterministic package and symlink-boundary tests cover the same invariants in the repository suite;
- reproducibility, native Windows/macOS signature, notarization and provenance verification for every platform release input.

The remaining external and real-system checks are tracked in the
[2026-08-22 security audit](SECURITY_AUDIT_2026-08-22.md).

These gaps are tracked as roadmap work rather than implied coverage.

## Adding a regression test

1. Reproduce the failure with sanitized paths and no credentials.
2. Add a focused test to the closest `tests/test_*.py` module.
3. Assert the safety outcome, not only the generated command—for example, that a destructive action is stopped or a key mismatch is rejected.
4. Run the complete suite and package build.
5. Document any provider-specific or manual verification still required.
