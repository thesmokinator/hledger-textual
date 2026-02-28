"""Interface to the git CLI for syncing journal repositories."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path


class GitError(Exception):
    """Raised when a git command fails."""


def run_git(*args: str, cwd: Path) -> str:
    """Run a git command and return stdout.

    Args:
        *args: Arguments to pass to git.
        cwd: Working directory for the command.

    Returns:
        The stdout output as a string.

    Raises:
        GitError: If the command fails or git is not found.
    """
    cmd = ["git", *args]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            cwd=cwd,
            timeout=30,
            env=env,
        )
    except FileNotFoundError:
        raise GitError("git not found. Please install git.")
    except subprocess.TimeoutExpired:
        raise GitError("git command timed out")
    except subprocess.CalledProcessError as exc:
        raise GitError(f"git command failed: {exc.stderr.strip()}")
    return result.stdout


def is_git_repo(journal_file: Path) -> bool:
    """Check whether the journal file lives inside a git repository.

    Args:
        journal_file: Path to the hledger journal file.

    Returns:
        True if the journal directory is inside a git working tree.
    """
    try:
        run_git("rev-parse", "--git-dir", cwd=journal_file.parent)
        return True
    except GitError:
        return False


def git_branch(journal_file: Path) -> str:
    """Return the current git branch name.

    Args:
        journal_file: Path to the hledger journal file.

    Returns:
        The branch name, or "detached" if HEAD is detached.
    """
    try:
        name = run_git(
            "branch", "--show-current", cwd=journal_file.parent
        ).strip()
        return name or "detached"
    except GitError:
        return "?"


def git_status_summary(journal_file: Path) -> str:
    """Return a short summary of the git working tree status.

    Args:
        journal_file: Path to the hledger journal file.

    Returns:
        "Clean" when there are no changes, or a count like "3 changed files".
    """
    try:
        output = run_git("status", "--short", cwd=journal_file.parent).strip()
        if not output:
            return "Clean"
        count = len(output.splitlines())
        return f"{count} changed file{'s' if count != 1 else ''}"
    except GitError:
        return "?"


def git_sync(journal_file: Path) -> str:
    """Commit, pull, and push journal changes in one step.

    The sync flow:
    1. Stage the journal file (and budget file if present alongside).
    2. Commit if there are staged changes.
    3. Pull with rebase. On conflict, abort rebase and raise GitError.
    4. Push to remote.

    Args:
        journal_file: Path to the hledger journal file.

    Returns:
        A summary string describing what happened.

    Raises:
        GitError: If any git operation fails (including rebase conflicts).
    """
    cwd = journal_file.parent

    # Stage journal file
    run_git("add", str(journal_file), cwd=cwd)

    # Stage budget file if it exists alongside
    budget_file = cwd / "budget.journal"
    if budget_file.exists():
        run_git("add", str(budget_file), cwd=cwd)

    # Check if there is anything to commit
    committed = False
    try:
        run_git("diff", "--cached", "--quiet", cwd=cwd)
    except GitError:
        # Non-zero exit means there are staged changes
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        run_git("commit", "-m", f"Update journal ({timestamp})", cwd=cwd)
        committed = True

    # Pull with rebase
    try:
        run_git("pull", "--rebase", cwd=cwd)
    except GitError as exc:
        # Abort rebase on conflict
        try:
            run_git("rebase", "--abort", cwd=cwd)
        except GitError:
            pass
        raise GitError(
            "Rebase conflict — please resolve manually. "
            f"Details: {exc}"
        )

    # Push
    run_git("push", cwd=cwd)

    if committed:
        return "Committed and pushed successfully"
    return "Nothing to commit — pulled and pushed"
