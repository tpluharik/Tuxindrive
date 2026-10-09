from tests import signal_safety as _signal_safety  # noqa: F401

import base64
import io
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request

from tuxindrive.mail_auth import (
    GMAIL_SCOPE, GRAPH_SCOPE, MICROSOFT_MAIL_CLIENT_ID, MailAccount, MailAccountStore, MailAuthorization,
    MailCancelled, MailError, MailTokenStore, NoRedirect, authorization_parameters,
    _grant, default_mail_client_id, http_bytes, valid_callback,
)
from tuxindrive.mail_connectors import MailAttachment, MailClient, MailScan, _gmail_fields, safe_message_url
from tuxindrive.mail_index import MailSearchIndex


GMAIL = MailAccount("a" * 32, "gmail", "Personal mail", "desktop.apps.googleusercontent.com")
MICROSOFT = MailAccount("b" * 32, "microsoft365", "Work mail", "00000000-0000-0000-0000-000000000001")


def attachment(account=GMAIL, **changes):
    values = dict(account_id=account.id, provider=account.provider, account_name=account.display_name,
                  message_id="message-one", attachment_id="attachment-one", name="invoice.txt",
                  subject="October invoice", sender="supplier@example.invalid", received="2026-10-08T09:00:00Z",
                  size=14, mime_type="text/plain", message_url=("https://mail.google.com/mail/u/0/#all/thread-one"
                  if account.provider == "gmail" else "https://outlook.office.com/mail/inbox/id/one"))
    values.update(changes)
    return MailAttachment(**values)


class SyntheticClient:
    def __init__(self, account=GMAIL, items=None, *, complete=True, data=b"private needle"):
        self.account = account
        self.items = [attachment(account)] if items is None else items
        self.complete, self.data, self.downloads = complete, data, 0

    def scan(self, progress=None):
        if progress:
            progress(len(self.items), self.account.max_messages, len(self.items))
        return MailScan(tuple(self.items), len(self.items), self.complete)

    def download(self, _item):
        self.downloads += 1
        return self.data


class MailAuthorizationTests(unittest.TestCase):
    @staticmethod
    def gmail_error(reason):
        body = {"error": {"errors": [{"reason": reason}], "message": "synthetic-private-response"}}
        return HTTPError("https://gmail.googleapis.com/test", 403, "Forbidden", {},
                         io.BytesIO(json.dumps(body).encode()))

    def test_gmail_quota_403_waits_and_retries_without_reauthorization(self):
        opener, stop = Mock(), Mock()
        stop.is_set.return_value = False
        opener.open.side_effect = [self.gmail_error("rateLimitExceeded"), io.BytesIO(b"ok")]
        with patch("tuxindrive.mail_auth.build_opener", return_value=opener):
            self.assertEqual(http_bytes(Request("https://gmail.googleapis.com/test"), 4, stop=stop), b"ok")
        stop.wait.assert_called_once_with(32)
        self.assertEqual(opener.open.call_count, 2)

    def test_gmail_quota_exhaustion_is_not_reported_as_lost_permissions(self):
        for reason in ("rateLimitExceeded", "userRateLimitExceeded"):
            opener = Mock()
            opener.open.side_effect = self.gmail_error(reason)
            with patch("tuxindrive.mail_auth.build_opener", return_value=opener), self.assertRaises(MailError) as error:
                http_bytes(Request("https://gmail.googleapis.com/test"), 4, retries=1)
            self.assertIn("rate limit", str(error.exception))
            self.assertIn("remains connected", str(error.exception))
            self.assertNotIn("permissions", str(error.exception))
            self.assertNotIn("synthetic-private-response", str(error.exception))

    def test_gmail_daily_quota_and_real_permission_denial_are_not_retried(self):
        for reason, expected in (("dailyLimitExceeded", "daily API quota"), ("insufficientPermissions", "permissions")):
            opener, stop = Mock(), Mock()
            stop.is_set.return_value = False
            opener.open.side_effect = self.gmail_error(reason)
            with patch("tuxindrive.mail_auth.build_opener", return_value=opener), self.assertRaises(MailError) as error:
                http_bytes(Request("https://gmail.googleapis.com/test"), 4, stop=stop)
            self.assertIn(expected, str(error.exception))
            self.assertEqual(opener.open.call_count, 1)
            stop.wait.assert_not_called()

    def test_gmail_quota_wait_is_cancellable_before_another_request(self):
        opener, stop = Mock(), Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = lambda _delay: setattr(stop.is_set, "return_value", True)
        opener.open.side_effect = self.gmail_error("rateLimitExceeded")
        with patch("tuxindrive.mail_auth.build_opener", return_value=opener), self.assertRaises(MailCancelled):
            http_bytes(Request("https://gmail.googleapis.com/test"), 4, stop=stop)
        self.assertEqual(opener.open.call_count, 1)

    def test_only_microsoft_has_a_public_default_client(self):
        self.assertEqual(default_mail_client_id("microsoft365"), MICROSOFT_MAIL_CLIENT_ID)
        self.assertEqual(MICROSOFT_MAIL_CLIENT_ID, "31a841b0-b4f8-4fea-a2f4-49025a6d7370")
        self.assertEqual(default_mail_client_id("gmail"), "")
        self.assertEqual(default_mail_client_id("unknown"), "")

    def test_registered_microsoft_client_preserves_read_only_pkce_consent(self):
        account = replace(MICROSOFT, client_id=default_mail_client_id("microsoft365"))
        url, fields = authorization_parameters(account, "http://localhost:55555/", "state", "verifier")
        self.assertEqual(url, "https://login.microsoftonline.com/common/oauth2/v2.0/authorize")
        self.assertEqual(fields["client_id"], MICROSOFT_MAIL_CLIENT_ID)
        self.assertEqual(fields["scope"], GRAPH_SCOPE + " offline_access")
        self.assertEqual(fields["code_challenge_method"], "S256")
        self.assertNotIn("client_secret", fields)

    def test_accounts_round_trip_without_tokens_and_with_private_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mail-accounts.json"
            store = MailAccountStore(path)
            store.save([GMAIL, MICROSOFT])
            self.assertEqual(store.load(), [GMAIL, MICROSOFT])
            self.assertNotIn("access_token", path.read_text())
            self.assertNotIn("client_secret", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_reserved_account_ids_and_untrusted_tenants_are_rejected(self):
        for item in (replace(GMAIL, id="../token"), replace(MICROSOFT, tenant="evil.invalid/other"),
                     replace(GMAIL, days=True), replace(GMAIL, max_messages=0),
                     replace(GMAIL, client_id=""), replace(GMAIL, include_content="yes"),
                     replace(GMAIL, client_id=None), replace(GMAIL, display_name=[])):
            with self.subTest(item=item), self.assertRaises(MailError):
                item.validate()

    def test_authorization_is_read_only_pkce_and_provider_specific(self):
        for account in (GMAIL, MICROSOFT):
            url, fields = authorization_parameters(account, "http://localhost:55555/", "state", "verifier")
            self.assertTrue(url.startswith("https://"))
            self.assertEqual(fields["code_challenge_method"], "S256")
            self.assertNotEqual(fields["code_challenge"], "verifier")
            self.assertNotIn("ReadWrite", fields["scope"])
            self.assertNotIn("send", fields["scope"])
            self.assertIn(GMAIL_SCOPE if account.provider == "gmail" else GRAPH_SCOPE, fields["scope"])
            self.assertNotIn("client_secret", fields)

    def test_oauth_callback_requires_single_exact_state_and_root_path(self):
        self.assertEqual(valid_callback("/?" + urlencode({"state": "good", "code": "code"}), "good"), "code")
        for path in ("/?state=bad&code=code", "/other?state=good&code=code",
                     "/?state=good&state=good&code=code", "/?state=good&code=x&code=y",
                     "https://evil.invalid/?state=good&code=x", "/?state=%C4%8D&code=x"):
            self.assertIsNone(valid_callback(path, "good"))
        with self.assertRaises(MailError):
            valid_callback("/?state=good&error=access_denied", "good")

    @patch("tuxindrive.mail_auth.run_process")
    def test_linux_native_store_passes_secret_only_via_stdin(self, run):
        run.return_value = Mock(returncode=0, stdout="", stderr="")
        with patch("tuxindrive.mail_auth.sys.platform", "linux"):
            MailTokenStore().store(GMAIL, {"refresh_token": "synthetic-secret"})
        args, kwargs = run.call_args
        self.assertNotIn("synthetic-secret", repr(args))
        self.assertIn("synthetic-secret", kwargs["input"])
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(args[0][0], "/usr/bin/secret-tool")

    def test_refresh_rotation_preserves_existing_refresh_token_and_caches_access(self):
        store = Mock()
        store.load.return_value = {"access_token": "old", "refresh_token": "refresh", "expires_at": 0,
                                   "client_secret": "desktop-secret"}
        authorization = MailAuthorization(store)
        grant = {"access_token": "new", "refresh_token": "", "expires_at": time.time() + 3600}
        with patch("tuxindrive.mail_auth._grant", return_value=grant) as renew:
            self.assertEqual(authorization.access_token(GMAIL), "new")
            self.assertEqual(authorization.access_token(GMAIL), "new")
        self.assertEqual(renew.call_count, 1)
        self.assertEqual(store.load.call_count, 1)
        saved = store.store.call_args.args[1]
        self.assertEqual(saved["refresh_token"], "refresh")
        self.assertEqual(saved["client_secret"], "desktop-secret")

    def test_redirects_and_oversized_responses_fail_closed(self):
        with self.assertRaises(MailError):
            NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://evil.invalid")
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"12345")
        with patch("tuxindrive.mail_auth.build_opener", return_value=opener), self.assertRaises(MailError):
            http_bytes(Request("https://gmail.googleapis.com/test"), 4)
        with self.assertRaises(MailError):
            http_bytes(Request("https://evil.invalid/test"), 4)

    def test_token_exchange_is_bounded_https_and_rejects_malformed_credentials(self):
        payload = {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh", "expires_in": 3600}
        with patch("tuxindrive.mail_auth.http_bytes", return_value=json.dumps(payload).encode()) as network:
            result = _grant(GMAIL, {"grant_type": "authorization_code", "code": "synthetic-code", "code_verifier": "proof"})
            self.assertEqual(result["refresh_token"], "synthetic-refresh")
            request = network.call_args.args[0]
            self.assertEqual(request.full_url, "https://oauth2.googleapis.com/token")
            self.assertEqual(request.get_method(), "POST")
            self.assertIn(b"code_verifier=proof", request.data)
            self.assertEqual(network.call_args.kwargs["retries"], 1)
        for changes in ({"access_token": "line\nbreak"}, {"refresh_token": []}, {"expires_in": float("inf")}):
            invalid = dict(payload, **changes)
            with patch("tuxindrive.mail_auth.http_bytes", return_value=json.dumps(invalid).encode()), self.assertRaises(MailError):
                _grant(GMAIL, {})

    def test_native_store_rejects_plaintext_backends_and_redacts_backend_errors(self):
        plaintext = SimpleNamespace()
        keyring = SimpleNamespace(get_keyring=lambda: plaintext)
        with patch.dict("sys.modules", {"keyring": keyring}), self.assertRaises(MailError):
            MailTokenStore._keyring()
        class Native:
            def get_password(self, *_args):
                raise RuntimeError("synthetic-private-credential")
        Native.__module__ = "keyring.backends.macOS"
        keyring = SimpleNamespace(get_keyring=lambda: Native())
        with patch.dict("sys.modules", {"keyring": keyring}), patch("tuxindrive.mail_auth.sys.platform", "darwin"):
            with self.assertRaises(MailError) as captured:
                MailTokenStore().load(GMAIL)
        self.assertNotIn("synthetic-private-credential", str(captured.exception))


class MailConnectorTests(unittest.TestCase):
    def test_gmail_requests_are_paced_and_microsoft_requests_are_not(self):
        authorization, stop = Mock(), Mock()
        authorization.access_token.return_value = "synthetic-token"
        stop.is_set.return_value = False
        client = MailClient(GMAIL, authorization, stop=stop)
        with patch("tuxindrive.mail_connectors.time.monotonic", side_effect=[100, 100, 100, 100.5]), \
                patch("tuxindrive.mail_connectors.http_bytes", return_value=b"{}"):
            client._request(client.base + "profile")
            client._request(client.base + "messages")
        stop.wait.assert_called_once_with(0.5)
        stop.reset_mock()
        client = MailClient(MICROSOFT, authorization, stop=stop)
        with patch("tuxindrive.mail_connectors.http_bytes", return_value=b"{}"):
            client._request(client.base + "messages")
            client._request(client.base + "messages")
        stop.wait.assert_not_called()

    def test_gmail_pacing_can_be_cancelled_without_another_network_read(self):
        authorization, stop = Mock(), Mock()
        authorization.access_token.return_value = "synthetic-token"
        stop.is_set.return_value = False
        stop.wait.side_effect = lambda _delay: setattr(stop.is_set, "return_value", True)
        client = MailClient(GMAIL, authorization, stop=stop)
        client._next_gmail_request = 101
        with patch("tuxindrive.mail_connectors.time.monotonic", return_value=100), \
                patch("tuxindrive.mail_connectors.http_bytes") as network, self.assertRaises(MailCancelled):
            client._request(client.base + "messages")
        network.assert_not_called()
        authorization.access_token.assert_not_called()

    def test_gmail_metadata_projection_excludes_body_data(self):
        self.assertNotIn("data", _gmail_fields())
        self.assertIn("data", _gmail_fields(content=True))
        client = MailClient(GMAIL, Mock())
        message = {"id": "one", "threadId": "thread", "internalDate": "1234567890000", "payload": {
            "mimeType": "multipart/mixed", "headers": [{"name": "Subject", "value": "Bill"}],
            "parts": [{"partId": "1", "filename": "invoice.pdf", "mimeType": "application/pdf",
                       "body": {"attachmentId": "file", "size": 5}},
                      {"partId": "2", "filename": "logo.png", "headers": [{"name": "Content-Disposition", "value": "inline"}],
                       "body": {"attachmentId": "logo", "size": 10}}]}}
        with patch.object(client, "_json", side_effect=[{"emailAddress": "actual@example.invalid"},
                          {"messages": [{"id": "one"}]}, message]) as request:
            scan = client.scan()
        self.assertEqual([a.name for a in scan.attachments], ["invoice.pdf"])
        self.assertTrue(scan.complete)
        self.assertIn("has:attachment", request.call_args_list[1].kwargs["params"]["q"])
        self.assertNotIn("data", request.call_args_list[2].kwargs["params"]["fields"])
        self.assertIn("authuser=actual%40example.invalid", scan.attachments[0].message_url)

    def test_graph_metadata_excludes_body_and_file_content_and_uses_immutable_ids(self):
        authorization = Mock()
        authorization.access_token.return_value = "synthetic-token"
        client = MailClient(MICROSOFT, authorization)
        message = {"id": "one", "subject": "Bill", "from": {"emailAddress": {"address": "x@example.invalid"}},
                   "webLink": "https://outlook.office.com/mail/inbox/id/one", "changeKey": "revision"}
        files = {"value": [{"@odata.type": "#microsoft.graph.fileAttachment", "id": "file", "name": "bill.txt", "size": 4},
                           {"@odata.type": "#microsoft.graph.referenceAttachment", "id": "link", "name": "Cloud link"},
                           {"@odata.type": "#microsoft.graph.fileAttachment", "id": "logo", "isInline": True}]}
        with patch.object(client, "_json", side_effect=[{"value": [message]}, files]) as request:
            scan = client.scan()
        self.assertEqual([a.name for a in scan.attachments], ["bill.txt"])
        self.assertEqual(scan.attachments[0].revision, "revision")
        self.assertNotIn("body", request.call_args_list[0].args[0])
        self.assertNotIn("contentBytes", request.call_args_list[1].args[0])
        with patch("tuxindrive.mail_connectors.http_bytes", return_value=b"{}") as network:
            client._request(client.base + "messages")
        self.assertEqual(network.call_args.args[0].get_header("Prefer"), 'IdType="ImmutableId"')

    def test_graph_continuation_cannot_forward_token_to_another_origin(self):
        authorization = Mock()
        client = MailClient(MICROSOFT, authorization)
        with self.assertRaises(MailError):
            client._request("https://evil.invalid/v1.0/me/messages")
        authorization.access_token.assert_not_called()
        authorization.access_token.return_value = "synthetic"
        page = json.dumps({"value": [], "@odata.nextLink": "https://evil.invalid/v1.0/me/messages"}).encode()
        with patch("tuxindrive.mail_connectors.http_bytes", return_value=page) as network:
            with self.assertRaises(MailError):
                client.scan()
        self.assertEqual(network.call_count, 1)
        self.assertEqual(authorization.access_token.call_count, 1)

    def test_repeated_gmail_continuations_are_rejected(self):
        client = MailClient(GMAIL, Mock())
        def page(path, **_kwargs):
            return {"emailAddress": "actual@example.invalid"} if path == "profile" else {"nextPageToken": "repeat"}
        with patch.object(client, "_json", side_effect=page), self.assertRaises(MailError):
            client.scan()

    def test_gmail_requires_verified_mailbox_identity_before_building_links(self):
        client = MailClient(GMAIL, Mock())
        with patch.object(client, "_json", return_value={}), self.assertRaises(MailError):
            client.scan()

    def test_wire_content_budget_includes_encoded_response_overhead(self):
        authorization = Mock()
        authorization.access_token.return_value = "synthetic"
        client = MailClient(GMAIL, authorization)
        client.content_bytes_remaining = 5
        with patch("tuxindrive.mail_connectors.http_bytes", return_value=b"12345") as network:
            client._request(client.base + "messages/one/attachments/file", attachment=True, limit=10)
            self.assertEqual(network.call_args.args[1], 5)
            self.assertEqual(network.call_args.kwargs["retries"], 1)
            with self.assertRaises(MailError):
                client._request(client.base + "messages/one/attachments/other", attachment=True)
            self.assertEqual(network.call_count, 1)
        self.assertEqual(client.content_bytes_remaining, 0)

    def test_graph_missing_collection_is_not_an_empty_successful_scan(self):
        client = MailClient(MICROSOFT, Mock())
        with patch.object(client, "_json", return_value={"unexpected": []}), self.assertRaises(MailError):
            client.scan()

    def test_attachment_download_decodes_base64_and_checks_declared_size(self):
        client = MailClient(GMAIL, Mock())
        item = attachment(size=3)
        with patch.object(client, "_json", return_value={"data": base64.urlsafe_b64encode(b"abc").decode().rstrip("=")}):
            self.assertEqual(client.download(item), b"abc")
            with self.assertRaises(MailError):
                client.download(replace(item, size=4))

    def test_cross_account_and_oversized_downloads_are_rejected_before_network(self):
        client = MailClient(GMAIL, Mock())
        with patch.object(client, "_json") as request:
            for item in (attachment(MICROSOFT), attachment(size=8 * 1024 * 1024 + 1)):
                with self.assertRaises(MailError):
                    client.download(item)
            request.assert_not_called()

    def test_message_links_reject_custom_schemes_and_untrusted_hosts(self):
        for url in ("file:///etc/passwd", "https://evil.invalid/", "https://mail.google.com.evil.invalid/",
                    "https://user:password@mail.google.com/", "https://mail.google.com:444/"):
            with self.assertRaises(MailError):
                safe_message_url(url, "gmail")
        self.assertEqual(safe_message_url(attachment().message_url, "gmail"), attachment().message_url)


class MailIndexTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.index = MailSearchIndex(Path(self.temporary.name) / "mail.sqlite3")

    def test_account_menu_search_is_scoped_and_parameterized(self):
        self.index.refresh(GMAIL, SyntheticClient())
        self.index.refresh(MICROSOFT, SyntheticClient(MICROSOFT))
        self.assertEqual(len(self.index.search("invoice")), 2)
        results = self.index.search("invoice", account_id=GMAIL.id)
        self.assertEqual([item.attachment.account_id for item in results], [GMAIL.id])
        self.assertEqual(self.index.search("invoice", account_id="' OR 1=1 --"), [])

    def test_metadata_only_searches_filename_subject_and_sender_without_downloads(self):
        client = SyntheticClient()
        result = self.index.refresh(GMAIL, client)
        self.assertEqual(result.indexed, 1)
        self.assertEqual(client.downloads, 0)
        for query in ("invoice", "October", "supplier@example.invalid"):
            self.assertEqual(len(self.index.search(query)), 1)
        self.assertEqual(self.index.search("private needle"), [])
        self.assertEqual(self.index.path.stat().st_mode & 0o777, 0o600)

    def test_content_is_explicitly_opt_in_and_reused_when_unchanged(self):
        account = replace(GMAIL, include_content=True)
        client = SyntheticClient(account)
        first = self.index.refresh(account, client)
        second = self.index.refresh(account, client)
        self.assertEqual((first.downloaded, second.reused, client.downloads), (1, 1, 1))
        result = self.index.search("private needle")[0]
        self.assertTrue(result.matched_content)
        self.assertEqual(result.indexed_text, "private needle")
        client.items = [replace(client.items[0], revision="unicode-expansion")]
        with patch("tuxindrive.mail_index.index_text_path", return_value="\ufb03" * 16000):
            self.index.refresh(account, client)
        self.assertEqual(len(self.index.search("ffi")[0].indexed_text), 16000)

    def test_revision_change_reindexes_same_named_same_sized_attachment(self):
        account = replace(GMAIL, include_content=True)
        client = SyntheticClient(account)
        self.index.refresh(account, client)
        client.items = [replace(client.items[0], revision="new")]
        client.data = b"updated needle"
        self.index.refresh(account, client)
        self.assertEqual(client.downloads, 2)
        self.assertEqual(self.index.search("private"), [])
        self.assertEqual(len(self.index.search("updated")), 1)

    def test_disabling_content_removes_text_but_keeps_attachment_metadata(self):
        account = replace(GMAIL, include_content=True)
        self.index.refresh(account, SyntheticClient(account))
        self.index.clear_contents(account.id)
        self.assertEqual(self.index.search("needle"), [])
        self.assertEqual(len(self.index.search("invoice")), 1)

    def test_partial_scan_keeps_old_rows_and_full_scan_removes_stale_rows(self):
        self.index.refresh(GMAIL, SyntheticClient())
        partial = self.index.refresh(GMAIL, SyntheticClient(items=[], complete=False))
        self.assertFalse(partial.complete)
        self.assertEqual(self.index.count(), 1)
        complete = self.index.refresh(GMAIL, SyntheticClient(items=[]))
        self.assertEqual(complete.removed, 1)
        self.assertEqual(self.index.count(), 0)

    def test_failure_or_cancellation_retains_previous_metadata(self):
        self.index.refresh(GMAIL, SyntheticClient())
        client = SyntheticClient()
        with patch.object(client, "scan", side_effect=MailError("synthetic failure")), self.assertRaises(MailError):
            self.index.refresh(GMAIL, client)
        stop = Event()
        stop.set()
        with self.assertRaises(MailCancelled):
            self.index.refresh(GMAIL, SyntheticClient(items=[]), stop_event=stop)
        self.assertEqual(self.index.count(), 1)

    def test_search_wildcards_are_literals_and_unicode_is_normalized(self):
        self.index.refresh(GMAIL, SyntheticClient(items=[attachment(name="Daňový_doklad.txt")]))
        self.assertEqual(len(self.index.search("DAŇOVÝ_doklad")), 1)
        self.assertEqual(self.index.search("%"), [])
        self.assertEqual(self.index.search("nonexistent_"), [])

    def test_same_filename_in_different_accounts_stays_separate(self):
        self.index.refresh(GMAIL, SyntheticClient())
        self.index.refresh(MICROSOFT, SyntheticClient(MICROSOFT))
        self.assertEqual(len(self.index.search("invoice")), 2)
        self.index.remove_account(GMAIL.id)
        self.assertEqual(self.index.count(), 1)
        self.assertEqual(self.index.search("invoice")[0].attachment.account_id, MICROSOFT.id)

    def test_download_budget_skips_content_without_losing_metadata(self):
        account = replace(GMAIL, include_content=True)
        items = [attachment(attachment_id="one", size=3), attachment(attachment_id="two", size=3)]
        client = SyntheticClient(account, items=items, data=b"abc")
        with patch("tuxindrive.mail_index.MAX_DOWNLOAD_BYTES_PER_REFRESH", 5):
            result = self.index.refresh(account, client)
        self.assertEqual((result.downloaded, result.content_skipped, self.index.count()), (1, 1, 2))

    def test_executables_and_path_traversal_are_never_materialized(self):
        account = replace(GMAIL, include_content=True)
        client = SyntheticClient(account, items=[attachment(name="../../malicious.exe")])
        self.index.refresh(account, client)
        self.assertEqual(client.downloads, 0)
        client.items = [attachment(name="../../safe.txt")]
        with patch("tuxindrive.mail_index.index_text_path", return_value="needle") as extract:
            self.index.refresh(account, client)
        selected = extract.call_args.args[0]
        self.assertEqual(selected.name, "attachment.txt")
        self.assertFalse(selected.exists())

    def test_search_is_cancelable_and_refreshes_are_serialized(self):
        stop = Event()
        stop.set()
        self.assertEqual(self.index.search("invoice", stop_event=stop), [])
        acquired, release = Event(), Event()
        def hold_lock():
            with self.index.refresh_lock:
                acquired.set()
                release.wait(5)
        worker = Thread(target=hold_lock, daemon=True)
        worker.start()
        self.assertTrue(acquired.wait(2))
        try:
            with self.assertRaises(MailError):
                self.index.refresh(GMAIL, SyntheticClient())
            with self.assertRaises(MailError):
                self.index.remove_account(GMAIL.id)
            with self.assertRaises(MailError):
                self.index.clear_contents(GMAIL.id)
        finally:
            release.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_managed_policy_can_disable_mail_text_independently_of_account_opt_in(self):
        account = replace(GMAIL, include_content=True)
        client = SyntheticClient(account)
        self.index.refresh(account, client, include_content=False)
        self.assertEqual(client.downloads, 0)


class MailSearchUITests(unittest.TestCase):
    def test_ui_has_explicit_consent_manual_refresh_and_unified_search(self):
        source = (Path(__file__).resolve().parents[1] / "src/tuxindrive/app.py").read_text()
        manager = source[source.index("class MailAccountsDialog"):source.index("class FolderSearchDialog")]
        search = source[source.index("class FolderSearchDialog"):source.index("class CloudTransferDialog")]
        self.assertIn("Refresh selected mailbox", manager)
        self.assertIn("Disconnect and remove local index", manager)
        self.assertIn("self._stop.set()", manager)
        self.assertIn("mail_search_index.search(", search)
        self.assertIn("query, stop_event=cancel, account_id=self.mail_account_id", search)
        self.assertIn("safe_message_url(result.attachment.message_url", search)
        self.assertIn("cancel is not self._query_cancel", search)
        self.assertIn("account = self._persist_options(account)", manager)
        self.assertIn("with self.controller.mail_search_index.maintenance():", manager)

    def test_mail_accounts_are_added_from_main_picker_not_as_drive_remotes(self):
        source = (Path(__file__).resolve().parents[1] / "src/tuxindrive/app.py").read_text()
        chooser = source[source.index("    def _choose_provider"):source.index("    def _configure_github")]
        self.assertIn("for provider in MailProvider", chooser)
        self.assertIn("isinstance(provider, MailProvider)", chooser)
        self.assertIn("MailConnectDialog(self, self.controller, provider.value", chooser)
        mail_row = source[source.index("    def _mail_account_row"):source.index("    @staticmethod\n    def _account_drag_targets")]
        self.assertNotIn("rclone", mail_row)
        self.assertNotIn("add_job", mail_row)
        self.assertIn("existing=account", mail_row)

    def test_store_updates_preserve_other_accounts_and_reject_disconnected_reconnect(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = MailAccountStore(Path(temporary) / "mail-accounts.json")
            store.save([GMAIL])
            store.upsert(MICROSOFT)
            renamed = replace(GMAIL, display_name="Renamed")
            store.upsert(renamed, existing=True)
            self.assertEqual(store.load(), [renamed, MICROSOFT])
            store.save([MICROSOFT])
            with self.assertRaisesRegex(MailError, "disconnected"):
                store.upsert(GMAIL, existing=True)
            self.assertEqual(store.load(), [MICROSOFT])


if __name__ == "__main__":
    unittest.main()
