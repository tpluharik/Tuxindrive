# Contributing to TuxInDrive

Thank you for helping improve TuxInDrive. The repository is publicly readable, while direct writes to the main repository remain restricted to maintainers. Public contributions should use GitHub Issues or pull requests.

## Ways to contribute

- Report a reproducible bug with the **Bug report** issue form.
- Suggest a feature or workflow improvement with the **Feature request** form.
- Comment on an existing issue to add evidence, logs, testing results, or design feedback.
- Fork the repository and open a pull request with an implementation.
- Improve user documentation, packaging, accessibility, or translations.
- Review or refine the [top-40 feature roadmap](docs/ROADMAP.md).
- Review the [architecture](docs/ARCHITECTURE.md), [configuration contract](docs/CONFIGURATION.md), or [operations guide](docs/OPERATIONS.md) for implementation/documentation drift.

## Before reporting a bug

1. Install the newest `.deb` from the repository.
2. Check the [illustrated user guide](docs/USER_GUIDE.md) and existing issues.
3. Reproduce the problem once with the live activity log open.
4. Remove passwords, OAuth tokens, client secrets, private URLs, personal file names, and confidential cloud content from screenshots and logs.

Useful diagnostics:

```bash
tuxindrive --diagnostics
tail -n 150 ~/.local/state/tuxindrive/tuxindrive.log
tail -n 150 ~/.local/state/tuxindrive/crash.log
tail -n 150 ~/.cache/tuxindrive/logs/*.log
```

## Development workflow

1. Fork `tpluharik/TuxInDrive`.
2. Create a focused branch from `main`.
3. Make a small, reviewable change.
4. Add or update tests for behaviour changes.
5. Run:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src
```

6. Update documentation when controls, configuration, packaging, or user-visible behaviour changes.
7. Open a pull request and complete the checklist.

The [testing guide](docs/TESTING.md) describes the current 386-test Python suite plus Android release tasks, the release matrix, safety invariants and known coverage gaps. Recovery, integrity, mass-change, conflict-resolution, peer authorization, lease, discovery, Nautilus, streaming-mount, provider-URL, bandwidth/admission, server, encryption, or local-index changes must include focused safety tests and document trust, expiry, authoritative-side, privacy, tenant, resource-bound, and rollback behavior.

## Pull-request expectations

- Explain the user problem and the proposed behaviour.
- Keep unrelated changes out of the pull request.
- Preserve existing configuration compatibility.
- Do not commit OAuth tokens, rclone configuration, credentials, real user logs, or personal paths.
- Run `bandit -q -r src -lll` and `pip-audit -r requirements-security.txt` for security-sensitive or dependency changes. Never suppress an advisory solely to pass CI; explain applicability, compensating controls, expiry, and the planned fixed version in `SECURITY.md`.
- Update `CHANGELOG.md`, `README.md`, `docs/USER_GUIDE.md`, `docs/TESTING.md`, `docs/ROADMAP.md`, and `docs/SECURITY_HARDENING.md` when a release changes security behavior, dependency floors, credential storage, protocol fields, recovery semantics, or trust boundaries.
- Update `docs/ARCHITECTURE.md` and `docs/CONFIGURATION.md` when components, data flow, or persisted fields change; update `docs/OPERATIONS.md` and `docs/RELEASES.md` when failure recovery, packaging, signing, or update channels change.
- Keep current-version claims synchronized across `README.md`, `SECURITY.md`, the documentation index, platform support, test counts, release pointers and signed manifests. Historical changelog entries must remain historical rather than being mechanically rewritten.
- New untrusted paths, archives, update metadata, peer instructions, or recovery operations require negative tests for traversal, symlink races, resource exhaustion, tampering, and unauthorized signers.
- Treat synchronization and deletion changes as safety-sensitive. Describe failure and recovery behaviour.
- Maintain support for Ubuntu 26.04, Google Drive, and Microsoft OneDrive.
- Use public provider APIs and compatible open-source components; do not copy proprietary client code or branding.

Maintainers may request changes, close incomplete proposals, or decline features that create unacceptable data-loss, privacy, security, or maintenance risk.

## Community conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Be specific, constructive, and respectful.
