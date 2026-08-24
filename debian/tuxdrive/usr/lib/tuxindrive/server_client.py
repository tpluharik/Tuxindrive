"""Bounded authenticated client for the optional self-hosted server."""

from __future__ import annotations

import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from .server_credentials import load_server_token


MAX_RESPONSE = 1024 * 1024


class ServerClientError(RuntimeError):
    pass


def normalize_server_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Server URL must be an HTTP or HTTPS origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Server URL must contain only scheme, host, and optional port")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("A remote TuxInDrive server requires HTTPS")
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class ServerClient:
    def __init__(self, url: str, ca_file: str = "", token: str | None = None, timeout: float = 8.0) -> None:
        self.url = normalize_server_url(url)
        self.ca_file = str(ca_file or "").strip()
        self._token = token
        self.timeout = max(1.0, min(30.0, float(timeout)))

    def _ssl_context(self):
        if not self.url.startswith("https://"):
            return None
        if self.ca_file:
            path = Path(self.ca_file).expanduser()
            if not path.is_file():
                raise ServerClientError("The configured server CA file does not exist")
            return ssl.create_default_context(cafile=str(path))
        return ssl.create_default_context()

    def request(self, path: str, method: str = "GET", payload: dict | None = None) -> dict:
        if not path.startswith("/") or ".." in path:
            raise ServerClientError("The server request path is invalid")
        token = self._token or load_server_token(self.url)
        body = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "TuxInDrive-client/1",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout, context=self._ssl_context()) as response:
                if int(response.headers.get("Content-Length", "0") or 0) > MAX_RESPONSE:
                    raise ServerClientError("The TuxInDrive server response is too large")
                data = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            exc.close()
            raise ServerClientError(f"Server rejected the request ({exc.code}): {detail}") from exc
        except (OSError, URLError, ssl.SSLError) as exc:
            raise ServerClientError(f"Could not contact the TuxInDrive server: {exc}") from exc
        if len(data) > MAX_RESPONSE:
            raise ServerClientError("The TuxInDrive server response is too large")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ServerClientError("The TuxInDrive server returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ServerClientError("The TuxInDrive server returned an invalid response")
        return value

    def health(self) -> dict:
        return self.request("/v1/health")

    def capabilities(self) -> dict:
        return self.request("/v1/capabilities")
