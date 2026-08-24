from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit


class GitHubSyncError(ValueError):
    pass


_BRANCH = re.compile(r"^(?![./])(?!.*(?:\.\.|//|@\{|\\|[ ~^:?*\[]))(?!.*[./]$)[A-Za-z0-9._/-]{1,200}$")
_SSH = re.compile(r"^git@github\.com:([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?$")


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    owner: str
    name: str
    clone_url: str

    @property
    def web_url(self) -> str:
        return f"https://github.com/{quote(self.owner)}/{quote(self.name)}"


def parse_repository_url(value: str) -> GitHubRepository:
    raw = value.strip()
    ssh = _SSH.fullmatch(raw)
    if ssh:
        return GitHubRepository(ssh.group(1), ssh.group(2), raw)
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise GitHubSyncError("Use an HTTPS or git@github.com repository URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port:
        raise GitHubSyncError("Repository URLs must not contain credentials, ports, queries, or fragments")
    parts = [item for item in parsed.path.split("/") if item]
    if len(parts) != 2:
        raise GitHubSyncError("Use a repository URL such as https://github.com/owner/repository.git")
    owner, name = parts
    if name.endswith(".git"):
        name = name[:-4]
    if not owner or not name or not re.fullmatch(r"[A-Za-z0-9_.-]+", owner + name):
        raise GitHubSyncError("The GitHub owner or repository name is invalid")
    return GitHubRepository(owner, name, raw)


def validate_branch(value: str) -> str:
    branch = value.strip()
    if not _BRANCH.fullmatch(branch) or branch.endswith(".lock"):
        raise GitHubSyncError("The Git branch name is invalid")
    return branch


def repositories_match(first: GitHubRepository, second: GitHubRepository) -> bool:
    """Compare repositories while honoring GitHub's verified rename redirects."""
    first_identity = (first.owner.lower(), first.name.lower())
    second_identity = (second.owner.lower(), second.name.lower())
    if first_identity == second_identity:
        return True

    def canonical_identity(repository: GitHubRepository) -> tuple[str, str]:
        request = urllib.request.Request(
            repository.web_url,
            headers={"User-Agent": "TuxInDrive-GitHub-Sync"},
            method="HEAD",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                canonical = parse_repository_url(response.geturl())
        except (OSError, urllib.error.URLError) as exc:
            raise GitHubSyncError(
                "Could not verify whether the configured GitHub repository was renamed"
            ) from exc
        return canonical.owner.lower(), canonical.name.lower()

    return canonical_identity(first) == canonical_identity(second)


def repository_item_url(repository_url: str, branch: str, relative: str = "") -> str:
    repository = parse_repository_url(repository_url)
    branch = validate_branch(branch)
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise GitHubSyncError("The repository item path is invalid")
    suffix = "/".join(quote(part, safe="") for part in relative_path.parts if part not in {"", "."})
    base = f"{repository.web_url}/tree/{quote(branch, safe='')}"
    return f"{base}/{suffix}" if suffix else base
