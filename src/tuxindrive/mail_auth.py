"""Read-only desktop mail OAuth, with PKCE and native-store-only tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Event, RLock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .file_permissions import private_descriptor
from .process_control import run_process


GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GRAPH_SCOPE = "https://graph.microsoft.com/Mail.Read"
SERVICE = "io.github.tuxindrive.TuxInDrive"
MAX_JSON_BYTES = 2 * 1024 * 1024


class MailError(RuntimeError):
    """Safe, user-facing errors never include URLs, response bodies or tokens."""


class MailCancelled(MailError):
    pass


def check_cancel(stop: Event | None) -> None:
    if stop is not None and stop.is_set():
        raise MailCancelled("Mail operation cancelled; the previous index is retained.")


@dataclass(frozen=True)
class MailAccount:
    id: str
    provider: str
    display_name: str
    client_id: str
    tenant: str = "common"
    email: str = ""
    days: int = 365
    max_messages: int = 2000
    include_content: bool = False

    def validate(self) -> None:
        if any(not isinstance(value, str) for value in
               (self.id, self.provider, self.display_name, self.client_id, self.tenant, self.email)):
            raise MailError("Invalid mail account settings; text fields are required.")
        if not re.fullmatch(r"[a-f0-9]{32}", self.id):
            raise MailError("Invalid mail account identifier.")
        if self.provider not in {"gmail", "microsoft365"}:
            raise MailError("Choose Gmail or Microsoft 365.")
        if not self.client_id.strip() or len(self.client_id) > 256:
            raise MailError("Enter the registered desktop OAuth application client ID.")
        if any(ord(c) < 32 for c in self.client_id + self.email + self.display_name):
            raise MailError("Mail account fields must not contain control characters.")
        if not self.display_name.strip() or len(self.display_name) > 200 or len(self.email) > 320:
            raise MailError("Enter a short display name for this mailbox.")
        if self.provider == "microsoft365" and not (
            self.tenant in {"common", "organizations", "consumers"}
            or re.fullmatch(r"[a-fA-F0-9-]{36}", self.tenant)
        ):
            raise MailError("Microsoft tenant must be common, organizations, consumers, or a tenant UUID.")
        if type(self.days) is not int or not 0 <= self.days <= 36500:
            raise MailError("Mail history must be 0 (all) or a number of days up to 36500.")
        if type(self.max_messages) is not int or not 1 <= self.max_messages <= 50000:
            raise MailError("The message limit must be between 1 and 50000.")
        if type(self.include_content) is not bool:
            raise MailError("Invalid attachment-content setting.")


class MailAccountStore:
    """Only non-secret settings; mail accounts are not sync jobs/profile secrets."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock = RLock()

    def load(self) -> list[MailAccount]:
        with self.lock:
            if not self.path.exists():
                return []
            try:
                if self.path.stat().st_size > MAX_JSON_BYTES:
                    raise ValueError()
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, list) or len(data) > 100:
                    raise ValueError()
                accounts = [MailAccount(**item) for item in data]
                for account in accounts:
                    account.validate()
                if len({a.id for a in accounts}) != len(accounts):
                    raise ValueError()
                return accounts
            except (ValueError, TypeError) as exc:
                raise MailError("Mail account settings are invalid; the original file was not changed.") from exc

    def save(self, accounts: list[MailAccount]) -> None:
        if len(accounts) > 100 or len({a.id for a in accounts}) != len(accounts):
            raise MailError("Too many or duplicate mail accounts.")
        for account in accounts:
            account.validate()
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, name = tempfile.mkstemp(prefix=".mail-accounts-", dir=self.path.parent)
            temporary = Path(name)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                    private_descriptor(stream.fileno())
                    json.dump([asdict(a) for a in accounts], stream, indent=2)
                    stream.write("\n")
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)


class MailTokenStore:
    """No disk fallback: token JSON lives solely in the desktop credential store."""

    @staticmethod
    def _purpose(account: MailAccount) -> str:
        account.validate()
        return "mail-oauth-" + account.id

    def _command(self, operation: str, account: MailAccount, value: str | None = None):
        command = ["/usr/bin/secret-tool", operation]
        if operation == "store":
            command += ["--label=TuxInDrive read-only mail"]
        command += ["application", "tuxindrive", "purpose", self._purpose(account)]
        try:
            return run_process(command, input=value, capture_output=True, text=True, timeout=10)
        except (OSError, TimeoutError, subprocess.SubprocessError) as exc:
            raise MailError("Unlock your desktop credential store and retry; mail tokens are never saved in plaintext.") from exc

    @staticmethod
    def _keyring():
        try:
            import keyring
            backend = keyring.get_keyring()
            allowed = {"keyring.backends.Windows", "keyring.backends.macOS"}
            candidates = getattr(backend, "backends", [backend])
            native = next((item for item in candidates if type(item).__module__ in allowed), None)
            if native is None:
                raise MailError("A native credential store is required; plaintext keyring backends are not allowed.")
            return native
        except ImportError as exc:
            raise MailError("Native credential-store support is unavailable.") from exc
        except MailError:
            raise
        except Exception as exc:
            raise MailError("Unlock the native credential store and retry.") from exc

    def load(self, account: MailAccount) -> dict:
        purpose = self._purpose(account)
        try:
            if sys.platform.startswith("linux"):
                result = self._command("lookup", account)
                raw = result.stdout.strip() if result.returncode == 0 else ""
            else:
                raw = self._keyring().get_password(SERVICE, purpose) or ""
            if not raw or len(raw) > 65536:
                raise MailError("Reconnect this mailbox; its OAuth credential is unavailable.")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
            return data
        except (ValueError, TypeError) as exc:
            raise MailError("Reconnect this mailbox; its OAuth credential is invalid.") from exc
        except MailError:
            raise
        except Exception as exc:
            raise MailError("The mailbox credential could not be read from the native store.") from exc

    def store(self, account: MailAccount, value: dict) -> None:
        raw = json.dumps(value, separators=(",", ":"))
        if len(raw) > 65536:
            raise MailError("The mail OAuth credential exceeded its safety limit.")
        if sys.platform.startswith("linux"):
            if self._command("store", account, raw).returncode:
                raise MailError("Mail authorization could not be saved in the native credential store.")
        else:
            try:
                self._keyring().set_password(SERVICE, self._purpose(account), raw)
            except MailError:
                raise
            except Exception as exc:
                raise MailError("Mail authorization could not be saved in the native credential store.") from exc

    def delete(self, account: MailAccount) -> None:
        if sys.platform.startswith("linux"):
            result = self._command("clear", account)
            if result.returncode not in {0, 1}:
                raise MailError("The mailbox credential could not be removed.")
        else:
            try:
                backend = self._keyring()
                if backend.get_password(SERVICE, self._purpose(account)):
                    backend.delete_password(SERVICE, self._purpose(account))
            except MailError:
                raise
            except Exception as exc:
                raise MailError("The mailbox credential could not be removed from the native store.") from exc


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MailError("The mail service returned a redirect; credentials were not forwarded.")


def http_bytes(request: Request, limit: int, *, stop: Event | None = None,
               bandwidth=None, retries: int = 3) -> bytes:
    """Bounded HTTPS only, no redirects or unbounded Retry-After waits."""
    parsed = urlsplit(request.full_url)
    if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment
            or parsed.port not in {None, 443}
            or parsed.hostname not in {"gmail.googleapis.com", "oauth2.googleapis.com",
                                       "graph.microsoft.com", "login.microsoftonline.com"}):
        raise MailError("The mail endpoint is not an approved HTTPS service.")
    for attempt in range(retries):
        check_cancel(stop)
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                chunks, size = [], 0
                while True:
                    check_cancel(stop)
                    chunk = response.read(min(65536, limit + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > limit:
                        raise MailError("The mail response exceeded its safety limit.")
                    if bandwidth:
                        bandwidth.throttle_download(len(chunk))
                    chunks.append(chunk)
                return b"".join(chunks)
        except HTTPError as exc:
            if exc.code in {429, 500, 502, 503, 504} and attempt + 1 < retries:
                try:
                    delay = min(20, max(1, int(exc.headers.get("Retry-After", 2 ** attempt))))
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                (stop or Event()).wait(delay)
                continue
            if exc.code == 401:
                raise MailError("Mail authorization expired; reconnect the mailbox.") from None
            if exc.code == 403:
                raise MailError("Mail access was denied; check read-only permissions and organization consent.") from None
            raise MailError(f"The mail service returned HTTP {exc.code}; retry indexing later.") from None
        except (URLError, TimeoutError, OSError) as exc:
            raise MailError("The mail service could not be reached; the previous index is retained.") from exc
    raise MailError("The mail service is temporarily unavailable.")


def json_response(raw: bytes) -> dict:
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, UnicodeError) as exc:
        raise MailError("The mail service returned an invalid response.") from exc


def token_endpoint(account: MailAccount) -> str:
    account.validate()
    if account.provider == "gmail":
        return "https://oauth2.googleapis.com/token"
    return f"https://login.microsoftonline.com/{account.tenant}/oauth2/v2.0/token"


def _grant(account: MailAccount, fields: dict, *, stop=None) -> dict:
    raw = http_bytes(Request(token_endpoint(account), data=urlencode(fields).encode(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"}),
                     MAX_JSON_BYTES, stop=stop, retries=1)
    tokens = json_response(raw)
    access = tokens.get("access_token")
    if not isinstance(access, str) or not access or len(access) > 32000 or any(ord(c) < 32 for c in access):
        raise MailError("The mail provider did not return a usable access token.")
    refresh = tokens.get("refresh_token", "")
    if not isinstance(refresh, str) or len(refresh) > 32000 or any(ord(c) < 32 for c in refresh):
        raise MailError("The mail provider did not return a usable renewal token.")
    try:
        expiry = float(tokens.get("expires_in", 3600))
        if not 0 < expiry <= 7 * 86400:
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise MailError("The mail provider returned an invalid token expiry.") from exc
    return {"access_token": access, "refresh_token": refresh,
            "expires_at": time.time() + expiry}


def authorization_parameters(account: MailAccount, redirect: str, state: str, verifier: str) -> tuple[str, dict]:
    account.validate()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    fields = {"client_id": account.client_id, "redirect_uri": redirect, "response_type": "code",
              "scope": GMAIL_SCOPE if account.provider == "gmail" else GRAPH_SCOPE + " offline_access",
              "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    if account.email:
        fields["login_hint"] = account.email
    if account.provider == "gmail":
        fields.update(access_type="offline", prompt="consent")
        return "https://accounts.google.com/o/oauth2/v2/auth", fields
    fields.update(prompt="select_account", response_mode="query")
    return f"https://login.microsoftonline.com/{account.tenant}/oauth2/v2.0/authorize", fields


def valid_callback(path: str, state: str) -> str | None:
    parsed = urlsplit(path)
    if parsed.path != "/" or parsed.scheme or parsed.netloc or len(path) > 8192:
        return None
    values = parse_qs(parsed.query, keep_blank_values=True)
    received = values.get("state", [])
    if len(received) != 1 or not received[0].isascii() or not secrets.compare_digest(received[0], state):
        return None
    if "error" in values:
        raise MailError("Mail authorization was declined or blocked by the account administrator.")
    codes = values.get("code", [])
    return codes[0] if len(codes) == 1 and codes[0] else None


def authorize(account: MailAccount, token_store: MailTokenStore, *, client_secret: str = "",
              stop: Event | None = None, browser=webbrowser.open, on_url=None,
              timeout: float = 180) -> None:
    """User-invoked system browser consent; no password or embedded webview."""
    account.validate()
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    outcome: dict = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Authorization codes must never enter request logs.

        def do_GET(self):
            try:
                code = valid_callback(self.path, state)
            except MailError as exc:
                outcome["error"] = exc
                code = None
            if code:
                outcome["code"] = code
            self.send_response(200 if code or "error" in outcome else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"Return to TuxInDrive to finish connecting your mailbox."
                             if code else b"Authorization was not accepted. Return to TuxInDrive.")

    class LoopbackServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(2)
            return connection, address

    with LoopbackServer(("127.0.0.1", 0), Callback) as server:
        server.timeout = 0.5
        host = "127.0.0.1" if account.provider == "gmail" else "localhost"
        redirect = f"http://{host}:{server.server_port}/"
        base, fields = authorization_parameters(account, redirect, state, verifier)
        url = base + "?" + urlencode(fields)
        if on_url:
            on_url(url)
        browser(url)
        deadline = time.monotonic() + timeout
        while not outcome and time.monotonic() < deadline:
            check_cancel(stop)
            server.handle_request()
        check_cancel(stop)
        if "error" in outcome:
            raise outcome["error"]
        if "code" not in outcome:
            raise MailError("Mail authorization timed out; choose Connect to try again.")
        fields = {"client_id": account.client_id, "redirect_uri": redirect,
                  "grant_type": "authorization_code", "code": outcome["code"], "code_verifier": verifier}
        if account.provider == "gmail" and client_secret:
            fields["client_secret"] = client_secret
        tokens = _grant(account, fields, stop=stop)
        if not tokens.get("refresh_token"):
            raise MailError("Offline mail access was not granted; reconnect and approve read-only access.")
        if account.provider == "gmail" and client_secret:
            tokens["client_secret"] = client_secret
        check_cancel(stop)
        token_store.store(account, tokens)


class MailAuthorization:
    def __init__(self, store: MailTokenStore | None = None):
        self.store = store or MailTokenStore()
        self.lock = RLock()
        self.cached: dict[tuple, dict] = {}

    def invalidate(self, account: MailAccount) -> None:
        with self.lock:
            self.cached.pop((account.id, account.client_id, account.tenant), None)

    def access_token(self, account: MailAccount, *, stop=None) -> str:
        with self.lock:
            check_cancel(stop)
            cache_key = (account.id, account.client_id, account.tenant)
            if cache_key not in self.cached:
                self.cached[cache_key] = self.store.load(account)
            value = self.cached[cache_key]
            try:
                fresh = float(value.get("expires_at", 0)) > time.time() + 60
            except (ValueError, TypeError):
                fresh = False
            if fresh and isinstance(value.get("access_token"), str) and value["access_token"]:
                return value["access_token"]
            refresh = value.get("refresh_token")
            if not isinstance(refresh, str) or not refresh:
                raise MailError("Reconnect this mailbox to renew read-only access.")
            fields = {"client_id": account.client_id, "grant_type": "refresh_token", "refresh_token": refresh}
            if account.provider == "gmail" and value.get("client_secret"):
                fields["client_secret"] = value["client_secret"]
            if account.provider == "microsoft365":
                fields["scope"] = GRAPH_SCOPE + " offline_access"
            renewed = _grant(account, fields, stop=stop)
            renewed["refresh_token"] = renewed.get("refresh_token") or refresh
            if value.get("client_secret"):
                renewed["client_secret"] = value["client_secret"]
            self.store.store(account, renewed)
            self.cached[cache_key] = renewed
            return renewed["access_token"]
