# TuxInDrive documentation

- [Official downloads](DOWNLOADS.md)
- [Code signing policy](CODE_SIGNING_POLICY.md)

<p align="center"><img src="../branding/tuxindrive-logo.png" width="140" alt="TuxInDrive circular penguin logo with a red bow tie"></p>

This index separates end-user instructions, operator guidance, implementation
details, security controls, and release procedures. Documentation describes
TuxInDrive 0.26.31 unless a section is explicitly historical. Release-specific
facts are identified by version; planned work is never described as shipped.

## Start here

| Audience | Document | Contents |
|---|---|---|
| Everyone | [Repository overview](../README.md) | Product scope, feature summary, installation, supported platforms and project links. |
| Users | [User guide](USER_GUIDE.md) | Accounts, folders, synchronization, streaming, peer sharing, recovery, mobile use and troubleshooting. |
| Administrators | [Operations guide](OPERATIONS.md) | State locations, bandwidth policy, health checks, logs, backup, recovery and incident handling. |
| Developers | [Architecture](ARCHITECTURE.md) | Components, threads, data flows, synchronization engine, Android implementation and module map. |
| Developers and administrators | [Configuration reference](CONFIGURATION.md) | Configuration file, every persisted setting/job field, environment integration and compatibility rules. |
| Maintainers | [Testing](TESTING.md) | Automated suite, safety invariants, manual test matrix and coverage limits. |
| Maintainers | [Release process](RELEASES.md) | Versioning, native builds, signed update channels, artifacts, validation and rollback. |
| Distribution maintainers | [Marketplace distribution](MARKETPLACE_DISTRIBUTION.md) | Generated package-manager inputs and the account-owner hand-off. |
| Security reviewers | [Security hardening](SECURITY_HARDENING.md) | Trust boundaries, credential storage, update verification and residual risk. |
| Platform users | [Platform support](PLATFORM_SUPPORT.md) | Linux, Windows, macOS and Android differences and requirements. |
| Server operators | [Server preview](SERVER.md) | Headless roles, `.deb` installation, API, client feature flag, quotas, TLS and limitations. |
| Testers and maintainers | [Network Lab](NETWORK_LAB.md) | Separate loopback-only server/client scenario application, fictional data, logs and release channel. |
| Contributors | [Contributing](../CONTRIBUTING.md) | Development workflow and pull-request expectations. |
| Release users | [Platform channels](../releases/README.md) | Stable updater manifests and durable installer locations. |
| Community maintainers | [0.26.31 media kit](ANNOUNCEMENT_0.26.31.md) | Verified release facts, social drafts, visual asset and answers to common questions. |

## Feature and history references

- [Roadmap](ROADMAP.md) — implemented and planned work.
- [Changelog](../CHANGELOG.md) — release-by-release history.
- [Security policy](../SECURITY.md) — supported releases and private vulnerability reporting.
- [Release channel layout](../releases/README.md) — durable package and manifest locations.
- [0.26.31 media kit](ANNOUNCEMENT_0.26.31.md) — current factual, reusable community-release text.
- [0.26.23 announcement notes](ANNOUNCEMENT_0.26.23.md) — archived search-release text.

## Documentation conventions

- **Local** means the device running TuxInDrive.
- **Remote** means an rclone-backed cloud, a Git repository, Proton Drive, or
  an authenticated TuxInDrive peer, depending on the job.
- **Streaming drive** means an rclone VFS mount whose directory metadata is
  visible before file content is downloaded.
- **Incremental synchronization** means callback-triggered changed-path work;
  **reconciliation** means a safety scan that re-establishes complete state.
- Commands assume the repository root unless stated otherwise.

Documentation changes are release work. A feature is not complete until its
user behavior, configuration, security implications, tests, and operational
failure modes are reflected in the appropriate documents above.

When documents disagree, the signed manifest and immutable package describe
what can be installed, the configuration reference describes persisted state,
and the security policy defines the supported trust boundary. Report drift as
a documentation bug rather than relying on an older screenshot or Actions
artifact.
