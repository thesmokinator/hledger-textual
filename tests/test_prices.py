"""Tests for the prices module (pricehist integration)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from hledger_textual.prices import (
    PriceError,
    _cache_path,
    fetch_prices,
    get_prices_file,
    has_pricehist,
    prices_are_fresh,
)


class TestHasPricehist:
    """Tests for has_pricehist."""

    def test_true_when_in_venv(self):
        """Returns True when pricehist is in the venv bin directory."""
        assert has_pricehist() is True

    def test_false_when_not_found(self):
        """Returns False when pricehist is not on PATH or in venv."""
        import sys
        with patch("shutil.which", return_value=None):
            with patch("hledger_textual.prices.Path") as mock_path:
                # Make venv_bin.exists() return False
                mock_path.return_value.parent.__truediv__.return_value.exists.return_value = False
                # Bypass the sys.executable path resolution by patching _pricehist_path
                from hledger_textual import prices
                original = prices._pricehist_path
                prices._pricehist_path = lambda: None
                try:
                    assert prices.has_pricehist() is False
                finally:
                    prices._pricehist_path = original


class TestPricesAreFresh:
    """Tests for prices_are_fresh."""

    def test_false_when_cache_missing(self, tmp_path, monkeypatch):
        """Returns False when the cache file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.prices._cache_path",
            lambda: tmp_path / "nonexistent.journal",
        )
        assert prices_are_fresh() is False

    def test_true_when_cache_written_today(self, tmp_path, monkeypatch):
        """Returns True when the cache file was written today."""
        cache = tmp_path / "prices.journal"
        cache.write_text("P 2026-02-26 00:00:00 XDWD 125.00 EUR\n")
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)
        assert prices_are_fresh() is True

    def test_false_when_cache_is_old(self, tmp_path, monkeypatch):
        """Returns False when the cache file is from a previous day."""
        cache = tmp_path / "prices.journal"
        cache.write_text("P 2020-01-01 00:00:00 XDWD 80.00 EUR\n")
        old_date = date(2020, 1, 1)
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)
        with patch("hledger_textual.prices.date") as mock_date:
            mock_date.today.return_value = date(2026, 2, 26)
            mock_date.fromtimestamp.return_value = old_date
            assert prices_are_fresh() is False


class TestFetchPrices:
    """Tests for fetch_prices."""

    def test_raises_when_pricehist_missing(self, tmp_path, monkeypatch):
        """Raises PriceError when pricehist is not available."""
        monkeypatch.setattr("hledger_textual.prices._pricehist_path", lambda: None)
        with pytest.raises(PriceError, match="pricehist not found"):
            fetch_prices({"XDWD": "XDWD.DE"})

    def test_writes_cache_file(self, tmp_path, monkeypatch):
        """Writes a cache file and returns its path."""
        cache = tmp_path / "prices.journal"
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)

        fake_output = "P 2026-02-26 00:00:00 XDWD 125.01 EUR\n"

        def fake_run(cmd, **kwargs):
            class Result:
                stdout = fake_output
                returncode = 0
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)
        result = fetch_prices({"XDWD": "XDWD.DE"})
        assert result == cache
        assert "P 2026-02-26" in cache.read_text()

    def test_skips_failed_tickers(self, tmp_path, monkeypatch):
        """Tickers that raise CalledProcessError are silently skipped."""
        import subprocess
        cache = tmp_path / "prices.journal"
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)

        def fake_run(cmd, **kwargs):
            raise subprocess.CalledProcessError(1, cmd)

        monkeypatch.setattr("subprocess.run", fake_run)
        result = fetch_prices({"UNKNOWN": "UNKNOWN.XX"})
        assert result == cache
        assert cache.read_text() == ""

    def test_fmt_base_flag_in_command(self, tmp_path, monkeypatch):
        """The --fmt-base flag renames the commodity in the output."""
        cache = tmp_path / "prices.journal"
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)

        captured: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            captured.append(cmd)
            class Result:
                stdout = "P 2026-02-26 00:00:00 XDWD 125.01 EUR\n"
                returncode = 0
            return Result()

        monkeypatch.setattr("subprocess.run", fake_run)
        fetch_prices({"XDWD": "XDWD.DE"})
        assert "--fmt-base" in captured[0]
        assert "XDWD" in captured[0]
        assert "XDWD.DE" in captured[0]


class TestGetPricesFile:
    """Tests for get_prices_file."""

    def test_returns_none_when_no_tickers(self):
        """Returns None when tickers dict is empty."""
        assert get_prices_file({}) is None

    def test_returns_none_when_pricehist_missing(self, monkeypatch):
        """Returns None when pricehist is not available."""
        monkeypatch.setattr("hledger_textual.prices.has_pricehist", lambda: False)
        assert get_prices_file({"XDWD": "XDWD.DE"}) is None

    def test_returns_cache_when_fresh(self, tmp_path, monkeypatch):
        """Returns the existing cache file when it is fresh."""
        cache = tmp_path / "prices.journal"
        cache.write_text("P 2026-02-26 XDWD 125.00 EUR\n")
        monkeypatch.setattr("hledger_textual.prices.has_pricehist", lambda: True)
        monkeypatch.setattr("hledger_textual.prices.prices_are_fresh", lambda: True)
        monkeypatch.setattr("hledger_textual.prices._cache_path", lambda: cache)
        result = get_prices_file({"XDWD": "XDWD.DE"})
        assert result == cache

    def test_fetches_when_cache_stale(self, tmp_path, monkeypatch):
        """Calls fetch_prices when cache is stale."""
        cache = tmp_path / "prices.journal"
        monkeypatch.setattr("hledger_textual.prices.has_pricehist", lambda: True)
        monkeypatch.setattr("hledger_textual.prices.prices_are_fresh", lambda: False)
        monkeypatch.setattr("hledger_textual.prices.fetch_prices", lambda t: cache)
        result = get_prices_file({"XDWD": "XDWD.DE"})
        assert result == cache

    def test_returns_none_on_price_error(self, monkeypatch):
        """Returns None when fetch_prices raises PriceError."""
        monkeypatch.setattr("hledger_textual.prices.has_pricehist", lambda: True)
        monkeypatch.setattr("hledger_textual.prices.prices_are_fresh", lambda: False)

        def _raise(t):
            raise PriceError("failed")

        monkeypatch.setattr("hledger_textual.prices.fetch_prices", _raise)
        assert get_prices_file({"XDWD": "XDWD.DE"}) is None
