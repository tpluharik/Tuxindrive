# Cross-platform performance audit — 2026-08-27

## Scope and guarantees

This audit covers the shared Python engine and GTK desktop client on Linux,
Windows and macOS, the embedded-rclone Android client, update paths, metadata
monitoring, streaming, recovery and peer services. It is a static hot-path
review plus the repository's deterministic test suite; it is not a substitute
for provider-scale benchmarks on real hardware. Proposed changes retain safety
previews, conflict preservation, signature and hash verification, path
confinement, credential handling and durable baselines.

The current implementation already coalesces GTK refreshes, tails logs with a
fixed memory budget, suppresses identical configuration writes, batches
incremental paths, applies scan jitter/backoff, and serializes network work.
The default bandwidth policy now also reserves 50% of the configured ceiling
for other applications on desktop and Android.

## Prioritized findings

| Priority | Platform/path | Finding | Safe optimization | Acceptance evidence |
|---|---|---|---|---|
| P0 | Desktop restart / two-way sync | The scheduler keeps its last-start and last-full-run clocks only in memory. Thirty seconds after a restart every initialized job therefore appears to have no baseline and becomes immediately due, even though `job.last_run` and durable bisync listings are present. Realtime monitors simultaneously rebuild local and remote snapshots, duplicating traversal; protected two-way jobs can then perform a full safety dry-run before the real bisync pass. | Restore the scheduler clock from a strictly parsed, timezone-aware `job.last_run`; give initialized realtime jobs a bounded startup grace while their monitor becomes healthy; seed the monitor from a validated durable bisync snapshot when possible. Fall back to the current full safety reconciliation if timestamps are invalid/future, the baseline pair is incomplete, inotify overflows, or the monitor does not become healthy before the grace deadline. | Restart tests proving that a recently completed initialized job does not start a full bisync, stale/non-realtime jobs still run, malformed/future timestamps fail safely, missing baseline pairs still require recovery, and changes made while the application was stopped are detected by the monitor or the bounded fallback reconciliation. |
| P0 | Android offline sync | Every run copies the complete Storage Access Framework tree into a private mirror and writes the complete mirror back, making unchanged runs O(total bytes) and increasing flash wear. | Persist a private path/size/mtime/content-hash index; stream only changed files, but keep the current complete deletion preview and bisync baseline. Treat unknown provider timestamps as changed. | Byte-identical results, unchanged mass-deletion stops, process-death recovery tests, and instrumented no-change runs with near-zero payload bytes. |
| P0 | Desktop remote monitoring | Each active job can perform a recursive `lsjson` on a short interval. Large roots multiply provider API requests and memory use. Targeted checks already reduce local-save traffic but unrelated remote detection still scans the tree. | Add provider change cursors where supported and persist only validated cursors; fall back to the current authoritative recursive scan after cursor rejection, gaps, overflow or upgrade. Keep jitter and backoff. | Replay fixtures proving no missed create/move/delete, forced expired-cursor fallback, and API-call counts by provider. |
| P1 | Android document traversal | `DocumentFile.listFiles()` is repeated during copying and recursive deletion counting; the same tree can be enumerated several times per run. | Build one bounded metadata snapshot per side and reuse it for copy planning and deletion calculation. Do not cache grants or bypass path/name validation. | Identical planned operations and safety counts, with enumeration count reduced to one per directory. |
| P1 | macOS traffic meter | Visible traffic statistics spawn `netstat -ibn` every second. Process startup dominates the small read and wastes energy. | Use a native interface-counter API, or cache/sample at 3–5 seconds and interpolate display values. Sampling must still stop when the feature is hidden. | Rate/totals parity across counter rollover and interface changes; lower wakeups in Activity Monitor. |
| P1 | Per-job monitor threads | Each realtime job owns a thread and timer loop. This is simple and isolated but scales linearly with many folders. | Share a bounded scheduler and provider scan queue while retaining one isolated state machine and cancellation token per job. Keep network admission outside engine locks. | Stress test at 100 jobs with bounded threads, fair scan latency and clean shutdown. |
| P1 | Streaming metadata | Every long-lived mount has its own provider connection and refresh policy. Many mounts can duplicate directory polling. | Deduplicate read-only metadata requests for identical account/scope keys with short-lived immutable results; never share writable VFS state or credentials across accounts. | Cache-key isolation tests and no stale result after write/move/disconnect. |
| P2 | Windows traffic meter | Legacy 32-bit interface counters wrap quickly on fast links, causing inaccurate display samples and extra persistence churn. | Prefer 64-bit interface counters and preserve the current rollover-safe fallback. | Synthetic >4 GiB counter tests and multi-interface totals. |
| P2 | UI dynamic rows | Structural signatures prevent most full rebuilds, but frequent state changes still touch every visible job row. | Track dirty job/account IDs and update only affected widgets; perform a full rebuild only when the structure signature changes. | Widget identity tests and unchanged accessibility/focus order. |
| P2 | Recovery/history | Large history directories are repeatedly enumerated for retention and display. | Maintain an append-only bounded metadata index rebuilt from disk on validation failure; filesystem content remains authoritative. | Corrupt/missing-index rebuild and retention parity tests. |

## Recommended delivery sequence

1. Fix restart scheduling first: restore only validated persisted clocks, add a
   bounded realtime-monitor startup grace, and retain the full safety fallback.
   This removes duplicate startup work without weakening recovery.
2. Instrument bytes copied, metadata calls, directory enumerations, scan
   duration, queue wait and UI refresh duration without logging paths or
   credentials.
3. Implement the Android one-pass snapshot and unchanged-file skip; it
   offers the largest deterministic reduction without provider-specific risk.
4. Add provider change cursors one backend at a time behind capability flags,
   always retaining recursive reconciliation as the recovery path.
5. Replace macOS and Windows traffic-counter backends, then consolidate job
   scheduling only after stress tests define fairness and shutdown budgets.

## Implemented in 0.26.31

- The desktop scheduler restores only strictly parsed, timezone-aware recent
  completion clocks. Initialized realtime jobs with a complete durable bisync
  baseline receive a 120-second startup grace; incomplete or invalid state
  continues through the established recovery path.
- Callback monitors seed their remote baseline from the validated durable
  bisync snapshot. Independent jobs retain isolated cancellation and state, but
  identical authoritative metadata reads are shared for at most five seconds,
  under the existing global network admission controller. Adaptive backoff and
  jitter remain the safe generic alternative where rclone does not expose a
  reliable provider cursor.
- Android persists an atomic, private path/size/time/hash index, traverses the
  granted document tree once per run, copies only changed content, and keeps
  the complete mass-deletion approval threshold. Unknown timestamps fail safe
  by treating the file as changed.
- macOS reuses the expensive interface-counter sample for three seconds while
  the meter is visible. Hiding the meter still stops sampling completely.
- Desktop and Android now reserve 50% of measured bandwidth for other
  applications by default. An existing explicit user value is preserved.

The remaining P2 items are optional measurement accuracy and UI/history
scalability improvements; they are not required for the 0.26.31 restart and
idle-traffic correction.

## Restart investigation

The reported long startup reconciliation is reproducible from the control
flow and is supported by the local state inspected during this audit:

- enabled two-way jobs have persisted, timezone-aware `last_run` values and
  matching durable `path1`/`path2` bisync listing pairs;
- `TuxInDriveApplication` nevertheless initializes `_last_started` and
  `_last_full_completed` as empty dictionaries on every process start;
- the first 30-second scheduler tick treats a missing in-memory clock as
  immediately due and does not consult `job.last_run`;
- callback monitoring starts independently and, without a process-local
  callback baseline, performs an initial local traversal, remote recursive
  listing and a second race-closing local traversal;
- a scheduled protected two-way job stops that callback and runs the complete
  deletion-safety preview before the real bisync command.

This is normally an unnecessary full reconciliation rather than a true rclone
`--resync`: the durable baseline pairs are present. A true reinitialization is
still correct when either side of a baseline pair is missing or corrupt. Older
local logs also contain repeated 30-second launch attempts from an earlier
build; the current in-process `_last_started` guard prevents that exact retry
loop, but it does not prevent the first redundant full job after a restart.

The safe target behavior is therefore: start monitors, recover their baseline
from validated durable state, detect changes accumulated while TuxInDrive was
offline, and run only incremental work. A full reconciliation remains the
bounded fallback for stale jobs, unhealthy monitors, invalid clocks, overflow
or incomplete state. Persisted time alone must never be treated as proof that
the filesystem and provider are equal.

## Validation performed

- Python `unittest` discovery covers restart scheduling, baseline reuse,
  shared metadata caching, traffic-sample caching, bandwidth reservation and
  the existing functional/security suite.
- Python source compilation was checked with an external bytecode cache.
- Bandwidth tests cover directional limits, zero/unlimited values, 50% reserve,
  shared byte-clock throttling, admission release and deadlock avoidance.
- Android unit coverage includes matching directional reserve calculations.

The sandbox used for the audit blocks UDP sockets, so LAN-discovery worker
threads reported expected permission errors during the Python run; the test
suite itself completed successfully once writable isolated state paths were
provided. Android compilation still requires the repository's Gradle/rclone
toolchain in CI or an Android SDK environment.
