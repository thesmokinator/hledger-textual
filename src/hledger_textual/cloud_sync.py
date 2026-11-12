"""Interface to rclone for cloud-based journal backup and sync."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class CloudSyncError(Exception):
    """Raised when an rclone command fails."""


def run_rclone(*args: str, timeout: int = 60) -> str:
    """Run an rclone command and return stdout.

    Args:
        *args: Arguments to pass to rclone.
        timeout: Command timeout in seconds.

    Returns:
        The stdout output as a string.

    Raises:
        CloudSyncError: If the command fails or rclone is not found.
    """
    cmd = ["rclone", *args]
    env = {**os.environ, "RCLONE_ASK_PASSWORD": "false"}

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
        )
    except FileNotFoundError:
        raise CloudSyncError(
            "rclone not found. Install it from https://rclone.org/install/"
        )
    except subprocess.TimeoutExpired:
        raise CloudSyncError("rclone command timed out")
    except subprocess.CalledProcessError as exc:
        raise CloudSyncError(f"rclone command failed: {exc.stderr.strip()}")
    return result.stdout


def has_rclone() -> bool:
    """Check whether rclone is installed and available.

    Returns:
        True if rclone can be executed.
    """
    try:
        run_rclone("version", timeout=10)
        return True
    except CloudSyncError:
        return False


def cloud_sync_upload(journal_file: Path, config: dict) -> str:
    """Upload journal files to the configured rclone remote.

    Copies all ``*.journal`` files from the journal directory to the remote.

    Args:
        journal_file: Path to the hledger journal file.
        config: Cloud sync config dict with 'remote' and 'path' keys.

    Returns:
        A summary string describing the result.

    Raises:
        CloudSyncError: If the upload fails.
    """
    remote = config["remote"]
    remote_path = config["path"]
    journal_dir = str(journal_file.parent)
    destination = f"{remote}:{remote_path}"

    run_rclone(
        "copy",
        journal_dir,
        destination,
        "--include", "*.journal",
    )
    return f"Uploaded journal files to {destination}"


def cloud_sync_download(journal_file: Path, config: dict) -> str:
    """Download journal files from the configured rclone remote.

    Creates a backup of local files before overwriting.

    Args:
        journal_file: Path to the hledger journal file.
        config: Cloud sync config dict with 'remote' and 'path' keys.

    Returns:
        A summary string describing the result.

    Raises:
        CloudSyncError: If the download fails.
    """
    from hledger_textual.fileutil import backup, cleanup_backup, restore

    remote = config["remote"]
    remote_path = config["path"]
    journal_dir = str(journal_file.parent)
    source = f"{remote}:{remote_path}"

    # Backup local journal before downloading
    bak = backup(journal_file)

    try:
        run_rclone(
            "copy",
            source,
            journal_dir,
            "--include", "*.journal",
        )
        cleanup_backup(bak)
    except CloudSyncError:
        restore(journal_file, bak)
        cleanup_backup(bak)
        raise

    return f"Downloaded journal files from {source}"
