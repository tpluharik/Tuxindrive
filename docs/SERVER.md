# TuxInDrive Server preview

TuxInDrive Server is the first functional Linux implementation of the server
and headless-agent plan. It is packaged separately as
`tuxindrive-server_VERSION_all.deb`; installing the desktop package does not
start a server. The server package includes its own GTK administration
application; the service itself remains headless. The client integration is
disabled by default and becomes
available only after **Settings → Enable TuxInDrive server integration
(preview)** is selected.

This release establishes a bounded, self-hostable foundation. It is not a
public multi-tenant cloud service and does not weaken direct peer operation.
Direct LAN/SFTP synchronization continues to work without this server.

The 0.26.27 cross-folder filename index remains entirely on each desktop
client. It is not uploaded to the server preview, and no server endpoint accepts
filenames or search queries. Server-backed search would require a separate
privacy and authorization design and is not part of the current preview.

## Implemented roles

Every role is independently named in `enabled_roles`. Removing a role makes
its endpoint return `404`; it does not silently enable a substitute.

| Role | First-version behavior |
|---|---|
| `agent` | Loads the normal TuxInDrive configuration without GTK, reuses `SyncEngine`, `PeerManager`, transfer policy and the global bandwidth controller, schedules enabled non-streaming jobs, starts enabled peer listeners (including configured Tor peer services), and exposes redacted job state plus sync/dry-run/cancel actions. |
| `mailbox` | Queues opaque client-encrypted messages for offline devices with tenant isolation, expiry, acknowledgement deletion, count/byte bounds and audit events. |
| `rendezvous` | Publishes bounded opaque signed device reachability envelopes with replacement and short expiry. Clients remain responsible for signature/key-change verification. |
| `objects` | Stores content-addressed encrypted blocks/snapshots by SHA-256, with tenant isolation, deduplication, expiry and quotas. The server receives ciphertext, size and timing—not content keys or plaintext names. |
| `collaboration` | Orders and returns bounded encrypted collaboration operations per opaque workspace identifier. It does not decide document truth or decrypt operations. |
| `relay` | Implements an authenticated HTTP `CONNECT` byte relay. A destination must appear exactly in `relay_targets`; sessions are time/byte bounded and only transferred-byte totals enter audit. Nested peer encryption remains mandatory. |
| `attestation` | Returns the running server version and explicitly configured signed updater manifests. It never signs or rewrites release metadata. |
| `mcp` | Implements a read-only MCP JSON-RPC preview with `health`, `list_jobs`, and `recent_audit`. There is no delete, arbitrary filesystem, credential, shell or unconfirmed mutation tool. |

The authenticated HTTP API is also the first remote/local administration API.
The unauthenticated `/healthz` endpoint returns only `{"status":"ok"}` for a
service manager. All `/v1/` endpoints require a bearer token.

## Installation

Download `tuxindrive-server_0.26.27_all.deb` from the matching
[GitHub Release](https://github.com/tpluharik/Tuxindrive/releases/tag/v0.26.27),
then install that local file. The leading `./` is required so APT treats the
name as a file instead of searching configured package repositories:

```bash
cd ~/Downloads
sudo apt install ./tuxindrive-server_0.26.27_all.deb
```

If configuration of the defective 0.26.12 preview was left unfinished,
installing 0.26.27 replaces its launcher and completes the pending package
configuration. If APT asks to repair dependencies afterward, run:

```bash
sudo apt --fix-broken install
sudo dpkg --configure -a
```

Build and inspect the package:

```bash
sh scripts/build-server-deb.sh
dpkg-deb --info dist/tuxindrive-server_0.26.27_all.deb
dpkg-deb --contents dist/tuxindrive-server_0.26.27_all.deb
sudo apt install ./dist/tuxindrive-server_0.26.27_all.deb
```

The package creates a locked `tuxindrive-server` system account, a root-owned
`/etc/tuxindrive-server` directory, service-owned runtime state and a hardened
systemd unit. `server.json` is `root:tuxindrive-server` mode `0640`; the service
cannot modify it. It initializes a
random 384-bit API token once. Read and then securely remove its bootstrap copy:

```bash
sudo cat /var/lib/tuxindrive-server/bootstrap-token
sudo shred -u /var/lib/tuxindrive-server/bootstrap-token
sudo systemctl enable --now tuxindrive-server
curl http://127.0.0.1:9443/healthz
```

The service is not enabled automatically because installation must not expose a
new network service without an administrator's explicit action.

## Graphical administration

Open **TuxInDrive Server** from the Linux Applications menu, or run this as the
signed-in desktop user:

```bash
tuxindrive-server gui
```

Running `tuxindrive-server` with no command opens the same application. Do not
run the GUI with `sudo`: it intentionally rejects a root desktop session. The
window opens maximized, and each page remains scrollable on smaller displays.

The application provides:

- service status plus start, stop, restart, enable and disable controls;
- every field in the validated server configuration, including roles, TLS,
  storage, quotas, expiry, bandwidth, relay targets and update manifests;
- local validation, protected save and an optional immediate service restart;
- high-entropy tenant-token generation, tenant removal and one-time raw-token
  display/copy while storing only its SHA-256 digest;
- protected bootstrap-token display/copy and deletion; and
- the latest service journal entries without requiring a terminal.

The window runs unprivileged. Linux PolicyKit authorizes each protected action
separately. The privileged helper accepts only fixed service/configuration
operations: it does not invoke a shell or accept an arbitrary destination. A
configuration save is staged in a caller-owned mode-0600 regular file, rejects
symlinks, wrong ownership and permissive modes, validates the complete schema,
then replaces the fixed system configuration atomically. Closing the GUI does
not stop the server service.

## Client setup

1. Open desktop **Settings**.
2. Select **Enable TuxInDrive server integration (preview)**.
3. Enter the server origin. Plain HTTP is accepted only for
   `localhost`, `127.0.0.1`, or `::1`; a remote origin must use HTTPS.
4. Paste the bootstrap/API token. TuxInDrive saves it in Secret Service,
   Windows Credential Manager, or macOS Keychain—not in `config.json`.
5. Optionally enter a private CA file, then select **Test server connection**.
6. Save Settings. Disabling the flag removes the live client object but does
   not delete server data or the native credential entry.

The first desktop integration checks authenticated health/capabilities and
provides the connection object to later mailbox/object/collaboration UI work.
It does not redirect existing direct or cloud jobs through the server merely
because the feature flag is enabled.

## Configuration

The graphical application is the normal interactive configuration method. The
file format and commands below remain supported for backup, recovery and
unattended automation.

The default configuration is `/etc/tuxindrive-server/server.json`:

```json
{
  "schema": 1,
  "bind": "127.0.0.1",
  "port": 9443,
  "tls_certificate": "",
  "tls_private_key": "",
  "database": "/var/lib/tuxindrive-server/server.sqlite3",
  "client_config": "",
  "enabled_roles": ["agent", "mailbox", "rendezvous", "objects", "collaboration", "relay", "attestation", "mcp"],
  "token_hashes": {"SHA256_OF_TOKEN": "owner"},
  "quota_mib_per_tenant": 512,
  "default_ttl_seconds": 86400,
  "global_bandwidth_limit": "10M",
  "automatic_bandwidth_control": true,
  "bandwidth_headroom_percent": 20,
  "max_concurrent_requests": 16,
  "max_requests_per_source": 4,
  "request_timeout_seconds": 30,
  "max_relay_connections": 4,
  "max_relay_connections_per_tenant": 2,
  "relay_idle_timeout_seconds": 30,
  "relay_targets": [],
  "update_manifests": []
}
```

Request admission is bounded globally and per source before a worker starts.
Every accepted connection receives a read deadline. Relay admission is also
bounded globally and per tenant; idle relays expire, total time/bytes remain
capped, and both relay directions use the same configured global bandwidth
clock as the headless agent. Automatic protection reserves the configured
headroom before traffic is admitted, preventing agent and relay roles from
independently consuming the complete ceiling.
The systemd unit independently caps tasks, file descriptors and memory.

`token_hashes` maps token SHA-256 digests to tenant IDs. The bootstrap mapping
uses the reserved tenant ID `owner`; only that token may list or start/cancel
headless synchronization jobs. Other tenant tokens can access only their own
storage, coordination, statistics and audit rows. The raw token is never
stored in the server JSON or database. To add a tenant, generate a strong random
token, place its SHA-256 digest in the map, deliver the raw token through a
separate trusted channel and restart the service. A production reverse proxy
must not log `Authorization` headers.

Set `client_config` only when the system service should run preconfigured cloud
or peer jobs. Copy a deliberately prepared configuration into a directory
readable by the service account; do not point the system service at an ordinary
desktop user's home. Provider credentials must separately exist in the service
account's rclone/Proton credential context.

For a non-loopback bind, both TLS files are mandatory and startup fails closed
without them. Keep port `9443` behind a host firewall. Use a separately
authenticated Tor reverse proxy if the API itself should be reachable through
an Onion Service; configured peer Onion Services remain managed by the existing
per-share Tor implementation.

Validate after editing:

```bash
sudo -u tuxindrive-server tuxindrive-server check \
  --config /etc/tuxindrive-server/server.json
sudo systemctl restart tuxindrive-server
```

## API outline

- `GET /v1/health`, `GET /v1/capabilities`, `GET /v1/stats`
- `GET /v1/jobs`, `POST /v1/jobs/ID/sync|dry-run|cancel`
- `POST|GET /v1/mailbox`, `DELETE /v1/mailbox/ID?recipient=DEVICE`
- `POST /v1/objects`, `GET /v1/objects/SHA256`
- `POST /v1/rendezvous`, `GET /v1/rendezvous/DEVICE`
- `POST|GET /v1/collaboration?workspace=ID`
- `CONNECT HOST:PORT` for exact configured relay targets
- `GET /v1/attestation`, `GET /v1/audit`, `POST /v1/mcp`

Opaque payload fields use strict base64 and are limited to 12 MiB per request.
JSON bodies are limited to 16 MiB, list results are capped, TTLs are bounded,
per-tenant storage quotas are atomic inside SQLite transactions, expired rows
are removed before access, and source requests are rate-limited. SQLite uses
WAL plus full synchronous durability and private permissions.

## Security and present limits

- The server authenticates transport/API access; end-to-end encryption and
  signatures remain client responsibilities. Uploading plaintext to an opaque
  endpoint does not make it encrypted.
- The server observes tenant, recipient/workspace opaque identifiers, sizes,
  timing, IP addresses and relay destinations. It cannot promise anonymity.
- Token hashing protects the stored verifier but is not a substitute for a
  high-entropy token. A stolen bearer token authorizes that tenant until it is
  removed and the service restarted.
- The first release uses one process and SQLite. It is suited to a personal or
  small trusted deployment, not an unreviewed internet-scale service.
- Federation, hardware-backed service identity, web administration, OCI/NAS
  appliances, push notification adapters and mutating MCP tools remain future
  compatibility layers. The role interfaces are deliberately versioned so
  they can be added without changing ciphertext or silently widening access.
- A formal external protocol/security review and long-duration fault-injection
  test remain required before removing the **preview** label.

See [Security hardening](SECURITY_HARDENING.md), [Architecture](ARCHITECTURE.md),
[Configuration](CONFIGURATION.md), [Operations](OPERATIONS.md), and
[Roadmap](ROADMAP.md) for the surrounding client trust boundaries.
