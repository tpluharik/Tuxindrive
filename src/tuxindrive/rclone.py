from __future__ import annotations

import configparser
import json
import os
import platform
import signal
import shutil
import socket
import subprocess
import sys
import threading
import ctypes
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Provider
from .bootstrap import install_rclone, resolve_rclone
from .process_control import new_process_group, spawn_process, run_process, terminate_process


class RcloneError(RuntimeError):
    pass


def _protect_sensitive_child() -> None:
    """Prevent same-user processes from reading sensitive rclone argv on Linux."""
    if platform.system() != "Linux":
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            os._exit(126)
    except Exception:
        os._exit(126)


@dataclass(slots=True)
class ConfigQuestion:
    state: str
    name: str
    help: str
    default: Any
    examples: list[dict[str, Any]]
    required: bool
    secret: bool
    exclusive: bool
    error: str = ""


@dataclass(slots=True)
class ConfigResult:
    complete: bool
    question: ConfigQuestion | None = None


@dataclass(slots=True)
class DriveLocation:
    key: str
    name: str
    scoped_remote: str


class RcloneClient:
    """Small, auditable interface to rclone.

    OAuth tokens stay in rclone's mode-0600 configuration. TuxInDrive never
    writes tokens to its own JSON configuration and never emits config dumps
    into logs.
    """

    def __init__(self, executable: str = "rclone") -> None:
        self.executable = executable
        self._oauth_guard = threading.Lock()
        self._oauth_process: subprocess.Popen[str] | None = None
        self._oauth_session: str | None = None
        self._config_security_checked = False

    def available(self) -> bool:
        resolved = resolve_rclone(self.executable)
        if resolved:
            self.executable = resolved
            self._ensure_config_security()
            return True
        return False

    def ensure_available(self) -> str:
        if self.available():
            return self.executable
        self.executable = install_rclone()
        return self.executable

    def version(self) -> str:
        result = self._run(["version"])
        return result.stdout.splitlines()[0] if result.stdout else "rclone"

    def list_remotes(self) -> list[str]:
        result = self._run(["listremotes"])
        return [line.rstrip(":") for line in result.stdout.splitlines() if line.strip()]

    def copy_to(self, source: str | Path, destination: str | Path) -> None:
        """Copy one object without exposing its contents to logs or stdout."""
        self._run(["copyto", str(source), str(destination)])

    def copy_between_remotes(
        self,
        source_remote: str,
        source_path: str,
        destination_remote: str,
        destination_path: str,
        *,
        dry_run: bool = True,
        bandwidth_args: Iterable[str] = (),
    ) -> subprocess.CompletedProcess[str]:
        """Copy cloud-to-cloud without deleting either endpoint.

        The caller must complete a dry run before invoking the real operation.
        rclone uses a provider-side transfer when supported and safely falls
        back to streamed transfer otherwise.
        """
        self._validate_remote_name(source_remote)
        self._validate_remote_name(destination_remote)
        if source_remote == destination_remote:
            raise ValueError("Cloud-to-cloud copy requires two different accounts")
        source = self._remote_spec(source_remote, source_path)
        destination = self._remote_spec(destination_remote, destination_path)
        args = [
            "copy", source, destination,
            "--server-side-across-configs",
            "--stats-one-line", "--stats", "5s",
            *list(bandwidth_args),
        ]
        if dry_run:
            args.append("--dry-run")
        return self._run(args, timeout=24 * 60 * 60)

    def object_exists(self, spec: str) -> bool:
        try:
            self._run(["lsjson", "--stat", spec])
            return True
        except RcloneError:
            return False

    def config_file(self) -> Path:
        result = self._run(["config", "file"])
        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if lines:
            candidate = Path(lines[-1]).expanduser()
            if candidate.is_file():
                return candidate
        fallback = Path.home() / ".config" / "rclone" / "rclone.conf"
        if fallback.is_file():
            return fallback
        raise RcloneError("Could not locate rclone's private configuration file")

    def discover_accounts(self) -> dict[str, Provider]:
        # The dump is parsed only in memory and is never returned or logged.
        result = self._run(["config", "dump"])
        try:
            raw = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as exc:
            raise RcloneError("rclone returned an invalid configuration") from exc
        accounts: dict[str, Provider] = {}
        backend_map = {
            provider.rclone_type: provider
            for provider in Provider
            if provider not in {Provider.NEXTCLOUD, Provider.WEBDAV, Provider.GITHUB, Provider.PEER}
        }
        for name, values in raw.items():
            backend = values.get("type") if isinstance(values, dict) else None
            if backend in backend_map:
                accounts[name] = backend_map[backend]
            elif backend == "webdav" and isinstance(values, dict) and values.get("vendor") == "nextcloud":
                accounts[name] = Provider.NEXTCLOUD
            elif backend == "webdav":
                accounts[name] = Provider.WEBDAV
        return accounts

    def account_login(self, remote: str, provider: Provider) -> str:
        """Return a non-secret login label without persisting provider tokens."""
        self._validate_remote_name(remote)
        try:
            result = self._run(["config", "userinfo", f"{remote}:", "--json"], timeout=30)
            identity = self._identity_label(json.loads(result.stdout or "{}"))
            if identity:
                return identity
        except (RcloneError, json.JSONDecodeError):
            pass

        # Older rclone backends do not consistently implement `config userinfo`.
        # Refresh through rclone when possible, then keep its decrypted config
        # only in memory. Never return or log tokens or secret config values.
        try:
            try:
                self._run(["about", f"{remote}:", "--json"], timeout=30)
            except RcloneError:
                pass
            raw = json.loads(self._run(["config", "dump"]).stdout or "{}")
            values = raw.get(remote, {})
            if not isinstance(values, dict):
                return ""
            identity = self._configured_identity(values)
            if identity:
                return identity
            token_value = values.get("token", "") if isinstance(values, dict) else ""
            token = json.loads(token_value) if isinstance(token_value, str) else token_value
            access_token = token.get("access_token", "") if isinstance(token, dict) else ""
            if not access_token:
                return ""
            request = self._identity_request(provider, access_token, values)
            if request is None:
                return self._identity_label(token)
            with urlopen(request, timeout=20) as response:
                return self._identity_label(json.load(response))
        except (RcloneError, json.JSONDecodeError, OSError, URLError, ValueError, KeyError):
            return ""

    @staticmethod
    def _configured_identity(values: dict[str, Any]) -> str:
        """Read only known non-secret identity fields from an rclone remote."""
        for key in ("user", "username", "email", "login"):
            candidate = values.get(key)
            if isinstance(candidate, str):
                candidate = " ".join(candidate.split()).strip()
                if candidate and len(candidate) <= 320:
                    return candidate
        return ""

    @staticmethod
    def _identity_request(
        provider: Provider, access_token: str, values: dict[str, Any]
    ) -> Request | None:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "TuxInDrive account identity",
        }
        if provider is Provider.GOOGLE_DRIVE:
            return Request(
                "https://www.googleapis.com/drive/v3/about?fields=user(displayName,emailAddress)",
                headers=headers,
            )
        if provider is Provider.ONEDRIVE:
            return Request(
                "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName",
                headers=headers,
            )
        if provider is Provider.DROPBOX:
            return Request(
                "https://api.dropboxapi.com/2/users/get_current_account",
                data=b"null",
                headers={**headers, "Content-Type": "application/json"},
                method="POST",
            )
        if provider is Provider.BOX:
            return Request(
                "https://api.box.com/2.0/users/me?fields=name,login",
                headers=headers,
            )
        if provider is Provider.PCLOUD:
            hostname = str(values.get("hostname") or "api.pcloud.com").strip().lower()
            if hostname not in {"api.pcloud.com", "eapi.pcloud.com"}:
                hostname = "api.pcloud.com"
            # pCloud requires the OAuth token as a form field. It is sent only
            # in the HTTPS request body, never in the URL or application logs.
            return Request(
                f"https://{hostname}/userinfo",
                data=urlencode({"access_token": access_token}).encode("ascii"),
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": headers["User-Agent"]},
                method="POST",
            )
        return None

    @staticmethod
    def _identity_label(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        preferred = (
            "emailAddress", "email", "userPrincipalName", "login", "username",
            "displayName", "name",
        )
        for key in preferred:
            candidate = value.get(key)
            if isinstance(candidate, str):
                candidate = " ".join(candidate.split()).strip()
                if candidate and len(candidate) <= 320:
                    return candidate
        for nested in ("user", "account", "owner"):
            candidate = RcloneClient._identity_label(value.get(nested))
            if candidate:
                return candidate
        return ""

    def begin_oauth(
        self,
        remote: str,
        provider: Provider,
        client_id: str = "",
        client_secret: str = "",
        session_id: str = "",
        credentials: dict[str, str] | None = None,
        replace_existing: bool = False,
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        if provider is Provider.PROTON_DRIVE:
            raise RcloneError(
                "Proton Drive authorization is available only through Proton's official browser-authenticated CLI"
            )
        args = (
            ["config", "update", remote]
            if replace_existing
            else ["config", "create", remote, provider.rclone_type]
        )
        if not replace_existing:
            args.extend(provider.initial_options)
        if client_id:
            args.extend(["client_id", client_id])
        if client_secret:
            args.extend(["client_secret", client_secret])
        secret_keys = {
            key for key, _label, secret, _required in provider.credential_fields if secret
        }
        for key, value in (credentials or {}).items():
            if not value:
                continue
            args.extend([key, self._obscure(value) if key in secret_keys else value])
        args.append("--non-interactive")
        return self._configuration_step(args, session_id)

    def validate_remote(self, remote: str) -> None:
        self._validate_remote_name(remote)
        self._run(["lsf", f"{remote}:", "--dirs-only", "--max-depth", "1"])

    def create_crypt_remote(
        self,
        remote: str,
        base_spec: str,
        password: str,
        password2: str = "",
        filename_encryption: str = "standard",
    ) -> None:
        """Create a crypt remote without ever placing cleartext secrets in config."""
        self._validate_remote_name(remote)
        if not base_spec or ":" not in base_spec:
            raise RcloneError("Choose a configured storage account and a dedicated vault folder")
        if not password:
            raise RcloneError("A vault password is required")
        if filename_encryption not in {"standard", "obfuscate", "off"}:
            raise RcloneError("Unsupported filename encryption mode")
        args = [
            "config", "create", remote, "crypt",
            "remote", base_spec,
            "filename_encryption", filename_encryption,
            "directory_name_encryption", "true",
            "password", self._obscure(password),
        ]
        if password2:
            args.extend(["password2", self._obscure(password2)])
        args.append("--non-interactive")
        self._run(args)
        self.validate_remote(remote)

    def update_credentials(
        self, remote: str, provider: Provider, credentials: dict[str, str]
    ) -> None:
        self._validate_remote_name(remote)
        if provider is Provider.PROTON_DRIVE:
            raise RcloneError(
                "Proton Drive credentials cannot be entered into TuxInDrive; reconnect in the official browser flow"
            )
        secret_keys = {
            key for key, _label, secret, _required in provider.credential_fields if secret
        }
        args = ["config", "update", remote]
        for key, value in credentials.items():
            if value:
                args.extend([key, self._obscure(value) if key in secret_keys else value])
        args.append("--non-interactive")
        self._run(args)

    def _obscure(self, value: str) -> str:
        if not self.available():
            self.ensure_available()
        result = subprocess.run(
            [self.executable, "obscure", "-"],
            input=value,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode or not result.stdout.strip():
            raise RcloneError("Could not protect the provider password before configuration")
        return result.stdout.strip()

    def continue_oauth(
        self,
        remote: str,
        state: str,
        answer: str,
        session_id: str = "",
    ) -> ConfigResult:
        self._validate_remote_name(remote)
        return self._configuration_step(
            [
                "config",
                "update",
                remote,
                "--continue",
                "--state",
                state,
                "--result",
                answer,
                "--non-interactive",
            ],
            session_id,
        )

    def reconnect(self, remote: str) -> subprocess.CompletedProcess[str]:
        self._validate_remote_name(remote)
        return self._run(["config", "reconnect", f"{remote}:"])

    def delete_remote(self, remote: str) -> None:
        self._validate_remote_name(remote)
        self._run(["config", "delete", remote])

    def list_directories(self, remote: str, remote_path: str = "") -> list[str]:
        self._validate_remote_name(remote)
        spec = f"{remote}:{remote_path.strip('/')}"
        result = self._run(["lsf", spec, "--dirs-only", "--max-depth", "1"])
        return sorted(line.rstrip("/") for line in result.stdout.splitlines() if line.strip())

    def google_drive_locations(self, remote: str) -> list[DriveLocation]:
        self._validate_remote_name(remote)
        configured_name = self._configured_google_root_name(remote)
        locations = [
            DriveLocation(
                "my_drive",
                "My Drive",
                google_scoped_remote(remote, "my_drive"),
            ),
            DriveLocation(
                "shared_with_me",
                "Shared with me",
                google_scoped_remote(remote, "shared_with_me"),
            ),
            DriveLocation(
                "configured",
                configured_name,
                remote,
            ),
        ]
        result = self._run(["backend", "drives", f"{remote}:"])
        try:
            shared_drives = json.loads(result.stdout or "[]")
        except json.JSONDecodeError as exc:
            raise RcloneError("Google returned an invalid Shared Drive list") from exc
        for item in shared_drives:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            drive_id = str(item["id"])
            name = str(item.get("name") or drive_id)
            locations.append(
                DriveLocation(
                    f"shared_drive:{drive_id}",
                    f"Shared Drive · {name}",
                    google_scoped_remote(remote, "shared_drive", drive_id),
                )
            )
        return locations

    def _configured_google_root_name(self, remote: str) -> str:
        """Describe the effective base root without decrypting OAuth tokens.

        A Google rclone remote may itself be pinned to a Shared Drive.  Calling
        that endpoint merely a "previously configured root" made it look like
        My Drive and allowed users to select the wrong tree.  rclone's redacted
        configuration preserves option presence while replacing credentials
        and identifiers, which is sufficient to identify the root type without
        bringing an OAuth token or a Shared Drive ID into this process.
        """
        try:
            result = self._run(["config", "redacted"])
            parser = configparser.ConfigParser(interpolation=None)
            parser.read_string(result.stdout or "")
            if not parser.has_section(remote):
                return "Configured Google Drive root"
            values = parser[remote]
            shared_with_me = values.get("shared_with_me", "").strip().lower()
            if shared_with_me in {"true", "1", "yes"}:
                return "Configured root · Shared with me"
            if values.get("team_drive", "").strip():
                return "Configured root · Shared Drive"
            root_folder = values.get("root_folder_id", "").strip()
            if not root_folder or root_folder == "root":
                return "Configured root · My Drive"
            return "Configured root · Google Drive folder"
        except (RcloneError, configparser.Error):
            return "Configured Google Drive root"

    def public_link(self, remote_spec: str) -> str:
        result = self._run(["link", remote_spec])
        link = result.stdout.strip()
        if not link.startswith("https://"):
            raise RcloneError("The provider did not return a secure HTTPS share link")
        return link

    def online_url(self, remote_spec: str, provider: Provider) -> tuple[str, bool]:
        """Return a non-sharing provider URL and whether it targets the exact item."""
        remote_name, _, raw_path = remote_spec.partition(":")
        remote_path = raw_path.strip("/")
        if provider is Provider.DROPBOX:
            suffix = f"/{quote(remote_path, safe='/')}" if remote_path else ""
            return f"https://www.dropbox.com/home{suffix}", True

        metadata: dict[str, Any] = {}
        if remote_path and provider in {Provider.GOOGLE_DRIVE, Provider.ONEDRIVE, Provider.BOX}:
            try:
                result = self._run(["lsjson", remote_spec, "--stat", "--no-mimetype", "--no-modtime"])
                metadata = json.loads(result.stdout or "{}")
            except (RcloneError, json.JSONDecodeError):
                metadata = {}
        # Some Google Drive/rclone combinations omit ID from an lsjson --stat
        # response even though normal directory listings contain it. Resolve
        # the selected item from its direct parent before falling back to the
        # provider home page. The scoped remote name is preserved, so this also
        # works for My Drive, Shared with me, and Shared Drives.
        if provider is Provider.GOOGLE_DRIVE and remote_path and not metadata.get("ID"):
            parent, _, child = remote_path.rpartition("/")
            parent_spec = f"{remote_name}:{parent}" if parent else f"{remote_name}:"
            try:
                result = self._run([
                    "lsjson", parent_spec, "--max-depth", "1",
                    "--no-mimetype", "--no-modtime",
                ])
                entries = json.loads(result.stdout or "[]")
                if isinstance(entries, list):
                    metadata = next(
                        (
                            item for item in entries
                            if isinstance(item, dict)
                            and str(item.get("Name") or item.get("Path") or "").strip("/") == child
                            and item.get("ID")
                        ),
                        {},
                    )
            except (RcloneError, json.JSONDecodeError):
                metadata = {}
        item_id = str(metadata.get("ID", "")).strip()
        is_dir = bool(metadata.get("IsDir", True))
        if item_id and provider is Provider.GOOGLE_DRIVE:
            return (
                f"https://drive.google.com/drive/folders/{quote(item_id, safe='')}"
                if is_dir else f"https://drive.google.com/open?id={quote(item_id, safe='')}",
                True,
            )
        if item_id and provider is Provider.BOX and is_dir:
            return f"https://app.box.com/folder/{quote(item_id, safe='')}", True
        if item_id and provider is Provider.ONEDRIVE:
            return f"https://onedrive.live.com/?id={quote(item_id, safe='!')}", True
        return provider.home_url, False

    def about(self, remote: str) -> dict[str, Any]:
        self._validate_remote_name(remote)
        result = self._run(["about", f"{remote}:", "--json"])
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {}

    def _configuration_step(self, args: list[str], session_id: str = "") -> ConfigResult:
        result = self._run_oauth(args, session_id, timeout=600)
        output = result.stdout.strip()
        if not output:
            self._secure_config_permissions()
            self._ensure_config_security(force=True)
            return ConfigResult(complete=True)
        try:
            value = json.loads(output)
        except json.JSONDecodeError:
            # Some successful backend configurations print informational text.
            self._secure_config_permissions()
            self._ensure_config_security(force=True)
            return ConfigResult(complete=True)
        state = value.get("State", "")
        option = value.get("Option")
        if not state or not option:
            self._secure_config_permissions()
            self._ensure_config_security(force=True)
            return ConfigResult(complete=True)
        return ConfigResult(
            complete=False,
            question=ConfigQuestion(
                state=state,
                name=option.get("Name", "option"),
                help=option.get("Help", ""),
                default=option.get("Default", ""),
                examples=option.get("Examples") or [],
                required=bool(option.get("Required")),
                secret=bool(option.get("IsPassword")),
                exclusive=bool(option.get("Exclusive")),
                error=value.get("Error", ""),
            ),
        )

    def _run_oauth(
        self, args: list[str], session_id: str, timeout: int
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            self.ensure_available()
        if "--continue" in args and self._callback_port_busy():
            raise RcloneError(
                "The OAuth callback port (127.0.0.1:53682) is already in use. "
                "Close the earlier TuxInDrive/rclone authorization attempt, then try again."
            )
        environment = os.environ.copy()
        environment.setdefault("LC_ALL", "C.UTF-8")
        with self._oauth_guard:
            if self._oauth_process is not None and self._oauth_process.poll() is None:
                raise RcloneError("Another cloud authorization is already in progress.")
            process = spawn_process(
                [self.executable, *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=environment,
                **new_process_group(),
                **({"preexec_fn": _protect_sensitive_child} if platform.system() == "Linux" else {}),
            )
            self._oauth_process = process
            self._oauth_session = session_id
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self.cancel_oauth(session_id)
            raise RcloneError("Authorization timed out. Please try again.") from exc
        finally:
            with self._oauth_guard:
                if self._oauth_process is process:
                    self._oauth_process = None
                    self._oauth_session = None
        if process.returncode:
            raise RcloneError(self._friendly_oauth_error(stderr or stdout))
        return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)

    def cancel_oauth(self, session_id: str) -> None:
        """Stop only the authorization process owned by the requesting wizard."""
        with self._oauth_guard:
            process = self._oauth_process
            if process is None or self._oauth_session != session_id or process.poll() is not None:
                return
            try:
                terminate_process(process)
            except ProcessLookupError:
                return
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                terminate_process(process, force=True)
            except ProcessLookupError:
                pass

    @staticmethod
    def _callback_port_busy() -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.15)
            return probe.connect_ex(("127.0.0.1", 53682)) == 0

    @staticmethod
    def _friendly_oauth_error(message: str) -> str:
        text = message.strip()
        if "address already in use" in text.lower():
            return (
                "The OAuth callback port (127.0.0.1:53682) is already in use. "
                "Close the earlier TuxInDrive/rclone authorization attempt, then try again."
            )
        meaningful = [line.strip() for line in text.splitlines() if line.strip()]
        for line in reversed(meaningful):
            if line.lower().startswith(("fatal error:", "error:")):
                return line[:500]
        return (meaningful[0] if meaningful else "Cloud authorization failed")[:500]

    @staticmethod
    def _secure_config_permissions() -> None:
        path = rclone_config_path()
        if path.is_file():
            os.chmod(path, 0o600)
            os.chmod(path.parent, 0o700)

    def _ensure_config_security(self, force: bool = False) -> None:
        if self._config_security_checked and not force:
            return
        config = rclone_config_path()
        system = platform.system()
        default_helper = (
            "/Applications/TuxInDrive.app/Contents/Resources/rclone-password"
            if system == "Darwin" else
            str(Path(sys.executable).with_name("tuxindrive-rclone-password.exe"))
            if system == "Windows" else
            "/usr/lib/tuxindrive/rclone-password"
        )
        helper = Path(
            os.environ.get("TUXINDRIVE_PASSWORD_HELPER")
            or os.environ.get("TUXDRIVE_PASSWORD_HELPER")
            or default_helper
        )
        marker = config.parent / ".tuxindrive-encrypted"
        legacy_marker = config.parent / ".tuxdrive-encrypted"
        if marker.is_file() or legacy_marker.is_file():
            os.environ["RCLONE_PASSWORD_COMMAND"] = str(helper)
            self._config_security_checked = True
            return
        if not config.is_file() or not config.read_bytes().strip():
            return
        if config.read_bytes().startswith(b"RCLONE_ENCRYPT_V"):
            # Respect configurations encrypted independently by an advanced user.
            self._config_security_checked = True
            return
        if not helper.is_file() or not os.access(helper, os.X_OK):
            return
        ensured = run_process(
            [str(helper), "--ensure"], capture_output=True, text=True, timeout=30, check=False,
            **({"preexec_fn": _protect_sensitive_child} if platform.system() == "Linux" else {}),
        )
        if ensured.returncode:
            raise RcloneError("Could not store the rclone configuration key in the system credential store")
        environment = os.environ.copy()
        environment["RCLONE_PASSWORD_COMMAND"] = str(helper)
        result = run_process(
            [self.executable, "config", "encryption", "set", "--password-command", str(helper)],
            capture_output=True, text=True, timeout=30, check=False, env=environment,
            **({"preexec_fn": _protect_sensitive_child} if platform.system() == "Linux" else {}),
        )
        if result.returncode:
            raise RcloneError("Could not encrypt the rclone credential configuration")
        marker.touch(mode=0o600, exist_ok=True)
        os.chmod(marker, 0o600)
        os.environ["RCLONE_PASSWORD_COMMAND"] = str(helper)
        self._config_security_checked = True

    def _run(
        self,
        args: Iterable[str],
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if not self.available():
            try:
                self.ensure_available()
            except Exception as exc:
                raise RcloneError(str(exc)) from exc
        environment = os.environ.copy()
        environment.setdefault("LC_ALL", "C.UTF-8")
        try:
            return run_process(
                [self.executable, *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            raise RcloneError("The cloud operation timed out") from exc
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or exc.stdout or "rclone operation failed").strip()
            raise RcloneError(message) from exc

    @staticmethod
    def _validate_remote_name(remote: str) -> None:
        if not remote or any(character in remote for character in ":/\\\n\r\t"):
            raise ValueError("Remote names cannot contain spaces, slashes, colons, or control characters")
        if " " in remote:
            raise ValueError("Remote names cannot contain spaces")

    @staticmethod
    def _remote_spec(remote: str, path: str) -> str:
        value = str(path or "").strip().strip("/")
        parts = Path(value).parts
        if any(part in {".", ".."} for part in parts) or "\x00" in value:
            raise ValueError("Cloud folder paths cannot contain traversal components")
        return f"{remote}:{value}" if value else f"{remote}:"


def rclone_config_path() -> Path:
    configured = os.environ.get("RCLONE_CONFIG")
    if configured:
        return Path(configured)
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "rclone" / "rclone.conf"


def google_scoped_remote(remote: str, kind: str, drive_id: str = "") -> str:
    """Build an rclone connection string without copying OAuth credentials."""
    if kind == "my_drive":
        return f"{remote},team_drive=,root_folder_id=root,shared_with_me=false"
    if kind == "shared_with_me":
        return f"{remote},team_drive=,root_folder_id=root,shared_with_me=true"
    if kind == "shared_drive" and drive_id:
        return f"{remote},team_drive={drive_id},root_folder_id=,shared_with_me=false"
    return remote
