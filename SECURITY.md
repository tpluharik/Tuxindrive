# TuxInDrive security policy

## Supported release

TuxInDrive 0.26.24 is the supported security baseline. Older packages retained for historical reference must not be installed on production systems. Installers and APKs are published as immutable assets on the matching GitHub Release; clients accept updates only through the signed platform manifests in `releases/`.

The source review dated **2026-08-22** found a high-severity privilege-boundary
issue in the optional Linux server package, server resource-exhaustion risk,
and release-supply-chain hardening gaps. Version 0.26.20 remediates the server
boundary, bounded-network, Android updater and sensitive-path findings and adds
regression coverage. Native Windows/macOS signing and fully immutable platform
package-manager inputs remain release-environment work. See findings and status in
[docs/SECURITY_AUDIT_2026-08-22.md](docs/SECURITY_AUDIT_2026-08-22.md).

Report suspected vulnerabilities privately through GitHub's **Security → Report a vulnerability** workflow. Do not place credentials, peer invitations, Onion authorization material, private keys, or personal filenames in a public issue.

## Security boundaries in 0.26.24

- Update metadata is signed by the offline Ed25519 release key, expires, and binds the version, URL, package digest and release notes. A fixed privileged helper independently verifies that manifest, copies the package to a root-only staging directory, and checks the immutable copy before APT installation.
- Provider credentials are held in rclone's encrypted configuration. A random configuration password is stored in GNOME Secret Service. Independently encrypted rclone configurations are not overwritten.
- Untrusted relative paths are confined beneath their configured root. Security-sensitive atomic installs use no-follow directory descriptors to resist symlink replacement races.
- Tor-only and no-public-IP shares bind locally; invitations carry allowed transports and do not contain forbidden relay fallback.
- Delta transactions are signed by an authorized Ed25519 peer identity, resource bounded, hash verified, and atomically installed.
- Python-package installations require `cryptography` 50.0.0 or newer after four advisories affected the former 46.x floor. Ubuntu packages consume Canonical-maintained security backports through APT.
- Windows, macOS, Android, and Linux update channels bind platform/architecture, approved origin, versioned filename, byte size, SHA-256, expiry, and Ed25519 signature. Android packages retain a separate release-signing identity.
- One global bandwidth/admission controller covers synchronization, streaming, scans, verification, updates, GitHub, Proton, and Android. It reduces congestion and duplicate jobs but is not an authentication, integrity, or firewall boundary.
- A LAN share may advertise its name before a collaborator is known, but it exposes no file endpoint until the owner approves the requesting device fingerprint. Requests expire, deduplicate, are globally capped and rate-limited by source; approved advertisements are recipient-scoped, router mapping is opt-in, and the listener still requires the complete approved SSH key.
- Encrypted mobile-profile transfer remains end-to-end protected whether moved as a searchable `.tdx` file or bounded multi-frame QR sequence. Android verifies the envelope, independent rclone unlock key, remote availability, frame sequence and digest before replacing working state.
- Desktop filename search uses a private, rebuildable, metadata-only SQLite index. It does not read file bodies, follow symbolic links, traverse files-on-demand mounts, or send names and queries to a provider or TuxInDrive server. Opening a result rechecks that its live path remains inside the configured synchronization root.
- Search-result preview is default-off and reads only the selected local result after repeating confinement checks. Text/image/archive/output limits, hostile archive rejection, safe XML parsing, and page/time-limited shell-free PDF extraction bound the additional decoder surface.
- The optional server preview is disabled in the client by default. It binds to loopback by default, requires TLS for non-loopback binds, stores only token digests, isolates opaque data and audit records per tenant, applies quotas/expiry/rate limits, and restricts headless job control to the bootstrap `owner` token. Its configuration is root-owned and atomically replaced without following temporary links; request and relay concurrency, deadlines, bandwidth and service resources are bounded. It remains a preview rather than an internet-scale public service.

The detailed control inventory, credential locations, upgrade checklist, dependency response, verification procedure, and operator guidance are maintained in [docs/SECURITY_HARDENING.md](docs/SECURITY_HARDENING.md). Implementation is described in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), operational response in [docs/OPERATIONS.md](docs/OPERATIONS.md), and signing/publication in [docs/RELEASES.md](docs/RELEASES.md).

## Known limitation intentionally retained

TuxInDrive 0.26.24 retains a separate listener and one-key authorization file for every enabled peer. Read-only/receive-only listeners are server read-only; send-only and one-time-drop listeners are rooted in dedicated inboxes. This prevents a modified generic SFTP client from using a role-limited key to browse the containing workspace. One-time-drop byte/file quotas and immediate completed-upload session termination remain defense-in-depth roadmap work.

Do not grant a peer key to an untrusted person under the assumption that the current role label is a hostile-client sandbox. Current per-device roots and server-side authorization reduce role bypass; resource quotas, hostile-client isolation and the future headless peer layer remain separate hardening work.

The server preview is not an internet-scale public service. Bearer-token theft,
traffic metadata, administrator access to the host, unencrypted payloads sent
by a faulty client, and incorrectly configured relay targets remain operator
risks. Remote deployments require a firewall, trusted TLS certificate and
careful token distribution. See [docs/SERVER.md](docs/SERVER.md).

## Release-key operation

Only the public update key is committed. Keep the private key offline or in a protected release environment. Create manifests with `scripts/sign-update.py`; never print the private key in CI logs. Compromise requires a reviewed application release which embeds a replacement public key.

## Release gates

Every release must pass unit tests, source compilation, high-severity Bandit checks, `pip-audit`, Debian installed-layout inspection, signed-manifest verification, and SBOM generation. Security-sensitive path, update, credential, Tor, peer, and recovery changes require regression tests.

Dependency findings must be fixed or explicitly documented with applicability, compensating controls, owner, and expiry. CI ignores are not a substitute for analysis. Ubuntu backported fixes must be verified against Ubuntu package security records rather than guessed from the upstream version alone.
