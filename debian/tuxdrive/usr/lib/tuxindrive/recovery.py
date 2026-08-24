from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .callbacks import FileChange
from .config import data_root
from .models import SyncJob
from .security import confined_path, install_confined, unlink_confined, copy_from_confined
from .bandwidth import GlobalBandwidthController


class SafetyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryEntry:
    job_id: str
    relative_path: str
    stored_path: str
    created_at: str
    reason: str
    size: int

    @classmethod
    def from_dict(cls, value: dict) -> "RecoveryEntry":
        return cls(**{key: value[key] for key in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class AuditIssue:
    symbol: str
    path: str

    @property
    def description(self) -> str:
        return {
            "*": "Different content",
            # rclone check --combined compares source (local) with destination
            # (cloud): '+' is missing from source and '-' from destination.
            "+": "Only on cloud/peer side",
            "-": "Only on local side",
            "!": "Could not verify",
        }.get(self.symbol, "Difference")


@dataclass(frozen=True, slots=True)
class MassChangeDecision:
    blocked: bool
    reason: str = ""


class RecoveryManager:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_root() / "recovery"

    def archive_local(self, job: SyncJob, relative: str, reason: str) -> RecoveryEntry | None:
        relative = self._safe_relative(relative)
        source = confined_path(job.local, relative)
        if not source.is_file():
            return None
        timestamp = datetime.now(timezone.utc)
        token = timestamp.strftime("%Y%m%dT%H%M%S.%fZ")
        destination = self.root / job.id / token / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        copy_from_confined(job.local, relative, destination)
        entry = RecoveryEntry(
            job.id,
            relative,
            str(destination),
            timestamp.isoformat(),
            reason,
            destination.stat().st_size,
        )
        self._append(entry)
        return entry

    def archive_incoming_changes(self, job: SyncJob, changes: Iterable[FileChange]) -> list[RecoveryEntry]:
        if not job.version_history:
            return []
        archived = []
        for change in changes:
            if change.side == "remote":
                entry = self.archive_local(
                    job, change.path, "remote deletion" if change.deleted else "remote replacement"
                )
                if entry:
                    archived.append(entry)
        self.prune(job)
        return archived

    def entries(self, job_id: str) -> list[RecoveryEntry]:
        index = self.root / job_id / "index.jsonl"
        if not index.is_file():
            return []
        values: list[RecoveryEntry] = []
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entry = RecoveryEntry.from_dict(json.loads(line))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if Path(entry.stored_path).is_file():
                values.append(entry)
        return sorted(values, key=lambda item: item.created_at, reverse=True)

    def restore(self, job: SyncJob, entry: RecoveryEntry) -> Path:
        source = Path(entry.stored_path)
        if not source.is_file() or entry.job_id != job.id:
            raise SafetyError("The selected recovery version is no longer available")
        relative = self._safe_relative(entry.relative_path)
        destination = confined_path(job.local, relative, create_parents=True)
        if destination.is_file():
            self.archive_local(job, entry.relative_path, "replaced during manual restore")
        installed = install_confined(source, job.local, relative)
        return installed

    @staticmethod
    def _safe_relative(value: str) -> str:
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            raise SafetyError("Recovery refused an unsafe file path")
        return path.as_posix()

    def prune(self, job: SyncJob) -> int:
        if job.version_retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=job.version_retention_days)
        removed = 0
        keep = []
        for entry in self.entries(job.id):
            try:
                created = datetime.fromisoformat(entry.created_at)
            except ValueError:
                keep.append(entry)
                continue
            if created < cutoff:
                try:
                    Path(entry.stored_path).unlink(missing_ok=True)
                    removed += 1
                except OSError:
                    keep.append(entry)
            else:
                keep.append(entry)
        self._rewrite(job.id, keep)
        return removed

    def _append(self, entry: RecoveryEntry) -> None:
        index = self.root / entry.job_id / "index.jsonl"
        index.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(index, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.__dict__ if hasattr(entry, "__dict__") else {
                field: getattr(entry, field) for field in entry.__dataclass_fields__
            }, ensure_ascii=False) + "\n")

    def _rewrite(self, job_id: str, entries: list[RecoveryEntry]) -> None:
        index = self.root / job_id / "index.jsonl"
        if not index.parent.exists():
            return
        temporary = index.with_suffix(".new")
        with temporary.open("w", encoding="utf-8") as handle:
            for entry in reversed(entries):
                handle.write(json.dumps({field: getattr(entry, field) for field in entry.__dataclass_fields__}) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, index)


class MassChangeGuard:
    SUSPICIOUS_SUFFIXES = {
        ".locked", ".encrypted", ".crypt", ".crypto", ".enc", ".lockbit",
        ".conti", ".ryuk", ".wannacry", ".blackcat",
    }

    @classmethod
    def assess(cls, job: SyncJob, changes: list[FileChange], total_files: int) -> MassChangeDecision:
        if not job.ransomware_protection or not job.initialized:
            return MassChangeDecision(False)
        changed = len({item.path for item in changes})
        deleted = sum(item.deleted for item in changes)
        suspicious = sum(Path(item.path).suffix.lower() in cls.SUSPICIOUS_SUFFIXES for item in changes)
        percent = (changed * 100 / max(1, total_files))
        reasons = []
        # Ordinary bulk edits require both configured signals. An absolute
        # count alone is noisy in large trees, while a percentage alone is
        # noisy in small folders. Destructive and encryption-shaped activity
        # remains independently blocked below.
        if (
            total_files >= 20
            and changed >= max(1, job.mass_change_limit)
            and percent >= max(1, job.mass_change_percent)
        ):
            reasons.append(
                f"{changed} paths changed ({percent:.0f}% of known files; "
                f"limits {job.mass_change_limit} and {job.mass_change_percent}%)"
            )
        if deleted > max(10, job.max_delete):
            reasons.append(f"{deleted} deletion events exceed the safety ceiling")
        if suspicious >= 5:
            reasons.append(f"{suspicious} files acquired suspicious encryption extensions")
        return MassChangeDecision(bool(reasons), "; ".join(reasons))

    @classmethod
    def assess_log(cls, job: SyncJob, log_path: Path, total_files: int) -> MassChangeDecision:
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return MassChangeDecision(False)
        changes: list[FileChange] = []
        pattern = re.compile(
            r"(?:INFO|NOTICE)\s*:\s+(.+?):\s+"
            r"(Deleted|Copied|Moved|Renamed|Skipped (?:copy|delete|move|rename).+)",
            re.I,
        )
        for line in lines:
            match = pattern.search(line)
            if match:
                action = match.group(2).lower()
                changes.append(FileChange(match.group(1), "preview", "delet" in action))
        return cls.assess(job, changes, total_files)


class IntegrityAuditor:
    def __init__(
        self,
        rclone_path: str,
        recovery: RecoveryManager,
        bandwidth: GlobalBandwidthController | None = None,
    ) -> None:
        self.rclone_path = rclone_path
        self.recovery = recovery
        self.bandwidth = bandwidth or GlobalBandwidthController()

    def audit(self, job: SyncJob, download: bool = False) -> list[AuditIssue]:
        command = [
            self.rclone_path, "check", str(job.local), job.remote_spec,
            "--combined", "-", "--checkers", "4",
            *self.bandwidth.rclone_args(job.bandwidth_limit),
        ]
        if download:
            command.append("--download")
        with self.bandwidth.guard():
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)
        if result.returncode not in (0, 1):
            raise SafetyError((result.stderr or result.stdout or "Integrity audit failed").strip()[-800:])
        issues = []
        for line in result.stdout.splitlines():
            if len(line) >= 3 and line[0] in "*+-!" and line[1] == " ":
                issues.append(AuditIssue(line[0], line[2:]))
        return issues

    def repair(self, job: SyncJob, issues: list[AuditIssue], winner: str) -> int:
        if winner not in {"local", "remote"}:
            raise SafetyError("Choose local or cloud/peer as the repair source")
        repaired = 0
        for issue in issues:
            relative = issue.path.strip("/")
            if not relative or ".." in Path(relative).parts or issue.symbol == "!":
                continue
            try:
                local = confined_path(job.local, relative, create_parents=winner == "remote")
            except ValueError:
                continue
            remote = f"{job.remote_spec.rstrip('/')}/{relative}"
            if winner == "remote":
                if issue.symbol == "-":
                    self.recovery.archive_local(job, relative, "removed by integrity repair")
                    unlink_confined(job.local, relative)
                else:
                    self.recovery.archive_local(job, relative, "replaced by integrity repair")
                    with tempfile.TemporaryDirectory(prefix="tuxindrive-repair-") as temporary:
                        staged = Path(temporary) / "incoming"
                        self._run([self.rclone_path, "copyto", remote, str(staged), *self.bandwidth.rclone_args(job.bandwidth_limit)])
                        install_confined(staged, job.local, relative)
            else:
                if issue.symbol == "+":
                    # Retain a local recovery copy before removing the remote-only file.
                    backup = self.recovery.root / job.id / "remote-repair" / relative
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    self._run([self.rclone_path, "copyto", remote, str(backup), *self.bandwidth.rclone_args(job.bandwidth_limit)])
                    self._run([self.rclone_path, "deletefile", remote, *self.bandwidth.rclone_args(job.bandwidth_limit)])
                else:
                    self._run([self.rclone_path, "copyto", str(local), remote, *self.bandwidth.rclone_args(job.bandwidth_limit)])
            repaired += 1
        return repaired

    def _run(self, command: list[str]) -> None:
        with self.bandwidth.guard():
            result = subprocess.run(command, capture_output=True, text=True, timeout=3600, check=False)
        if result.returncode:
            raise SafetyError((result.stderr or result.stdout or "Repair failed").strip()[-800:])
