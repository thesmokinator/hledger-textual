"""Tests for the git module."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from hledger_textual.git import (
    GitError,
    git_branch,
    git_status_summary,
    git_sync,
    is_git_repo,
    run_git,
)

pytestmark = pytest.mark.skipif(
    not shutil.which("git"), reason="git not installed"
)


def _init_repo(path: Path) -> Path:
    """Initialize a git repo at *path* with an initial commit and return it."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path, check=True, capture_output=True,
    )
    # Initial commit so HEAD exists
    readme = path / "README.md"
    readme.write_text("init\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=path, check=True, capture_output=True,
    )
    return path


def _init_repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create a local repo with a bare remote. Returns (local, remote)."""
    bare = tmp_path / "remote.git"
    bare.mkdir()
    subprocess.run(
        ["git", "init", "--bare"], cwd=bare, check=True, capture_output=True,
    )

    local = _init_repo(tmp_path / "local")
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=local, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=local, check=True, capture_output=True,
    )
    return local, bare


# ------------------------------------------------------------------
# run_git
# ------------------------------------------------------------------


class TestRunGit:
    """Tests for the run_git wrapper."""

    def test_successful_command(self, tmp_path: Path):
        """run_git returns stdout for a valid command."""
        repo = _init_repo(tmp_path / "repo")
        output = run_git("status", "--short", cwd=repo)
        assert isinstance(output, str)

    def test_bad_command_raises(self, tmp_path: Path):
        """run_git raises GitError for an invalid git subcommand."""
        repo = _init_repo(tmp_path / "repo")
        with pytest.raises(GitError, match="git command failed"):
            run_git("nonsense-subcommand", cwd=repo)

    def test_git_not_found(self, tmp_path: Path, monkeypatch):
        """run_git raises GitError when git binary is missing."""
        monkeypatch.setenv("PATH", "")
        with pytest.raises(GitError, match="git not found"):
            run_git("status", cwd=tmp_path)


# ------------------------------------------------------------------
# is_git_repo
# ------------------------------------------------------------------


class TestIsGitRepo:
    """Tests for is_git_repo."""

    def test_true_inside_git_dir(self, tmp_path: Path):
        """Returns True when the journal is in a git repo."""
        repo = _init_repo(tmp_path / "repo")
        journal = repo / "test.journal"
        journal.write_text("")
        assert is_git_repo(journal) is True

    def test_false_outside_git_dir(self, tmp_path: Path):
        """Returns False when the directory is not a git repo."""
        plain = tmp_path / "plain"
        plain.mkdir()
        journal = plain / "test.journal"
        journal.write_text("")
        assert is_git_repo(journal) is False


# ------------------------------------------------------------------
# git_branch
# ------------------------------------------------------------------


class TestGitBranch:
    """Tests for git_branch."""

    def test_returns_branch_name(self, tmp_path: Path):
        """Returns the current branch name."""
        repo = _init_repo(tmp_path / "repo")
        journal = repo / "test.journal"
        journal.write_text("")
        branch = git_branch(journal)
        assert branch in ("main", "master")

    def test_detached_head(self, tmp_path: Path):
        """Returns 'detached' when HEAD is detached."""
        repo = _init_repo(tmp_path / "repo")
        # Detach HEAD by checking out a commit hash
        subprocess.run(
            ["git", "checkout", "--detach", "HEAD"],
            cwd=repo, check=True, capture_output=True,
        )
        journal = repo / "test.journal"
        journal.write_text("")
        assert git_branch(journal) == "detached"


# ------------------------------------------------------------------
# git_status_summary
# ------------------------------------------------------------------


class TestGitStatusSummary:
    """Tests for git_status_summary."""

    def test_clean_repo(self, tmp_path: Path):
        """Returns 'Clean' when there are no changes."""
        repo = _init_repo(tmp_path / "repo")
        journal = repo / "test.journal"
        journal.write_text("")
        subprocess.run(
            ["git", "add", "."], cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add journal"],
            cwd=repo, check=True, capture_output=True,
        )
        assert git_status_summary(journal) == "Clean"

    def test_modified_file(self, tmp_path: Path):
        """Returns a count when files are modified."""
        repo = _init_repo(tmp_path / "repo")
        journal = repo / "test.journal"
        journal.write_text("initial")
        subprocess.run(
            ["git", "add", "."], cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add journal"],
            cwd=repo, check=True, capture_output=True,
        )
        journal.write_text("modified")
        summary = git_status_summary(journal)
        assert "1 changed file" in summary

    def test_multiple_modified(self, tmp_path: Path):
        """Returns plural count for multiple changed files."""
        repo = _init_repo(tmp_path / "repo")
        (repo / "a.txt").write_text("a")
        (repo / "b.txt").write_text("b")
        subprocess.run(
            ["git", "add", "."], cwd=repo, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add files"],
            cwd=repo, check=True, capture_output=True,
        )
        (repo / "a.txt").write_text("aa")
        (repo / "b.txt").write_text("bb")
        journal = repo / "test.journal"
        journal.write_text("")
        summary = git_status_summary(journal)
        assert "changed files" in summary


# ------------------------------------------------------------------
# git_sync
# ------------------------------------------------------------------


class TestGitSync:
    """Tests for the full git_sync flow."""

    def test_sync_commits_and_pushes(self, tmp_path: Path):
        """Full sync: commit + push to remote."""
        local, _bare = _init_repo_with_remote(tmp_path)
        journal = local / "test.journal"
        journal.write_text("2026-01-01 Test\n    expenses  €10\n    assets\n")

        result = git_sync(journal)
        assert "Committed and pushed" in result

        # Verify the commit exists
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=local, capture_output=True, text=True, check=True,
        )
        assert "Update journal" in log.stdout

    def test_sync_nothing_to_commit(self, tmp_path: Path):
        """When there are no changes, sync still pulls and pushes."""
        local, _bare = _init_repo_with_remote(tmp_path)
        journal = local / "test.journal"
        journal.write_text("")
        subprocess.run(
            ["git", "add", "."], cwd=local, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "add journal"],
            cwd=local, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"], cwd=local, check=True, capture_output=True,
        )

        result = git_sync(journal)
        assert "Nothing to commit" in result

    def test_sync_stages_budget_file(self, tmp_path: Path):
        """Budget file is staged alongside the journal when it exists."""
        local, _bare = _init_repo_with_remote(tmp_path)
        journal = local / "test.journal"
        journal.write_text("journal content")
        budget = local / "budget.journal"
        budget.write_text("budget content")

        result = git_sync(journal)
        assert "Committed and pushed" in result

        # Verify both files are in the commit
        show = subprocess.run(
            ["git", "show", "--stat", "HEAD"],
            cwd=local, capture_output=True, text=True, check=True,
        )
        assert "budget.journal" in show.stdout
        assert "test.journal" in show.stdout

    def test_sync_conflict_aborts_rebase(self, tmp_path: Path):
        """Rebase conflict triggers abort and raises GitError."""
        local, bare = _init_repo_with_remote(tmp_path)

        # Create a conflicting commit on a second clone
        clone2 = tmp_path / "clone2"
        subprocess.run(
            ["git", "clone", str(bare), str(clone2)],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=clone2, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=clone2, check=True, capture_output=True,
        )
        conflict_file = clone2 / "README.md"
        conflict_file.write_text("conflicting content\n")
        subprocess.run(
            ["git", "add", "."], cwd=clone2, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "conflict"],
            cwd=clone2, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "push"], cwd=clone2, check=True, capture_output=True,
        )

        # Now modify the same file locally
        readme = local / "README.md"
        readme.write_text("local change that conflicts\n")
        journal = local / "README.md"  # Use README.md as the "journal" for conflict

        with pytest.raises(GitError, match="Rebase conflict"):
            git_sync(journal)

    def test_sync_push_fails_no_remote(self, tmp_path: Path):
        """GitError raised when push fails (no remote configured)."""
        repo = _init_repo(tmp_path / "repo")
        journal = repo / "test.journal"
        journal.write_text("content")

        with pytest.raises(GitError):
            git_sync(journal)
