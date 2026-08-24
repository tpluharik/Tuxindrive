# Code signing policy

Free code signing is provided by SignPath.io; the certificate is provided by
SignPath Foundation.

## Scope and official artifacts

Only Windows installers built from the public TuxInDrive repository by the
protected GitHub Actions release workflow are eligible for production signing.
The signed artifact must correspond to an immutable `vMAJOR.MINOR.PATCH` tag and
is published only through the official [TuxInDrive releases](DOWNLOADS.md).
Test builds, local builds, pull-request artifacts, modified upstream programs,
and files supplied outside the verified build workflow are not production
signed.

TuxInDrive is MIT-licensed open-source software. Third-party open-source
components retain their own identities and licenses and are not represented as
TuxInDrive-authored binaries.

## Roles and approval

- **Committer and reviewer:** Tomas Pluharik (`tpluharik`). External changes are
  accepted through pull requests and reviewed before merging.
- **Signing approver:** Tomas Pluharik (`tpluharik`). Every production signing
  request requires explicit manual approval.

Repository and signing-service accounts require multi-factor authentication.
Signing credentials are stored only as protected service secrets and are never
committed, embedded in artifacts, or copied into issue discussions or logs.

## Build and release controls

1. GitHub-hosted runners build the Windows application and installer from the
   tagged public source and pinned workflow actions.
2. Automated tests and packaging checks must succeed before the unsigned
   installer is submitted to SignPath.
3. SignPath verifies the GitHub build origin and applies the production
   Authenticode signature only after the configured approval.
4. The workflow verifies the returned signature and publishes immutable release
   bytes with SHA-256 checksums.
5. Chocolatey and WinGet definitions reference the exact signed GitHub Release
   URL and checksum. Existing release files are not silently replaced.

If a signing key, account, workflow, release artifact, or maintainer identity is
suspected of compromise, publishing stops immediately. Affected releases are
withdrawn where possible, SignPath is notified for investigation or revocation,
and users are informed through a GitHub security advisory or release notice.

## Privacy statement

TuxInDrive does not transfer information to other networked systems unless the
user or system administrator explicitly requests or configures the associated
operation. Network features include user-configured cloud synchronization,
GitHub synchronization, update checks, explicitly enabled peer collaboration,
and optional self-hosted server integration. TuxInDrive operates no advertising,
analytics, tracking, or hosted user-profile service. Provider and platform
privacy terms apply when a user chooses those external services.

Security concerns can be reported privately according to the repository
[security policy](../SECURITY.md).
