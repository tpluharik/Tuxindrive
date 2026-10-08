from tests import signal_safety as _signal_safety  # noqa: F401

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tuxindrive.engine import SyncEngine
from tuxindrive.github_sync import (
    GitHubSyncError,
    parse_repository_url,
    repositories_match,
    repository_item_url,
    validate_branch,
)
from tuxindrive.models import SyncJob, SyncMode


class GitHubSyncTests(unittest.TestCase):
    class _RedirectResponse:
        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def geturl(self):
            return self.url

    def test_repository_urls_reject_embedded_tokens_and_non_github_hosts(self):
        self.assertEqual(parse_repository_url("git@github.com:owner/repo.git").name, "repo")
        self.assertEqual(parse_repository_url("https://github.com/owner/repo.git").owner, "owner")
        for value in (
            "https://token@github.com/owner/repo.git",
            "https://gitlab.com/owner/repo.git",
            "file:///tmp/repo",
        ):
            with self.assertRaises(GitHubSyncError):
                parse_repository_url(value)

    def test_branch_and_item_url_are_confined(self):
        self.assertEqual(validate_branch("feature/offline"), "feature/offline")
        with self.assertRaises(GitHubSyncError):
            validate_branch("../main")
        self.assertEqual(
            repository_item_url("https://github.com/owner/repo.git", "main", "docs/User Guide.md"),
            "https://github.com/owner/repo/tree/main/docs/User%20Guide.md",
        )

    def test_repository_comparison_accepts_only_matching_github_rename_redirects(self):
        old = parse_repository_url("https://github.com/owner/old-name.git")
        renamed = parse_repository_url("https://github.com/owner/new-name.git")
        unrelated = parse_repository_url("https://github.com/owner/other.git")
        with patch(
            "tuxindrive.github_sync.urllib.request.urlopen",
            side_effect=[
                self._RedirectResponse("https://github.com/owner/new-name"),
                self._RedirectResponse("https://github.com/owner/new-name"),
            ],
        ):
            self.assertTrue(repositories_match(old, renamed))
        with patch(
            "tuxindrive.github_sync.urllib.request.urlopen",
            side_effect=[
                self._RedirectResponse("https://github.com/owner/new-name"),
                self._RedirectResponse("https://github.com/owner/other"),
            ],
        ):
            self.assertFalse(repositories_match(old, unrelated))

    def test_download_sync_persists_canonical_origin_after_repository_rename(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            job = SyncJob(
                account_remote="github-repo",
                local_path=str(root),
                repository_url="https://github.com/owner/old-name.git",
                repository_branch="main",
                mode=SyncMode.DOWNLOAD_ONLY,
            )
            engine = SyncEngine()
            with patch("tuxindrive.engine.shutil.which", return_value="/usr/bin/git"), \
                 patch.object(engine, "_git_output", side_effect=[
                     "https://github.com/owner/new-name.git", "main",
                     "bbbb refs/heads/main", "aaaa",
                 ]), \
                 patch("tuxindrive.engine.repositories_match", return_value=True), \
                 patch.object(engine, "_git_dirty", return_value=False), \
                 patch.object(engine, "_run_git_process", return_value=0):
                result = engine._run_git_sync(job, root / "sync.log", False)
        self.assertTrue(result.success)
        self.assertEqual(
            job.repository_url,
            "https://github.com/owner/new-name.git",
        )

    def test_two_way_sync_stages_fetches_rebases_and_pushes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            job = SyncJob(
                account_remote="github-repo",
                local_path=str(root),
                repository_url="https://github.com/owner/repo.git",
                repository_branch="main",
                mode=SyncMode.TWO_WAY,
                git_author_name="TuxInDrive Test",
                git_author_email="test@example.invalid",
            )
            engine = SyncEngine()
            commands = []

            def run(_job, command, _cwd, _log, _environment):
                commands.append(command)
                return 0

            with patch("tuxindrive.engine.shutil.which", return_value="/usr/bin/git"), \
                 patch.object(engine, "_run_git_process", side_effect=run), \
                 patch.object(
                     engine,
                     "_git_output",
                     side_effect=["https://github.com/owner/repo.git", "main", "1"],
                 ), \
                 patch(
                     "tuxindrive.engine.subprocess.run",
                     side_effect=[
                         MagicMock(returncode=0, stdout="", stderr=""),
                         MagicMock(returncode=1, stdout="", stderr=""),
                     ],
                 ):
                result = engine._run_git_sync(job, root / "sync.log", False)
        self.assertTrue(result.success)
        self.assertTrue(any(command[3:5] == ["add", "-A"] for command in commands))
        self.assertTrue(any("commit" in command for command in commands))
        self.assertTrue(any("fetch" in command for command in commands))
        self.assertTrue(any("rebase" in command for command in commands))
        self.assertTrue(any("push" in command for command in commands))

    def test_two_way_sync_skips_push_when_branch_is_not_ahead(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".git").mkdir()
            job = SyncJob(
                account_remote="github-repo", local_path=str(root),
                repository_url="https://github.com/owner/repo.git",
                repository_branch="main", mode=SyncMode.TWO_WAY,
            )
            engine = SyncEngine()
            commands = []

            def run(_job, command, _cwd, _log, _environment):
                commands.append(command)
                return 0

            with patch("tuxindrive.engine.shutil.which", return_value="/usr/bin/git"), \
                 patch.object(engine, "_run_git_process", side_effect=run), \
                 patch.object(engine, "_git_changes", return_value=[]), \
                 patch.object(
                     engine, "_git_output",
                     side_effect=["https://github.com/owner/repo.git", "main", "0"],
                 ):
                result = engine._run_git_sync(job, root / "sync.log", False)
        self.assertTrue(result.success)
        self.assertFalse(any("push" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
