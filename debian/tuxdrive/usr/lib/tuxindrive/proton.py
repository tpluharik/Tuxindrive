from __future__ import annotations

import fnmatch
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from .config import data_root
from .models import ConflictPolicy, SyncJob, SyncMode
from .security import ensure_private_directory
from .process_control import new_process_group, terminate_process
from .file_permissions import private_descriptor


class ProtonDriveError(RuntimeError):
    """A safe, user-facing failure from the official Proton Drive CLI."""


PROTON_CLI_MANIFEST = "https://proton.me/download/drive/cli/index.html"
_MAX_MANIFEST_BYTES = 1 * 1024 * 1024
_MAX_CLI_BYTES = 256 * 1024 * 1024


class _ProtonManifestParser(HTMLParser):
    """Collect links and checksums from Proton's small release table."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._links: list[str] | None = None
        self._text: list[str] = []
        self.rows: list[tuple[list[str], str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._links = []
            self._text = []
        elif tag == "a" and self._links is not None:
            href = dict(attrs).get("href")
            if href:
                self._links.append(href)

    def handle_data(self, data: str) -> None:
        if self._links is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "tr" and self._links is not None:
            self.rows.append((self._links, " ".join(self._text)))
            self._links = None
            self._text = []


@dataclass(frozen=True, slots=True)
class ProtonNode:
    name: str
    path: str
    is_dir: bool
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ProtonSyncResult:
    uploaded: int
    downloaded: int
    remote_items: int
    local_items: int


def _safe_name(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("value", "") if value.get("ok", True) else ""
    name = str(value or "")
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or any(ord(character) < 32 for character in name)
    ):
        raise ProtonDriveError("Proton Drive returned an unsafe file or folder name")
    return name


def proton_path(relative: str = "") -> str:
    """Map a TuxInDrive relative path into Proton CLI's /my-files namespace."""
    value = str(relative or "").replace("\\", "/").strip("/")
    parts = value.split("/") if value else []
    if any(
        part in {"", ".", ".."}
        or any(ord(character) < 32 for character in part)
        for part in parts
    ):
        raise ProtonDriveError("The Proton Drive path is invalid")
    return "/my-files" + ("/" + "/".join(parts) if parts else "")


class ProtonDriveClient:
    """Auditable adapter for Proton's official browser-authenticated CLI.

    The CLI owns authentication and encryption. TuxInDrive forces the supported
    OS keychain store and never reads, writes, exports, or logs the session.
    """

    def __init__(self, executable: str = "proton-drive") -> None:
        self.executable = executable
        self._login_lock = threading.Lock()
        self._login_process: subprocess.Popen[str] | None = None
        self._cancelled_jobs: set[str] = set()
        self._install_cancel = threading.Event()
        self._tree_cache: dict[str, dict[str, ProtonNode]] = {}

    @staticmethod
    def managed_path() -> Path:
        return data_root() / "tools" / "proton-drive"

    def resolve(self) -> str:
        candidate = self.executable
        resolved = (
            str(Path(candidate).expanduser())
            if os.path.sep in candidate
            else shutil.which(candidate)
        )
        managed = self.managed_path()
        if (not resolved or not Path(resolved).is_file()) and managed.is_file():
            resolved = str(managed)
        if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
            raise ProtonDriveError(
                "Official Proton Drive CLI is not installed. Choose Install CLI and connect; "
                "TuxInDrive will download it from Proton and verify Proton's SHA-512 checksum."
            )
        self.executable = resolved
        return resolved

    def available(self) -> bool:
        try:
            self.resolve()
            return True
        except ProtonDriveError:
            return False

    def install(self) -> Path:
        """Install Proton's verified release in TuxInDrive's private user data.

        The manifest and binary are fetched over HTTPS. Redirected binary data
        is trusted only after it matches the SHA-512 value from Proton's own
        manifest; partial or mismatched downloads are never made executable.
        """
        platform_name = self._platform_name()
        try:
            manifest_response = self._open_url(PROTON_CLI_MANIFEST)
            try:
                manifest_url = self._validated_manifest_url(manifest_response.geturl())
                manifest = self._read_limited(
                    manifest_response, _MAX_MANIFEST_BYTES, "Proton CLI manifest"
                ).decode("utf-8", errors="strict")
            finally:
                manifest_response.close()
        except (OSError, UnicodeError, urllib.error.URLError) as exc:
            raise ProtonDriveError("Could not securely read Proton's CLI release manifest") from exc
        download_url, expected = self._manifest_entry(
            manifest, manifest_url, platform_name
        )

        root = self.managed_path().parent
        if root.is_symlink():
            raise ProtonDriveError("The private Proton CLI directory cannot be a symbolic link")
        ensure_private_directory(root)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="proton-drive-", suffix=".download", dir=root
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha512()
        received = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                response = self._open_url(download_url)
                try:
                    final_url = urllib.parse.urlparse(response.geturl())
                    if final_url.scheme != "https":
                        raise ProtonDriveError("Proton CLI download was redirected outside HTTPS")
                    length = response.headers.get("Content-Length") if response.headers else None
                    if length:
                        try:
                            if int(length) > _MAX_CLI_BYTES:
                                raise ProtonDriveError("Proton CLI download exceeded the safety limit")
                        except ValueError:
                            raise ProtonDriveError("Proton CLI download returned an invalid length") from None
                    while True:
                        if self._install_cancel.is_set():
                            raise ProtonDriveError("Proton CLI installation was cancelled")
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > _MAX_CLI_BYTES:
                            raise ProtonDriveError("Proton CLI download exceeded the safety limit")
                        digest.update(chunk)
                        output.write(chunk)
                finally:
                    response.close()
                output.flush()
                os.fsync(output.fileno())
                private_descriptor(output.fileno(), 0o700)
            if not received:
                raise ProtonDriveError("Proton CLI download was empty")
            if not hmac.compare_digest(digest.hexdigest(), expected):
                raise ProtonDriveError(
                    "Proton CLI checksum verification failed; the downloaded file was discarded"
                )
            target = self.managed_path()
            os.replace(temporary, target)
            os.chmod(target, 0o700)
            directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            self.executable = str(target)
            return target
        except (OSError, UnicodeError, urllib.error.URLError) as exc:
            raise ProtonDriveError("Could not securely install the official Proton Drive CLI") from exc
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def install_and_login(self) -> None:
        self._install_cancel.clear()
        if not self.available():
            self.install()
        if self._install_cancel.is_set():
            raise ProtonDriveError("Proton authorization was cancelled")
        self.login()

    @staticmethod
    def _platform_name() -> str:
        machine = platform.machine().lower()
        if machine in {"x86_64", "amd64"}:
            return "linux-x64"
        if machine in {"aarch64", "arm64"}:
            return "linux-arm64"
        raise ProtonDriveError(
            f"Proton Drive CLI is unavailable for this processor architecture: {machine or 'unknown'}"
        )

    @staticmethod
    def _validated_manifest_url(value: str) -> str:
        parsed = urllib.parse.urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "proton.me"
            or parsed.path != "/download/drive/cli/index.html"
            or parsed.username
            or parsed.password
        ):
            raise ProtonDriveError("Proton CLI manifest was redirected to an untrusted location")
        return value

    @staticmethod
    def _manifest_entry(manifest: str, manifest_url: str, platform_name: str) -> tuple[str, str]:
        parser = _ProtonManifestParser()
        parser.feed(manifest)
        matches: list[tuple[str, str]] = []
        for links, text in parser.rows:
            checksums = re.findall(r"(?i)\b[0-9a-f]{128}\b", text)
            for href in links:
                url = urllib.parse.urljoin(manifest_url, href)
                parsed = urllib.parse.urlparse(url)
                if (
                    parsed.scheme == "https"
                    and parsed.hostname == "proton.me"
                    and parsed.path.startswith("/download/drive/cli/")
                    and parsed.path.endswith(f"/{platform_name}/proton-drive")
                    and not parsed.query
                    and not parsed.fragment
                    and len(checksums) == 1
                ):
                    matches.append((url, checksums[0].lower()))
        if len(matches) != 1:
            raise ProtonDriveError(
                f"Proton's CLI manifest has no unambiguous {platform_name} release"
            )
        return matches[0]

    @staticmethod
    def _open_url(url: str):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "TuxInDrive Proton CLI installer"},
        )
        return urllib.request.urlopen(request, timeout=60)

    @staticmethod
    def _read_limited(response, limit: int, label: str) -> bytes:
        length = response.headers.get("Content-Length") if response.headers else None
        if length:
            try:
                if int(length) > limit:
                    raise ProtonDriveError(f"{label} exceeded the safety limit")
            except ValueError:
                raise ProtonDriveError(f"{label} returned an invalid length") from None
        value = response.read(limit + 1)
        if len(value) > limit:
            raise ProtonDriveError(f"{label} exceeded the safety limit")
        return value

    def version(self) -> str:
        return self._run(["version"], timeout=30).stdout.strip()

    def login(self) -> None:
        """Open Proton's browser flow and wait for its Secret Service session."""
        executable = self.resolve()
        with self._login_lock:
            if self._login_process and self._login_process.poll() is None:
                raise ProtonDriveError("A Proton browser authorization is already in progress")
            process = subprocess.Popen(
                [executable, "auth", "login"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                **new_process_group(),
                env=self._environment(),
            )
            self._login_process = process
        try:
            stdout, stderr = process.communicate(timeout=600)
        except subprocess.TimeoutExpired as exc:
            self._terminate(process)
            raise ProtonDriveError("Proton browser authorization timed out; no session was accepted") from exc
        finally:
            with self._login_lock:
                if self._login_process is process:
                    self._login_process = None
        if process.returncode:
            detail = self._safe_error(stderr or stdout)
            raise ProtonDriveError(detail or "Proton browser authorization failed")
        self.validate_session()

    def cancel_login(self) -> None:
        self._install_cancel.set()
        with self._login_lock:
            process = self._login_process
        if process and process.poll() is None:
            self._terminate(process)

    def logout(self) -> None:
        self._run(["auth", "logout"], timeout=60)

    def validate_session(self) -> None:
        self._json(["filesystem", "list", "/my-files", "--json"], timeout=120)

    def list_directories(self, _remote: str, remote_path: str = "") -> list[str]:
        nodes = self._list(proton_path(remote_path))
        return sorted(item.name for item in nodes if item.is_dir)

    def remote_snapshot(
        self, remote_path: str = "", *, job_id: str = "", force: bool = False
    ) -> dict[str, str]:
        return {
            relative: node.fingerprint
            for relative, node in self.remote_tree(
                remote_path, job_id=job_id, force=force
            ).items()
        }

    def remote_tree(
        self, remote_path: str = "", *, job_id: str = "", force: bool = False
    ) -> dict[str, ProtonNode]:
        root = proton_path(remote_path)
        tree: dict[str, ProtonNode] = {}
        cached = self._tree_cache.get(job_id, {}) if job_id and not force else {}
        pending: list[tuple[str, str]] = [(root, "")]
        while pending:
            parent, relative_parent = pending.pop()
            for node in self._list(parent, job_id=job_id):
                relative = f"{relative_parent}/{node.name}".strip("/")
                tree[relative] = node
                if node.is_dir:
                    prior = cached.get(relative)
                    if prior is not None and prior.fingerprint == node.fingerprint:
                        prefix = relative + "/"
                        tree.update({
                            path: item for path, item in cached.items()
                            if path.startswith(prefix)
                        })
                    else:
                        pending.append((node.path, relative))
        if job_id:
            self._tree_cache[job_id] = dict(tree)
        return tree

    def sync(
        self,
        job: SyncJob,
        *,
        process_callback: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> ProtonSyncResult:
        if job.mode is SyncMode.VIRTUAL_DRIVE:
            raise ProtonDriveError(
                "Proton files-on-demand is unavailable because the official CLI has no mount API"
            )
        configured_local = job.local.expanduser()
        if configured_local.is_symlink():
            raise ProtonDriveError("The Proton synchronization root cannot be a symbolic link")
        local = configured_local.resolve(strict=False)
        local.mkdir(parents=True, exist_ok=True)
        if not local.is_dir() or local.is_symlink():
            raise ProtonDriveError("The Proton synchronization root must be a real local directory")
        remote_root = proton_path(job.remote_path)
        before_remote_tree = self.remote_tree(job.remote_path, job_id=job.id)
        before_remote = {
            relative: node.fingerprint for relative, node in before_remote_tree.items()
        }
        before_local = self.local_snapshot(job)
        previous = self._load_state(job.id)
        self._guard_mass_change(job, before_local, before_remote, previous)

        upload_plan, download_plan = self._transfer_plan(
            job, before_local, before_remote, previous
        )
        uploaded = downloaded = 0
        # Download conflict copies first. A following merge upload then keeps
        # the original local file as the new revision while preserving the
        # downloaded remote variant under the CLI-selected available name.
        for strategy, relatives in sorted(download_plan.items()):
            downloaded += self._download_children(
                before_remote_tree, local, strategy, job, process_callback, relatives
            )
        for strategy, relatives in sorted(upload_plan.items()):
            uploaded += self._upload_children(
                local, remote_root, before_remote_tree, strategy, job, process_callback, relatives
            )

        after_local = self.local_snapshot(job)
        # A true no-op cannot have changed Proton Drive. Reusing the guarded
        # snapshot avoids a second recursive provider traversal while the next
        # scheduled run still observes any later remote change normally.
        after_remote = (
            before_remote
            if not upload_plan and not download_plan
            else self.remote_snapshot(job.remote_path, job_id=job.id, force=True)
        )
        self._save_state(job.id, {"local": after_local, "remote": after_remote})
        return ProtonSyncResult(uploaded, downloaded, len(after_remote), len(after_local))

    def cancel(self, job_id: str) -> None:
        self._cancelled_jobs.add(job_id)

    def local_snapshot(self, job: SyncJob) -> dict[str, str]:
        root = job.local.resolve(strict=False)
        snapshot: dict[str, str] = {}
        if not root.exists():
            return snapshot
        for path in root.rglob("*"):
            try:
                relative = path.relative_to(root).as_posix()
                if self._excluded(relative, job.exclude_patterns) or path.is_symlink():
                    continue
                stat = path.stat()
            except (OSError, ValueError):
                continue
            kind = "d" if path.is_dir() else "f"
            snapshot[relative] = f"{kind}:{stat.st_size}:{stat.st_mtime_ns}"
        return snapshot

    def _list(self, path: str, *, job_id: str = "") -> list[ProtonNode]:
        raw = self._json(["filesystem", "list", path, "--json"], timeout=180, job_id=job_id)
        if not isinstance(raw, list):
            raise ProtonDriveError("Proton Drive returned an unexpected directory listing")
        nodes: list[ProtonNode] = []
        for item in raw:
            if not isinstance(item, dict):
                raise ProtonDriveError("Proton Drive returned an invalid directory entry")
            name = _safe_name(item.get("name"))
            is_dir = item.get("type") in {"folder", "directory"}
            revision = item.get("activeRevision") if isinstance(item.get("activeRevision"), dict) else {}
            fingerprint = ":".join(
                json.dumps(value, sort_keys=True, default=str) if isinstance(value, (dict, list)) else str(value or "")
                for value in (
                "d" if is_dir else "f",
                revision.get("claimedSize") or item.get("size"),
                revision.get("claimedDigests") or item.get("modificationTime"),
                item.get("uid"),
                )
            )
            nodes.append(ProtonNode(name, f"{path.rstrip('/')}/{name}", is_dir, fingerprint))
        return nodes

    def _download_children(
        self,
        remote_tree: dict[str, ProtonNode],
        local: Path,
        strategy: str,
        job: SyncJob,
        process_callback: Callable[[subprocess.Popen[str]], None] | None,
        relatives: set[str],
    ) -> int:
        self._assert_symlink_free(local)
        files_by_parent: dict[str, list[ProtonNode]] = {}
        for relative, node in remote_tree.items():
            if relative not in relatives:
                continue
            if self._excluded(relative, job.exclude_patterns):
                continue
            if node.is_dir:
                self._safe_local_directory(local, relative)
            else:
                files_by_parent.setdefault(str(Path(relative).parent), []).append(node)
        transferred = 0
        for parent, nodes in sorted(files_by_parent.items()):
            destination = local if parent == "." else self._safe_local_directory(local, parent)
            self._run(
                [
                    "filesystem", "download", *(item.path for item in nodes), str(destination),
                    "--conflict-strategy", strategy, "--json",
                ],
                timeout=24 * 3600,
                job_id=job.id,
                process_callback=process_callback,
            )
            transferred += len(nodes)
        return transferred

    def _upload_children(
        self,
        local: Path,
        remote_root: str,
        remote_tree: dict[str, ProtonNode],
        strategy: str,
        job: SyncJob,
        process_callback: Callable[[subprocess.Popen[str]], None] | None,
        relatives: set[str],
    ) -> int:
        self._assert_symlink_free(local)
        remote_dirs = {
            relative for relative, node in remote_tree.items() if node.is_dir
        }
        directories: list[str] = []
        files_by_parent: dict[str, list[Path]] = {}
        for path in local.rglob("*"):
            relative = path.relative_to(local).as_posix()
            if self._excluded(relative, job.exclude_patterns):
                continue
            if path.is_dir():
                if any(item == relative or item.startswith(relative + "/") for item in relatives):
                    directories.append(relative)
            elif path.is_file() and relative in relatives:
                files_by_parent.setdefault(str(Path(relative).parent), []).append(path)
        for relative in sorted(directories, key=lambda value: (value.count("/"), value)):
            if relative in remote_dirs:
                continue
            parent = str(Path(relative).parent)
            remote_parent = remote_root if parent == "." else f"{remote_root}/{parent}"
            self._run(
                ["filesystem", "create-folder", remote_parent, Path(relative).name, "--json"],
                timeout=180,
                job_id=job.id,
                process_callback=process_callback,
            )
            remote_dirs.add(relative)
        transferred = 0
        for parent, paths in sorted(files_by_parent.items()):
            remote_parent = remote_root if parent == "." else f"{remote_root}/{parent}"
            self._run(
                [
                    "filesystem", "upload", *(str(path) for path in paths), remote_parent,
                    "--conflict-strategy", strategy, "--skip-thumbnails", "--json",
                ],
                timeout=24 * 3600,
                job_id=job.id,
                process_callback=process_callback,
            )
            transferred += len(paths)
        return transferred

    @staticmethod
    def _assert_symlink_free(root: Path) -> None:
        if root.is_symlink():
            raise ProtonDriveError("The Proton synchronization root cannot be a symbolic link")
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ProtonDriveError(
                    f"Proton synchronization paused because a symbolic link is present: {path.relative_to(root)}"
                )

    @staticmethod
    def _safe_local_directory(root: Path, relative: str) -> Path:
        parts = Path(relative).parts
        if not parts or ".." in parts or Path(relative).is_absolute():
            raise ProtonDriveError("Proton Drive returned an unsafe local destination")
        current = root
        for part in parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise ProtonDriveError("A symbolic link blocks the Proton download destination")
            current.mkdir(exist_ok=True)
        resolved_root = root.resolve(strict=True)
        resolved = current.resolve(strict=True)
        if resolved != resolved_root and resolved_root not in resolved.parents:
            raise ProtonDriveError("The Proton download destination escaped its local root")
        return current

    def _json(self, args: list[str], *, timeout: int, job_id: str = "") -> object:
        result = self._run(args, timeout=timeout, job_id=job_id)
        try:
            return json.loads(result.stdout or "null")
        except json.JSONDecodeError as exc:
            raise ProtonDriveError("Proton Drive returned invalid machine-readable output") from exc

    def _run(
        self,
        args: Iterable[str],
        *,
        timeout: int,
        job_id: str = "",
        process_callback: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        executable = self.resolve()
        if job_id and job_id in self._cancelled_jobs:
            self._cancelled_jobs.discard(job_id)
            raise ProtonDriveError("Proton synchronization was cancelled")
        process = subprocess.Popen(
            [executable, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **new_process_group(),
            env=self._environment(),
        )
        if process_callback:
            process_callback(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._terminate(process)
            raise ProtonDriveError("The Proton Drive operation timed out") from exc
        if process.returncode:
            detail = self._safe_error(stderr or stdout)
            lower = detail.lower()
            if any(marker in lower for marker in ("not authenticated", "unauthorized", "session", "login")):
                raise ProtonDriveError(
                    "Proton authorization expired. Open the account menu and choose Reconnect in browser."
                )
            raise ProtonDriveError(detail or "The Proton Drive operation failed")
        return subprocess.CompletedProcess([executable, *args], process.returncode, stdout, stderr)

    @staticmethod
    def _environment() -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("PROTON_DRIVE_CACHE_DIR", None)
        environment["PROTON_DRIVE_CREDENTIALS_STORE"] = "keychain"
        environment["PROTON_DRIVE_LOG_LEVEL"] = "WARNING"
        environment.setdefault("LC_ALL", "C.UTF-8")
        return environment

    @staticmethod
    def _safe_error(value: str) -> str:
        # Do not reflect URLs, tokens, cookies, or multiline debug payloads to
        # logs/UI. Official CLI errors are useful after this conservative trim.
        lines = []
        for line in str(value or "").splitlines():
            cleaned = re.sub(r"https?://\S+", "[authorization URL omitted]", line).strip()
            cleaned = re.sub(r"(?i)(token|cookie|session|authorization)\s*[:=]\s*\S+", r"\1=[redacted]", cleaned)
            if cleaned:
                lines.append(cleaned[:500])
        return " ".join(lines[-3:])[:1000]

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        try:
            terminate_process(process)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                terminate_process(process, force=True)
            except ProcessLookupError:
                pass

    @staticmethod
    def _excluded(relative: str, patterns: Iterable[str]) -> bool:
        defaults = (".Trash-*", "*.part", "~$*", ".goutputstream-*", ".nfs*")
        value = relative.strip("/")
        parts = value.split("/") if value else []
        if any(fnmatch.fnmatch(part, pattern) for part in parts for pattern in defaults):
            return True
        prefixes = ["/".join(parts[:index]) for index in range(1, len(parts) + 1)]
        return any(
            fnmatch.fnmatch(candidate, normalized)
            for pattern in patterns
            if (normalized := pattern.strip().lstrip("/"))
            for candidate in prefixes
        )

    @staticmethod
    def _transfer_plan(
        job: SyncJob,
        local: dict[str, str],
        remote: dict[str, str],
        previous: dict[str, dict[str, str]],
    ) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
        """Choose changed file paths without interpreting unlike fingerprints."""
        uploads: dict[str, set[str]] = defaultdict(set)
        downloads: dict[str, set[str]] = defaultdict(set)
        previous_local = previous.get("local", {})
        previous_remote = previous.get("remote", {})
        for relative in sorted(set(local) | set(remote)):
            local_value = local.get(relative)
            remote_value = remote.get(relative)
            local_file = bool(local_value and local_value.startswith("f:"))
            remote_file = bool(remote_value and remote_value.startswith("f:"))
            if local_value and remote_value and local_file != remote_file:
                raise ProtonDriveError(
                    f"Proton synchronization paused: file/folder type conflict at {relative}"
                )
            if not local_file and not remote_file:
                continue
            if job.mode is SyncMode.UPLOAD_ONLY:
                if local_file and (
                    not remote_file or previous_local.get(relative) != local_value
                ):
                    uploads["merge"].add(relative)
                continue
            if job.mode is SyncMode.DOWNLOAD_ONLY:
                if remote_file and (
                    not local_file or previous_remote.get(relative) != remote_value
                ):
                    downloads["replace"].add(relative)
                continue
            if local_file and not remote_file:
                uploads["merge"].add(relative)
                continue
            if remote_file and not local_file:
                downloads["replace"].add(relative)
                continue
            local_changed = previous_local.get(relative) != local_value
            remote_changed = previous_remote.get(relative) != remote_value
            if not local_changed and not remote_changed:
                continue
            if local_changed and not remote_changed:
                uploads["merge"].add(relative)
            elif remote_changed and not local_changed:
                downloads["replace"].add(relative)
            elif job.conflict_policy is ConflictPolicy.LOCAL_WINS:
                uploads["merge"].add(relative)
            elif job.conflict_policy is ConflictPolicy.CLOUD_WINS:
                downloads["replace"].add(relative)
            else:
                downloads["keep-both"].add(relative)
                uploads["merge"].add(relative)
        return dict(uploads), dict(downloads)

    def _state_path(self, job_id: str) -> Path:
        root = data_root() / "proton-sync"
        ensure_private_directory(root)
        return root / f"{job_id}.json"

    def _load_state(self, job_id: str) -> dict[str, dict[str, str]]:
        path = self._state_path(job_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                return {}
            return {
                side: {str(key): str(item) for key, item in entries.items()}
                for side, entries in value.items()
                if side in {"local", "remote"} and isinstance(entries, dict)
            }
        except (OSError, ValueError, TypeError):
            return {}

    def _save_state(self, job_id: str, value: dict[str, dict[str, str]]) -> None:
        path = self._state_path(job_id)
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
        descriptor, temporary = tempfile.mkstemp(prefix="proton-state-", suffix=".json", dir=path.parent)
        try:
            private_descriptor(descriptor)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _guard_mass_change(
        job: SyncJob,
        local: dict[str, str],
        remote: dict[str, str],
        previous: dict[str, dict[str, str]],
    ) -> None:
        if not job.ransomware_protection or not job.initialized or not previous:
            return
        directions = []
        if job.mode in {SyncMode.TWO_WAY, SyncMode.UPLOAD_ONLY}:
            directions.append(("local", local, previous.get("local", {})))
        if job.mode in {SyncMode.TWO_WAY, SyncMode.DOWNLOAD_ONLY}:
            directions.append(("cloud", remote, previous.get("remote", {})))
        for label, current, earlier in directions:
            changed = sum(1 for key in set(current) | set(earlier) if current.get(key) != earlier.get(key))
            percent = int(changed * 100 / max(len(earlier), 1))
            if changed >= job.mass_change_limit and percent >= job.mass_change_percent:
                raise ProtonDriveError(
                    f"Protection paused Proton synchronization: {changed} {label} paths changed ({percent}%)."
                )
