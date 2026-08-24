from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import FolderGroup, SyncJob


JOB_DRAG_PREFIX = "tuxindrive-job:"
MAX_JOB_DRAG_ID_LENGTH = 256


def cloud_selection_paths(selected: Iterable[str] | None = None) -> set[str]:
    """Keep cloud choices independently of the asynchronously rendered tree."""
    paths = {str(path).strip("/") for path in (selected or [])}
    return paths or {""}


def toggle_cloud_selection(current: Iterable[str], path: str, selected: bool) -> set[str]:
    """Apply one hierarchical cloud-folder toggle to persistent selection state."""
    path = path.strip("/")
    values = {str(item).strip("/") for item in current}
    if not selected:
        values.discard(path)
        return values
    values = {
        item for item in values
        if item and path and not item.startswith(path + "/") and not path.startswith(item + "/")
    }
    values.add(path)
    return values


def initial_cloud_paths(existing: SyncJob | None, account_remote: str) -> list[str]:
    """Preserve an edit path only while editing its original cloud account."""
    if existing is not None and existing.account_remote == account_remote:
        return [existing.remote_path]
    return [""]


def job_drag_payload(job_id: str) -> str:
    """Return a bounded text payload for an in-process folder-row drag."""
    if not job_id or len(job_id) > MAX_JOB_DRAG_ID_LENGTH or "\x00" in job_id:
        return ""
    return f"{JOB_DRAG_PREFIX}{job_id}"


def job_id_from_drag_payload(payload: str | bytes | None) -> str:
    """Decode only a well-formed TuxInDrive folder-row text payload."""
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    if not isinstance(payload, str) or not payload.startswith(JOB_DRAG_PREFIX):
        return ""
    job_id = payload[len(JOB_DRAG_PREFIX):]
    if not job_id or len(job_id) > MAX_JOB_DRAG_ID_LENGTH or "\x00" in job_id:
        return ""
    return job_id


def valid_group_id(group_id: str, groups: Sequence[FolderGroup]) -> str:
    """Return a persisted group id only when it still names a real group."""
    return group_id if group_id and any(group.id == group_id for group in groups) else ""


def move_job(
    jobs: list[SyncJob],
    groups: Sequence[FolderGroup],
    job_id: str,
    target_group_id: str,
    *,
    anchor_job_id: str = "",
    after: bool = False,
) -> bool:
    """Move one display entry without touching either endpoint's filesystem paths.

    ``jobs`` is the persisted display order. An anchor places the moved job before
    or after another visible entry. Dropping on a group header (no anchor) appends
    it to that group's current entries.
    """
    source = next((job for job in jobs if job.id == job_id), None)
    if source is None or (anchor_job_id and anchor_job_id == job_id):
        return False

    group_id = valid_group_id(target_group_id, groups)
    anchor = next((job for job in jobs if job.id == anchor_job_id), None)
    if anchor is not None:
        group_id = valid_group_id(anchor.group_id, groups)

    previous_group = source.group_id
    previous_index = jobs.index(source)
    jobs.pop(previous_index)
    source.group_id = group_id

    if anchor is not None and anchor in jobs:
        index = jobs.index(anchor) + (1 if after else 0)
    else:
        members = [
            index for index, job in enumerate(jobs)
            if valid_group_id(job.group_id, groups) == group_id
        ]
        index = members[-1] + 1 if members else len(jobs)
    jobs.insert(index, source)
    return previous_group != source.group_id or previous_index != jobs.index(source)
