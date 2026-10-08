# TuxInDrive testing and release verification

TuxInDrive treats synchronization, deletion propagation, authentication, mounting, and software updates as safety-sensitive behavior. Every change affecting these areas should add or update an automated test and describe any remaining manual verification.

## Run the automated suite

From the repository root:

The ordinary unit suite installs a fail-closed signal guard **before importing
application code**. Real `kill`, `killpg`, pidfd, thread-signal and Windows
termination calls are blocked; only exact positive-PID `kill(pid, 0)` probes
are allowed. Signal assertions must mock the endpoint. There is no environment
variable that disables this guard. Every test module imports it explicitly,
including when discovered with `unittest discover -s tests`.

```bash
python3 -m pip install .
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
cd android
gradle :app:testSideloadDebugUnitTest
```

The dependency-install step is required when using an isolated Python environment such as GitHub Actions. Python-package builds require `cryptography>=50.0.0,<51`; Ubuntu `.deb` installations use the distribution-maintained `python3-cryptography` package so official Ubuntu backported security fixes are recognized by APT rather than compared only by the upstream version string.

CI pins third-party actions by immutable commit, runs high-severity Bandit checks and `pip-audit`, and publishes a CycloneDX dependency SBOM with the package.

The source defines **608 unit checks: 595 Python tests and 13 Android JVM tests**, plus three separate isolated process-lifecycle checks. These counts describe test definitions, not evidence that a particular revision has passed CI. Four Python checks require an isolated GTK display and are skipped during the normal headless suite. Tests use temporary directories and mocked cloud/Git/Tor processes where possible, so they do not require or expose real credentials or personal files. Coverage includes automatic, manual-only and Codex chat-only AI-tool backups, protocol-provider capability guards, selective transfer rules, non-destructive per-file recovery, managed policy, cloud copy, content indexing, aggregate tray state and error summaries, and historical upgrades. Server API and Network Lab integration use only temporary loopback listeners and fictional ciphertext-like bytes.

The credential/backup regressions use synthetic data and cover mocked timeout
cleanup, no key replacement on credential-store failure,
deny-first chat filters, excluded incoming deletions and filter-free incremental
manifests. The real local rclone copy check skips when rclone is unavailable;
provide `TUXINDRIVE_TEST_RCLONE=/absolute/path/to/rclone` to run it explicitly:

```bash
PYTHONPATH=src TUXINDRIVE_TEST_RCLONE=/absolute/path/to/rclone \
  python3 -m unittest tests.test_backup_regressions -v
```

No live cloud account or personal chat files are used by these regressions.

### Real process lifecycle: isolated CI only

Real process-group checks were moved to `integration_tests/test_process_groups.py`
and are **not** part of ordinary unit discovery. They require both explicit
`TUXINDRIVE_ISOLATED_PROCESS_TESTS=1` opt-in and a Linux container marker, with
no graphical desktop environment. The dedicated `isolated-process-lifecycle`
CI job uses a disposable container, a process-count limit and a five-minute
job timeout. Do not run these checks directly in a developer desktop session.
The in-process unit guard is never disabled for integration checks; they run
in a separate interpreter/container instead.

Application cancellation and Tor reload share the same ownership gateway.
Only native `Popen` instances created through `spawn_process` are registered;
mock objects, coerced/bool/invalid PIDs and unregistered processes are rejected.
On Linux, verified session members are pinned with pidfds and birth identities,
so escalation after leader reaping cannot signal a reused PID. On systems
without pidfds, group signals require an unreaped isolated leader and hold its
wait/poll lock without blocking cancellation; after reaping or while the lock
is busy they fail closed. Portable background waiters use short bounded waits
so they cannot monopolize that lock. Timeout helpers never enter Popen's
context manager with its unbounded exit wait. Unknown/unverifiable descendants
are never adopted by numeric PID alone. Debian upgrades use exact launcher
arguments and pidfds, and skip automatic process shutdown without pidfd support.

Run the real GTK tray-menu checks separately on Linux with GTK 3, PyGObject,
Xvfb and xauth installed:

```bash
PYTHONPATH=src TUXINDRIVE_GTK_TESTS=1 xvfb-run -a python3 -m unittest tests.test_tray_gtk -v
```

These checks build the actual GTK menus on a virtual display, verify both
menus and overflow entries, activate the selected error row, and check that
resolved errors disappear. Application configuration and logs use temporary
directories; cloud synchronization is never started.

## Test groups

| Test module | Tests | What it verifies |
|---|---:|---|
| `test_ai_backups.py` | 13 | Local Codex, Claude Code, Gemini CLI, Cursor and Continue discovery; override handling; secret exclusions; automatic, manual-only and Codex chat-only upload scheduling; connector persistence; seven-day retention migration; safe remote components and symlink rejection. |
| `test_audit.py` | 4 | Private audit persistence, filtering, bounded newest-first reads across chunk boundaries, malformed historical-line handling and private CSV/JSONL export. |
| `test_bandwidth.py` | 13 | Directional syntax and invalid values, stricter global/job limits, automatic headroom/fair division, independent upload/download clocks, network-slot admission and release, update byte clock and bounded scan jitter. |
| `test_bootstrap.py` | 7 | Linux/macOS transfer-engine selection, rejection and identity-cached revalidation of incompatible/replaced rclone versions, supported CPU architectures, and pinned release checksums. |
| `test_capabilities.py` | 3 | Complete provider records and conservative adaptive-mode restrictions. |
| `test_config.py` | 12 | Round-trip persistence, bandwidth/theme/cache/visibility validation, legacy path compatibility, unchanged-write suppression, private permissions, and invalid configuration quarantine. |
| `test_delta.py` | 1 | Rolling BLAKE2 block signatures identify only modified ranges and calculate transferred bytes. |
| `test_diagnostics.py` | 1 | Startup failures are written before GTK imports, allowing diagnosis when the graphical runtime cannot start. |
| `test_platform_support.py` | 5 | Safe distribution parsing, Linux/macOS/Windows machine-readable capabilities and unsupported-architecture blocking. |
| `test_engine.py` | 97 | Full and incremental modes, atomic reservation, non-blocking mount startup, aggregate streaming budgets, global rates/admission, jitter/backoff, deletion/conflict safety, streaming/mount recovery, owned mount shutdown, offline hydration, marker confinement, symlink rejection and engine replacement. |
| `test_file_preview.py` | 13 | Default-local bounded text/image/document previews, no-follow reads, folder non-enumeration, UTF handling, archive traversal/ZIP-bomb rejection, and shell-free page/time-limited PDF extraction. |
| `test_github_sync.py` | 6 | Credential-free GitHub URL/branch/item safety, redirect migration, global admission and guarded commit/fetch/rebase/push orchestration. |
| `test_folder_layout.py` | 11 | Persistent selection during asynchronous cloud-tree loading, safe account-switch defaults, before/after drag ordering, cross-group moves, group-header append, Ungrouped fallback, self-drop handling, endpoint-path preservation, GTK text-payload round-trip and malformed-payload rejection. |
| `test_i18n_help.py` | 3 | Six-language UI fallback, Arabic/Hebrew RTL detection, complete localized in-app help topics and localized drag/collapse guidance. |
| `test_tray.py` | 8 | Animation frames, paused-job alerts, credential redaction, bounded summaries, runtime failures, and unresolved-error priority over successful or active transfers. |
| `test_tray_gtk.py` | 4 | Opt-in real GTK summaries in both menus, overflow activation, direct Error details routing, rename/resolution refresh and runtime failures. |
| `test_migration.py` | 9 | AES-GCM profile round trips, wrong-password/tamper rejection, visible and legacy cloud discovery/migration, complete unlock-key handoff, compact mobile export, secret opt-in, private permissions and validation. |
| `test_offline_action.py` | 9 | Mounted-drive fast dispatch, cold-start queuing, both supported command-line availability option forms, lexical file routing without FUSE resolution, sibling-prefix rejection, exact file-rule isolation, nested offline/online-only precedence, and green-state publication only for locally verified rules. |
| `test_nautilus_extension.py` | 12 | Exact path/menu isolation, cached/coalesced badge refresh, URI lifecycle, Nautilus 4.1 construction, sensitivity and verified offline transitions. |
| `test_network_usage.py` | 10 | Linux/macOS/Windows counter parsing and failure handling, platform dispatch, current rates, daily reset, counter rollover and private persistent totals. |
| `test_packaging.py` | 17 | Debian/Windows/macOS/Android packaging, release-channel layout, native assets, automatic missing-version publication, upgrade process, Nautilus routing and emblem metadata. |
| `test_password_helper.py` | 8 | Private credential-helper input/output, packaged Secret Service fallback, migration-key storage and rejection behavior. |
| `test_profile_qr.py` | 3 | Stable desktop/Android QR protocol, multi-frame ordering/deduplication, bounds and incomplete/mixed/tampered transfer rejection. |
| `test_performance.py` | 16 | Inotify delivery/startup race, remote retry, shared scans, interruptible monitor shutdown, overflow reconciliation, monitor safety, cache protection, fail-closed markers and performance hooks. |
| `test_process_control.py` | 21 | Mock/PID spoofing rejection, registered ownership, birth identities, pidfd cleanup after reaping, PID/session reuse rejection, native Windows handles, non-blocking POSIX lock checks, bounded waits and mocked timeout behavior; all signal endpoints intercepted. |
| `test_signal_safety.py` | 3 | Fail-closed Python signal endpoints, audit protection for cached aliases and exact positive-PID zero-signal probes. |
| `test_upgrade_processes.py` | 5 | Exact launcher matching, invalid-PID rejection, pidfd escalation, raced process identity and clean-exit handling; no installer execution. |
| `test_proton.py` | 30 | Official CLI install/login/session, Secret Service, redaction/confinement, backend migration, safety previews, global admission and fail-closed routing. |
| `test_collaboration.py` | 11 | Offline CRDT convergence, iterative deep-chain handling, immutable/bounded operation state, checkpoints, review/presence, deterministic ODT/ODS round trips, ZIP-bomb rejection, unsafe XML rejection and binary fallback. |
| `test_peer.py` | 27 | Invitation compatibility, approval-based LAN requests/advertisements, roles/drops/transports, signed atomic deltas, isolated device roots, authorization/revocation, host-key pinning, leases and private identities. |
| `test_policies.py` | 7 | Controlled defaults plus battery, metered-network and normal/overnight schedule decisions, including fail-open probe handling. |
| `test_recovery.py` | 13 | Local archive/restore behavior, disabled retention, malformed/foreign record rejection, expiry pruning, mass-change and ransomware-suffix blocking, integrity-audit parsing and directional repairs. |
| `test_responsive_windows.py` | 5 | Monitor-safe, freely resizable client/server windows, local scrolling, wide-control isolation and search preview feature gating. |
| `test_search_index.py` | 13 | Private metadata indexing, explicit bounded content opt-in, Unicode/token lookup, cancellation, literal wildcard handling, stale pruning, exclusions, symlink rejection, paused roots, streaming avoidance and safety-limit retention. |
| `test_security.py` | 8 | Empty/absolute/parent path rejection, symlink refusal, confined atomic installation, Ed25519-only keys and signed transaction tamper detection. |
| `test_server.py` | 26 | Private initialization, race-resistant root configuration writes, shared agent/relay bandwidth control, package-launcher forwarding and private library isolation, TLS/URL/token validation, default-off client flag, opaque mailbox/object/rendezvous/collaboration isolation and deterministic same-second operation ordering, expiry/quota bounds, bounded authenticated HTTP and relay admission, relay rejection, read-only MCP, GUI/desktop packaging and private staging-file permission rejection. |
| `test_network_lab.py` | 4 | Separate release packaging, 19 loopback-only production-protocol scenarios with fictional tenants, real multi-address local TCP/HTTP traffic, private redacted reports, cancellation/cleanup, visual topology and non-blocking GUI progress reporting. |
| `test_themes.py` | 5 | Nordic Glass, Bento Cloud and Midnight Sync registration; shared components and distinct palettes; Midnight-only dark preference; persisted selection; safe legacy/invalid fallback. |
| `test_tor.py` | 4 | Fail-closed transport policy, private bridge handling, Onion client authorization validation and revocation. |
| `test_update_dialog.py` | 2 | Safe close behavior during active work and rejection of late callbacks after shutdown. |
| `test_rclone.py` | 22 | OAuth question parsing, callback handling, remote validation, provider behavior, Proton protection, non-destructive cross-account copy, and automatic Secret Service-backed rclone configuration encryption. |
| `test_managed_policy.py` | 2 | Root-policy schema, provider/feature restrictions, bandwidth constraints and symbolic-link rejection. |
| `test_recovery_advisor.py` | 2 | Deterministic actionable failure categories and bounded fallback guidance. |
| `test_reliability.py` | 2 | Complete machine-readable scenario reporting with retained failures. |
| `test_upgrade_matrix.py` | 2 | Historical configuration migration, privacy defaults and stable round trips. |
| `test_updater.py` | 18 | Version validation/comparison, platform-channel selection, trusted URLs, expiry/checksum/tamper rejection, globally rate-limited downloads, size/partial cleanup, privileged immutable staging and signed release coherence. |

Android JVM coverage is kept beside the mobile source: `MobileValidationTest` contains 7 tests for bandwidth, automatic headroom, and version inputs, `MobileNetworkControllerTest` contains 2 tests for serialized access and exception-safe permit release, `ProfileQrTest` contains 2 cross-platform protocol/tamper tests, and `ProfileImporterTest` contains 2 tests for the encrypted rclone configuration plus its independent unlock key. Release CI runs `testSideloadReleaseUnitTest`; main-branch package CI runs `testSideloadDebugUnitTest` before lint and assembly. The Android build also needs the pinned `rclone.aar`; CI creates it before Gradle runs.

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
- New profiles use controlled transfer policy and pause below 25% while unplugged; existing explicit Maximum mode remains unrestricted.
- The stricter global/job directional bandwidth limit reaches synchronization, streaming, scans, verification and repairs; native Git/Proton/update work shares admission, and scan jitter remains bounded.
- An incremental job reserves its ID before it waits for network admission, preventing a full or second incremental run for the same mapping from starting concurrently.
- Directory topology events force authoritative reconciliation and clear stale deferred paths; vanished-parent save notifications are consumed, legitimate nested deletions remain transferable, and incremental failures retain side/phase/source diagnostics.
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
dpkg-deb --info dist/tuxindrive_0.26.61_all.deb
dpkg-deb --contents dist/tuxindrive_0.26.61_all.deb
sha256sum dist/tuxindrive_0.26.61_all.deb
```

The CI **Static security analysis** step must run before tests and packaging:

```bash
bandit -q -r src -lll
pip-audit -r requirements-security.txt
```

The release is blocked on any high-severity Bandit result or unresolved dependency advisory. Do not add an ignore merely to make CI green; document exploitability and a time-bounded exception in `SECURITY.md` if no fixed dependency exists. The 0.16.0 floor was introduced because 46.0.7 was affected by PYSEC-2026-3552, PYSEC-2026-3553, PYSEC-2026-3554, and GHSA-537c-gmf6-5ccf.

Release manifests must be signed outside Git with the Ed25519 release key:

```bash
python3 scripts/sign-update.py --version 0.26.61 \
  --package dist/tuxindrive_0.26.61_all.deb \
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
dpkg-deb --info dist/tuxindrive-server_0.26.61_all.deb
dpkg-deb --contents dist/tuxindrive-server_0.26.61_all.deb
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
| Network Lab | Install the separate `0.26.31+lab5` package, confirm all controls and topology nodes are visible, run all 19 scenarios, observe Alice/Bob link animation and non-zero connection/byte counters, cancel and restart once, and verify the listener never leaves loopback. Review the private summary/JSONL logs and confirm that no real account, credential, synchronized path or payload is present. |
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
- a disposable two-physical-host network integration environment (Network Lab
  provides two distinct loopback client addresses on one host);
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
