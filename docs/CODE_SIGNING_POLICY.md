# Code signing policy

Windows installers are currently not Authenticode-signed. Expiring update
manifests are separately signed offline using Ed25519; that is not a native
Windows publisher signature. Current macOS DMGs are ad-hoc signed, not notarized.
The macOS build already requests hardened runtime (`--options runtime`); that
alone does not provide a Developer ID identity or Apple's notarization ticket.

The planned integration is SignPath.io with a certificate from SignPath
Foundation. The Windows approval and signing flow below is the target policy,
not a statement that the integration already operates. Never replace an existing
release's unsigned bytes with signed bytes; publish a higher version instead.

## Opt-in native verification gates

`scripts/verify-native-distribution.py` runs before native build artifacts are
uploaded. It never imports certificates, reads private keys, submits signing
requests or notarizes software. The default mode reports
`pending-not-configured`, not a successful native-signature verification.
Local/development unsigned and ad-hoc builds remain available.

After the protected signing stages described below are actually provisioned,
set these **public repository variables** (they are not private credentials):

- Windows: `TUXINDRIVE_REQUIRE_WINDOWS_SIGNING=1` and
  `TUXINDRIVE_WINDOWS_CERT_SHA256`, the 64-hex SHA-256 of the approved publisher
  certificate. The installer and both TuxInDrive-authored portable entry points
  must have valid, timestamped Authenticode signatures from that certificate.
  Third-party libraries retain their own identities.
- macOS: `TUXINDRIVE_REQUIRE_MACOS_SIGNING=1` and
  `TUXINDRIVE_APPLE_TEAM_ID`, the approved 10-character Apple Team ID. The app,
  password helper and DMG must have valid Developer ID Application signatures;
  executables must retain hardened runtime. The DMG needs a valid stapled
  notarization ticket, and both app and DMG must pass Gatekeeper assessment.

Only `0` (deferred) and `1` (required) are accepted. Required mode fails on absent
identity settings, unsigned/ad-hoc artifacts, wrong identities, missing tickets
or unsuccessful system verification; it never falls back to unsigned output.
Do not enable required mode before connecting a protected signing producer:
the current build jobs intentionally receive no native private credentials.
These gates are preparation, not a claim that production signing is configured
or that its credential-dependent end-to-end path has been tested.

### External provisioning still required

1. **Windows:** obtain SignPath Foundation approval and the actual organization,
   project, artifact-configuration and production-policy identifiers. Configure
   SHA-256 signing, trusted timestamps, GitHub build-origin verification and
   explicit maintainer approval. Add a least-privilege API token only to the
   protected release signing stage. Wire that separate stage to return the
   signed installer and portable files before the verification gate, signing
   our application/helper before embedding them in the installer. No service
   enrollment, token creation or signing request is performed by this change.
2. **Apple:** supply an Apple Developer ID Application certificate **with its
   private key** to an ephemeral protected signing keychain, plus the Team ID.
   Provide approved notarization access (App Store Connect key/issuer/key ID or
   an Apple app-specific-password Keychain profile). Wire a separate protected
   stage to sign the app/helper/DMG, submit with `notarytool`, require `Accepted`,
   and staple the ticket. Delete temporary private material after use. Do not
   pass private keys/passwords through repository variables or committed files.
3. Exercise the real credentialed native builds, verification gates and clean
   installation/launch on their target OS before enabling native publication.
   Generate checksums and Ed25519 update manifests only from the final signed
   bytes, and publish them under a **new version**. Never replace 0.26.81 assets.

References: [Microsoft SignTool](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool),
[Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

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

## Target Windows signing controls

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
