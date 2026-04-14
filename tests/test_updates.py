"""Tests for the update check module."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from hledger_textual.updates import _CACHE_TTL, get_latest_version, is_newer


class TestIsNewer:
    """Tests for the is_newer version comparison helper."""

    def test_newer_patch(self):
        assert is_newer("0.1.8", "0.1.7") is True

    def test_newer_minor(self):
        assert is_newer("0.2.0", "0.1.9") is True

    def test_newer_major(self):
        assert is_newer("1.0.0", "0.9.9") is True

    def test_same_version(self):
        assert is_newer("0.1.7", "0.1.7") is False

    def test_older_version(self):
        assert is_newer("0.1.6", "0.1.7") is False

    def test_double_digit_patch(self):
        assert is_newer("0.1.10", "0.1.9") is True


class TestGetLatestVersion:
    """Tests for get_latest_version with mocked cache and network."""

    def test_returns_cached_version_when_fresh(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        cache_file.write_text(json.dumps({
            "latest_version": "0.1.8",
            "checked_at": datetime.now().isoformat(),
        }))
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version") as mock_fetch:
            result = get_latest_version()

        assert result == "0.1.8"
        mock_fetch.assert_not_called()

    def test_fetches_when_cache_stale(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        stale_time = datetime.now() - _CACHE_TTL - timedelta(minutes=1)
        cache_file.write_text(json.dumps({
            "latest_version": "0.1.7",
            "checked_at": stale_time.isoformat(),
        }))
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version", return_value="0.1.8"):
            result = get_latest_version()

        assert result == "0.1.8"

    def test_fetches_when_no_cache(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version", return_value="0.1.8"):
            result = get_latest_version()

        assert result == "0.1.8"

    def test_falls_back_to_stale_cache_on_network_error(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        stale_time = datetime.now() - _CACHE_TTL - timedelta(minutes=1)
        cache_file.write_text(json.dumps({
            "latest_version": "0.1.7",
            "checked_at": stale_time.isoformat(),
        }))
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version", return_value=None):
            result = get_latest_version()

        assert result == "0.1.7"

    def test_returns_none_when_no_cache_and_network_fails(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version", return_value=None):
            result = get_latest_version()

        assert result is None

    def test_writes_cache_after_fetch(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "update_check.json"
        monkeypatch.setattr("hledger_textual.updates._CACHE_PATH", cache_file)

        with patch("hledger_textual.updates._fetch_latest_version", return_value="0.1.8"):
            get_latest_version()

        data = json.loads(cache_file.read_text())
        assert data["latest_version"] == "0.1.8"
        assert "checked_at" in data
