# Gmail and Microsoft 365 attachment search

**Introduced in 0.26.71; easier Microsoft setup in 0.26.72 desktop builds.** Live provider authorization and organization
consent still require end-to-end validation; synthetic tests are not evidence
of access to a real mailbox. Android mailbox indexing is not implemented.

## What it does

The search window combines synchronized files with locally indexed Gmail and
Microsoft 365 attachments. Use **Files and mail**, **Synchronized files**, or
**Mail attachments** to choose the search scope. Queries run offline against
the last committed index: typing never contacts a mail service.

By default only attachment names, sizes/types, message subjects, senders,
received timestamps and provider message links are indexed. Email bodies are
not indexed. **Open selected**, double-click, and **Open online location** open
the original email in Gmail/Outlook, where the attachment can be opened or
downloaded. Gmail links use the mailbox address returned by the API rather
than guessing the first signed-in browser account. There is no retained local
attachment directory; **Open local location** explains this for mail results.

Mailbox credentials are separate from Google Drive/OneDrive credentials.
There are no send, edit or delete operations on either mail API.

## Connect a mailbox

1. Open the magnifying glass, then **Mail accounts**.
2. Choose **Connect Gmail** or **Connect Microsoft 365**.
3. Enter a display name and optionally an email login hint. Microsoft 365
   pre-fills the registered TuxInDrive Mail public desktop client; you can use
   your own client/tenant instead. Gmail requires your own Desktop client ID
   and its client secret. Follow the provider setup below.
4. Choose **Open browser and connect** and approve read-only access in the
   system browser. The wizard also provides an authorization-page link if the
   browser did not appear. Authorization expires after three minutes and can
   be cancelled; TuxInDrive never asks for your mailbox password.
5. Select the connected mailbox and choose **Refresh selected mailbox**.

Connecting does not scan mail automatically. Refresh applies the displayed
indexing options and saves them. **Save indexing options** can save options
without contacting the provider. Refresh and disconnect run in the background;
**Stop** or closing the manager cancels refresh at the next cancellation check.
An in-flight network read can take up to its timeout before returning.

### Gmail setup

Enable the Gmail API in your Google Cloud project, configure the OAuth consent
screen, and create a **Desktop app** OAuth client. Enter its client ID and,
if supplied/required, desktop client secret. The requested scope is
`https://www.googleapis.com/auth/gmail.readonly`. The authorization flow uses
PKCE and a random-port loopback callback on `127.0.0.1`.

`gmail.readonly` is a restricted scope. Development apps may need explicitly
listed test users; production distribution can require Google verification and
additional requirements. Workspace administrators can restrict access, and
Testing apps allow only listed test users; Gmail refresh tokens expire after
seven days, requiring reconnection. The maintainer's private Testing client is
not bundled or pre-filled for all users. Do not assume a new client ID is approved
for every user. See [Gmail OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
and [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
including [refresh-token expiry](https://developers.google.com/identity/protocols/oauth2#expiration).

### Gmail rate limits and recovery (0.26.73)

New Google Cloud projects have lower per-user quotas than older projects.
TuxInDrive spaces Gmail API requests by at least half a second and recognizes
`rateLimitExceeded` / `userRateLimitExceeded` HTTP 403 responses as temporary
quota limits, not lost credentials. Recovery waits are bounded and cancellable;
if retries run out, keep the mailbox connected and refresh after a minute.
A daily-quota error needs the quota to reset or a project-quota review, not a
new OAuth login. No quota increase or billing enablement is performed by the app.
See [Gmail usage limits](https://developers.google.com/workspace/gmail/api/reference/quota).
Genuine permission/administrator denials still require their separate recovery.

### Microsoft 365 / Office 365 setup

Version 0.26.72 pre-fills the registered **TuxInDrive Mail** application:
`31a841b0-b4f8-4fea-a2f4-49025a6d7370`, tenant `common`. It supports personal
Microsoft accounts and work/school accounts in any Entra tenant. Its delegated
permissions are only `Mail.Read` and `offline_access`; no tenant-wide admin
consent has been granted. The publisher is not verified, so an organization may
block user consent or require its administrator's approval. Registration is not
evidence of successful live mailbox authorization or indexing. Existing saved
mail accounts are not changed by the pre-filled default.

For your own client, register an application in Microsoft Entra ID with **Mobile and desktop
applications**, redirect URI `http://localhost`, and delegated Microsoft Graph
`Mail.Read` permission. Use an account audience matching your mailbox: a
specific tenant UUID or `organizations` for organizational accounts,
`consumers` for personal accounts, or `common` when the registration supports
both. No Microsoft client secret is entered or stored. PKCE and
`offline_access` support desktop authorization and token renewal.

Your organization may require administrator consent or disallow this app.
Only the signed-in user's mailbox is implemented; shared/delegated mailboxes
and sovereign-cloud endpoints are not. See [Entra application registration](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)
and [Graph attachment permissions](https://learn.microsoft.com/en-us/graph/api/message-list-attachments?view=graph-rest-1.0).

## Optional attachment text

Enable **Download supported attachment contents for text indexing** for each
mailbox. This is separate from **Index local file contents**. Supported text,
PDF and Office formats use the existing bounded extractor; PDF extraction
requires the existing optional `pdftotext` helper. Cached text is previewable
without another download when **Enable preview** is enabled.

Limits per mailbox refresh:

- Default history: 365 days; set 0 for all history.
- Default message scan: 2,000 messages; configurable up to 50,000.
- Index cap: 10,000 attachments per mailbox.
- Content: 8 MiB per attachment, 500 attempts, 64 MiB declared attachment
  payload budget and a separate 64 MiB encoded-response budget. Protocol
  overhead/failures can make fewer files fit these budgets.
- Extracted text: at most 16,000 characters per supported attachment.

Unchanged successfully extracted text is reused across refreshes. This avoids
re-downloading it, but metadata is rescanned: Gmail history/Microsoft delta
checkpoints and automatic scheduling are not implemented. Unsupported or
over-budget content still has searchable metadata. Inline logos, Graph link
attachments and attached email items are excluded. There is no OCR, archive
indexing, or encrypted-document support, and extraction limits are not a
general-purpose malware sandbox.

A failed or cancelled scan retains prior attachment metadata. A limited scan
keeps unseen older results; a complete scan removes stale entries from the
selected mailbox's scanned scope. Reduce the history window only if pruning
older indexed entries is intended. Results may remain stale until a complete
refresh. The status reports counts, limits and reused/skipped text rather than
claiming an exact mailbox-wide completion percentage.

## Privacy and removal

OAuth tokens and the optional Google desktop secret live only in the native
credential store: Linux Secret Service (`secret-tool`), Windows Credential
Manager, or macOS Keychain. There is no plaintext credential fallback. Unlock
the desktop credential store before connecting. Tokens are not written into
account JSON, the search index, logs, or profile exports.

Non-secret settings are saved in `config_root()/mail-accounts.json`; metadata
and opt-in text are in `cache_root()/mail-search.sqlite3`. These use private
POSIX permissions where supported, but **the SQLite search cache is not
encrypted**. Mail subjects, senders and extracted text are sensitive: use disk
encryption and protect backups. Raw attachments use temporary private files
only during extraction and are removed afterwards; this is not secure erasure.

Disabling content and saving/refreshing removes that mailbox's searchable
cached text immediately without deleting metadata. Managed
`allow_content_indexing=false` prevents mail-content downloads and removes
cached mail text at application startup. SQLite/WAL and backup remnants are
not guaranteed to be securely erased.

**Disconnect and remove local index** removes the saved account, local native
credential and its indexed entries. Remote emails/attachments are unchanged;
revoke provider-side app consent separately if desired. If authorization was
revoked or expired, disconnect and connect again with the same registered app,
then refresh. Account/index mutations refuse to overlap a running refresh.

This feature is attachment discovery, not a full mailbox backup or mail client.
