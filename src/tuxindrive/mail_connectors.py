"""Read-only Gmail/Graph adapters; names first, bounded file bytes on opt-in."""

from __future__ import annotations

import base64
import binascii
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from .mail_auth import (
    MAX_JSON_BYTES, MailAccount, MailAuthorization, MailError, check_cancel,
    http_bytes, json_response,
)


MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
MAX_ATTACHMENTS = 10000
MAX_CONTENT_RESPONSE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class MailAttachment:
    account_id: str
    provider: str
    account_name: str
    message_id: str
    attachment_id: str
    name: str
    subject: str
    sender: str
    received: str
    size: int
    mime_type: str
    message_url: str
    revision: str = ""


@dataclass(frozen=True)
class MailScan:
    attachments: tuple[MailAttachment, ...]
    messages: int
    complete: bool


def _text(value, limit: int = 1000) -> str:
    return str(value or "").replace("\x00", "")[:limit]


def _id(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise MailError("The mail provider returned an invalid item identifier.")
    return value


def _size(value) -> int:
    try:
        amount = int(value)
        if not 0 <= amount <= 2**63 - 1:
            raise ValueError()
        return amount
    except (TypeError, ValueError, OverflowError) as exc:
        raise MailError("The mail provider returned an invalid attachment size.") from exc


def safe_message_url(url: str, provider: str) -> str:
    try:
        parsed = urlsplit(url)
        hosts = {"mail.google.com"} if provider == "gmail" else {
            "outlook.office.com", "outlook.office365.com", "outlook.live.com",
        }
        if (parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username
                and not parsed.password and parsed.port in {None, 443}
                and not any(ord(c) < 32 for c in url) and len(url) <= 8192):
            return url
    except ValueError:
        pass
    raise MailError("This message does not have a safe provider web location.")


def _gmail_fields(depth: int = 10, *, content: bool = False) -> str:
    body = "attachmentId,size" + (",data" if content else "")
    fields = f"partId,filename,mimeType,headers(name,value),body({body})"
    return fields + (f",parts({_gmail_fields(depth - 1, content=content)})" if depth else "")


def _gmail_parts(payload: dict, *, depth: int = 0):
    if depth > 10:
        raise MailError("A mail MIME tree exceeded the indexing depth limit.")
    yield payload
    if str(payload.get("mimeType", "")).startswith("multipart/") and "parts" not in payload:
        raise MailError("The mail provider returned an incomplete MIME tree; old results are retained.")
    for child in payload.get("parts", []):
        if not isinstance(child, dict):
            raise MailError("The mail provider returned an invalid MIME part.")
        yield from _gmail_parts(child, depth=depth + 1)


class MailClient:
    """No write methods. Continuation URLs cannot change the credential origin."""

    def __init__(self, account: MailAccount, authorization: MailAuthorization | None = None,
                 *, bandwidth=None, stop: Event | None = None):
        account.validate()
        self.account = account
        self.authorization = authorization or MailAuthorization()
        self.bandwidth, self.stop = bandwidth, stop
        self.content_bytes_remaining = MAX_CONTENT_RESPONSE_BYTES
        self.base = ("https://gmail.googleapis.com/gmail/v1/users/me/" if account.provider == "gmail"
                     else "https://graph.microsoft.com/v1.0/me/")

    def _request(self, url: str, *, limit: int = MAX_JSON_BYTES, attachment: bool = False) -> bytes:
        if not url.startswith(self.base) or urlsplit(url).fragment:
            raise MailError("Mail pagination left the approved account API; credentials were not forwarded.")
        check_cancel(self.stop)
        token = self.authorization.access_token(self.account, stop=self.stop)
        if any(ord(c) < 32 for c in token) or len(token) > 32000:
            raise MailError("Reconnect this mailbox; its access token is invalid.")
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if self.account.provider == "microsoft365":
            headers["Prefer"] = 'IdType="ImmutableId"'
        gate = (self.bandwidth.interactive_transfer_guard() if attachment
                else self.bandwidth.control_plane_guard()) if self.bandwidth else nullcontext()
        if attachment:
            if self.content_bytes_remaining <= 0:
                raise MailError("The attachment download budget was reached; refresh again for remaining contents.")
            limit = min(limit, self.content_bytes_remaining)
        with gate:
            raw = None
            try:
                raw = http_bytes(Request(url, headers=headers), limit, stop=self.stop,
                                 bandwidth=self.bandwidth, retries=1 if attachment else 3)
                return raw
            finally:
                # Count wire payload too (base64/MIME overhead), conservatively
                # charging the request cap when a failed response was incomplete.
                if attachment:
                    self.content_bytes_remaining -= len(raw) if raw is not None else limit

    def _json(self, path: str, *, params: dict | None = None, absolute: bool = False,
              limit: int = MAX_JSON_BYTES, attachment: bool = False) -> dict:
        url = path if absolute else self.base + path
        if params:
            url += "?" + urlencode(params)
        return json_response(self._request(url, limit=limit, attachment=attachment))

    def scan(self, progress=None) -> MailScan:
        return self._gmail_scan(progress) if self.account.provider == "gmail" else self._graph_scan(progress)

    def _gmail_scan(self, progress) -> MailScan:
        profile = self._json("profile", params={"fields": "emailAddress"})
        email = profile.get("emailAddress")
        if not isinstance(email, str) or not email or len(email) > 320 or any(ord(c) < 32 for c in email):
            raise MailError("The mail provider did not identify the authorized mailbox; old results are retained.")
        query = "has:attachment -in:trash -in:spam"
        if self.account.days:
            query += f" newer_than:{self.account.days}d"
        attachments, messages, page_token, seen_pages = [], 0, "", set()
        while True:
            check_cancel(self.stop)
            params = {"q": query, "maxResults": min(100, self.account.max_messages - messages),
                      "fields": "messages(id,threadId),nextPageToken", "includeSpamTrash": "false"}
            if page_token:
                params["pageToken"] = page_token
            page = self._json("messages", params=params)
            references = page.get("messages", [])
            if not isinstance(references, list) or set(page) - {"messages", "nextPageToken"}:
                raise MailError("The mail provider returned an invalid message page.")
            for reference in references:
                check_cancel(self.stop)
                if messages >= self.account.max_messages or len(attachments) >= MAX_ATTACHMENTS:
                    return MailScan(tuple(attachments), messages, False)
                message_id = _id(reference.get("id"))
                message = self._json("messages/" + quote(message_id, safe=""), params={
                    "format": "full", "fields": f"id,threadId,internalDate,payload({_gmail_fields()})"})
                payload = message.get("payload", {})
                if message.get("id") != message_id or not isinstance(payload, dict):
                    raise MailError("The mail provider returned incomplete message metadata.")
                headers = {str(h.get("name", "")).lower(): _text(h.get("value")) for h in payload.get("headers", [])}
                thread = _id(message.get("threadId", message_id))
                location = "https://mail.google.com/mail/u/0/?" + urlencode({"authuser": email})
                location += "#all/" + quote(thread, safe="")
                for part in _gmail_parts(payload):
                    name = _text(part.get("filename"), 255)
                    disposition = next((str(h.get("value", "")) for h in part.get("headers", [])
                                        if str(h.get("name", "")).lower() == "content-disposition"), "")
                    if not name or disposition.lower().startswith("inline"):
                        continue
                    body = part.get("body", {})
                    identifier = body.get("attachmentId") or "part:" + _id(part.get("partId"))
                    attachments.append(MailAttachment(
                        self.account.id, "gmail", self.account.display_name, message_id, _id(identifier), name,
                        headers.get("subject", "")[:512], headers.get("from", "")[:512],
                        _text(message.get("internalDate", headers.get("date", "")), 100),
                        _size(body.get("size", 0)), _text(part.get("mimeType"), 255), location))
                    if len(attachments) >= MAX_ATTACHMENTS:
                        return MailScan(tuple(attachments), messages + 1, False)
                messages += 1
                if progress:
                    progress(messages, self.account.max_messages, len(attachments))
            next_page = page.get("nextPageToken", "")
            if not next_page:
                return MailScan(tuple(attachments), messages, True)
            if messages >= self.account.max_messages:
                return MailScan(tuple(attachments), messages, False)
            page_token = _id(next_page)
            if page_token in seen_pages:
                raise MailError("Mail pagination repeated a page; the previous index is retained.")
            seen_pages.add(page_token)
            if len(seen_pages) > 1000:
                raise MailError("The mail pagination safety limit was reached; old results are retained.")

    def _graph_scan(self, progress) -> MailScan:
        selected = "id,subject,from,receivedDateTime,hasAttachments,webLink,changeKey,lastModifiedDateTime"
        expression = "hasAttachments eq true"
        if self.account.days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self.account.days)
            expression += " and receivedDateTime ge " + cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        url = self.base + "messages?" + urlencode({"$filter": expression, "$select": selected, "$top": 100})
        attachments, messages, seen_pages = [], 0, set()
        while url:
            check_cancel(self.stop)
            if url in seen_pages:
                raise MailError("Mail pagination repeated a page; the previous index is retained.")
            seen_pages.add(url)
            page = self._json(url, absolute=True)
            references = page.get("value")
            if not isinstance(references, list):
                raise MailError("The mail provider returned an invalid message page.")
            for message in references:
                check_cancel(self.stop)
                if messages >= self.account.max_messages:
                    return MailScan(tuple(attachments), messages, False)
                message_id = _id(message.get("id"))
                prefix = self.base + "messages/" + quote(message_id, safe="") + "/attachments"
                attachment_url = prefix + "?" + urlencode({"$select": "id,name,size,contentType,isInline", "$top": 100})
                seen_attachments = set()
                while attachment_url:
                    if (attachment_url in seen_attachments
                            or urlsplit(attachment_url).path != urlsplit(prefix).path):
                        raise MailError("Attachment pagination is invalid; the previous index is retained.")
                    seen_attachments.add(attachment_url)
                    items = self._json(attachment_url, absolute=True)
                    if not isinstance(items.get("value"), list) or len(seen_attachments) > 200:
                        raise MailError("The attachment page is incomplete or exceeded its safety limit.")
                    for item in items["value"]:
                        if item.get("isInline") or item.get("@odata.type") != "#microsoft.graph.fileAttachment":
                            continue
                        sender = message.get("from", {}).get("emailAddress", {})
                        attachments.append(MailAttachment(
                            self.account.id, "microsoft365", self.account.display_name, message_id, _id(item.get("id")),
                            _text(item.get("name"), 255), _text(message.get("subject"), 512),
                            _text(sender.get("address", sender.get("name", "")), 512),
                            _text(message.get("receivedDateTime"), 100), _size(item.get("size", 0)),
                            _text(item.get("contentType"), 255),
                            safe_message_url(str(message.get("webLink", "")), "microsoft365"),
                            _text(message.get("changeKey", message.get("lastModifiedDateTime", "")), 255)))
                        if len(attachments) >= MAX_ATTACHMENTS:
                            return MailScan(tuple(attachments), messages + 1, False)
                    attachment_url = items.get("@odata.nextLink", "")
                    if not isinstance(attachment_url, str):
                        raise MailError("The mail provider returned an invalid continuation.")
                messages += 1
                if progress:
                    progress(messages, self.account.max_messages, len(attachments))
            url = page.get("@odata.nextLink", "")
            if not isinstance(url, str) or (url and urlsplit(url).path != "/v1.0/me/messages"):
                raise MailError("The mail provider returned an invalid message continuation.")
            if url and messages >= self.account.max_messages:
                return MailScan(tuple(attachments), messages, False)
            if len(seen_pages) > 1000:
                raise MailError("The mail pagination safety limit was reached; old results are retained.")
        return MailScan(tuple(attachments), messages, True)

    def download(self, item: MailAttachment) -> bytes:
        if item.account_id != self.account.id or item.provider != self.account.provider:
            raise MailError("This attachment does not belong to the selected mailbox.")
        if item.size > MAX_ATTACHMENT_BYTES:
            raise MailError("The attachment exceeds the 8 MiB content-indexing limit.")
        path = "messages/" + quote(_id(item.message_id), safe="") + "/attachments/" + quote(_id(item.attachment_id), safe="")
        if self.account.provider == "microsoft365":
            content = self._request(self.base + path + "/$value", limit=MAX_ATTACHMENT_BYTES, attachment=True)
        else:
            if item.attachment_id.startswith("part:"):
                payload = self._json("messages/" + quote(item.message_id, safe=""), params={
                    "format": "full", "fields": f"payload({_gmail_fields(content=True)})"},
                    limit=MAX_ATTACHMENT_BYTES * 2, attachment=True)
                part = next((p for p in _gmail_parts(payload.get("payload", {}))
                             if "part:" + str(p.get("partId", "")) == item.attachment_id), None)
                if part is None:
                    raise MailError("This attachment is no longer available in the message.")
                encoded = part.get("body", {}).get("data", "")
            else:
                payload = self._json(path, limit=MAX_ATTACHMENT_BYTES * 2, attachment=True)
                encoded = payload.get("data", "")
            if not isinstance(encoded, str) or len(encoded) > MAX_ATTACHMENT_BYTES * 4 // 3 + 8:
                raise MailError("The attachment response exceeded its safety limit.")
            try:
                content = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
            except (ValueError, binascii.Error) as exc:
                raise MailError("The attachment response is not valid base64 data.") from exc
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise MailError("The attachment exceeds the content-indexing limit.")
        if len(content) != item.size:
            raise MailError("The attachment changed during indexing; its content was not stored.")
        return content
