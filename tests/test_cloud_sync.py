"""Unit tests for cloud_sync module (mocked subprocess, no rclone needed)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hledger_textual.cloud_sync import (
    CloudSyncError,
    cloud_sync_download,
    cloud_sync_upload,
    has_rclone,
    run_rclone,
)


def test_run_rclone_not_found():
    """run_rclone raises CloudSyncError when rclone is not installed."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(CloudSyncError, match="rclone not found"):
            run_rclone("version")


def test_run_rclone_timeout():
    """run_rclone raises CloudSyncError on timeout."""
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("rclone", 60)):
        with pytest.raises(CloudSyncError, match="timed out"):
            run_rclone("copy", "src", "dst")


def test_run_rclone_command_failure():
    """run_rclone raises CloudSyncError when rclone returns non-zero."""
    exc = subprocess.CalledProcessError(1, "rclone", stderr="permission denied")
    with patch("subprocess.run", side_effect=exc):
        with pytest.raises(CloudSyncError, match="permission denied"):
            run_rclone("copy", "src", "dst")


def test_run_rclone_success():
    """run_rclone returns stdout on success."""
    mock_result = MagicMock()
    mock_result.stdout = "rclone v1.65.0"
    with patch("subprocess.run", return_value=mock_result):
        result = run_rclone("version")
        assert result == "rclone v1.65.0"


def test_run_rclone_sets_env():
    """run_rclone sets RCLONE_ASK_PASSWORD=false to prevent hanging."""
    mock_result = MagicMock()
    mock_result.stdout = ""
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        run_rclone("version")
        call_kwargs = mock_run.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env", {})
        assert env.get("RCLONE_ASK_PASSWORD") == "false"


def test_has_rclone_true():
    """has_rclone returns True when rclone is available."""
    mock_result = MagicMock()
    mock_result.stdout = "rclone v1.65.0"
    with patch("subprocess.run", return_value=mock_result):
        assert has_rclone() is True


def test_has_rclone_false():
    """has_rclone returns False when rclone is not installed."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert has_rclone() is False


def test_cloud_sync_upload(tmp_path):
    """cloud_sync_upload calls rclone copy with correct arguments."""
    journal = tmp_path / "test.journal"
    journal.write_text("2026-01-01 test\n")
    config = {"remote": "gdrive", "path": "hledger-backup"}

    mock_result = MagicMock()
    mock_result.stdout = ""
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = cloud_sync_upload(journal, config)

    assert "gdrive:hledger-backup" in result
    # Verify rclone was called with copy command
    call_args = mock_run.call_args[0][0]
    assert call_args[0] == "rclone"
    assert "copy" in call_args


def test_cloud_sync_download(tmp_path):
    """cloud_sync_download calls rclone copy and creates backup."""
    journal = tmp_path / "test.journal"
    journal.write_text("2026-01-01 test\n")
    config = {"remote": "gdrive", "path": "hledger-backup"}

    mock_result = MagicMock()
    mock_result.stdout = ""
    with patch("subprocess.run", return_value=mock_result):
        result = cloud_sync_download(journal, config)

    assert "gdrive:hledger-backup" in result


def test_cloud_sync_download_failure_restores_backup(tmp_path):
    """A failed download restores the local journal and cleans the backup."""
    from unittest.mock import patch

    from hledger_textual.cloud_sync import CloudSyncError, cloud_sync_download

    journal = tmp_path / "test.journal"
    journal.write_text("original\n", encoding="utf-8")
    config = {"remote": "gdrive", "path": "backup"}

    def _fail(*args, **kwargs):
        raise CloudSyncError("network down")

    with patch("hledger_textual.cloud_sync.run_rclone", side_effect=_fail):
        with pytest.raises(CloudSyncError, match="network down"):
            cloud_sync_download(journal, config)

    assert journal.read_text(encoding="utf-8") == "original\n"
    assert list(tmp_path.glob("*.bak")) == []
