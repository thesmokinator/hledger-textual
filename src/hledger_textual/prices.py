"""Price fetching for investment commodities via pricehist."""

from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path


class PriceError(Exception):
    """Raised when price fetching fails or pricehist is unavailable."""


def _pricehist_path() -> str | None:
    """Return the full path to the pricehist executable, or None if not found.

    Searches the system PATH first, then the directory containing the running
    Python interpreter (i.e. the active venv's bin directory).
    """
    found = shutil.which("pricehist")
    if found:
        return found
    # Also check in the same directory as the current Python executable
    venv_bin = Path(sys.executable).parent / "pricehist"
    if venv_bin.exists():
        return str(venv_bin)
    return None


def has_pricehist() -> bool:
    """Return True if pricehist is available."""
    return _pricehist_path() is not None


def get_pricehist_version() -> str:
    """Return the pricehist version string, or '?' if unavailable."""
    path = _pricehist_path()
    if not path:
        return "?"
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        raw = result.stdout.strip()
        # Strip program name prefix: "pricehist 1.4.14" → "1.4.14"
        if raw.lower().startswith("pricehist "):
            return raw[len("pricehist "):].strip()
        return raw
    except Exception:
        return "?"


def _cache_path() -> Path:
    """Return the path to the daily prices cache file."""
    cache_dir = Path.home() / ".cache" / "hledger-textual"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "prices.journal"


def prices_are_fresh() -> bool:
    """Return True if the prices cache exists and was written today."""
    path = _cache_path()
    if not path.exists():
        return False
    mtime = date.fromtimestamp(path.stat().st_mtime)
    return mtime >= date.today()


def fetch_prices(tickers: dict[str, str]) -> Path:
    """Fetch today's prices for the given commodity → Yahoo Finance ticker mapping.

    For each entry runs::

        pricehist fetch yahoo YAHOO_TICKER -s TODAY -e TODAY -o ledger --fmt-base COMMODITY

    The ``--fmt-base`` flag ensures the output P-directive uses the journal
    commodity name (e.g. ``XDWD``) rather than the Yahoo ticker (``XDWD.DE``),
    so that hledger can match the price to the correct commodity.

    The results are written to the daily cache file.

    Args:
        tickers: Mapping from journal commodity name to Yahoo Finance ticker,
            e.g. ``{"XDWD": "XDWD.DE", "XEON": "XEON.DE"}``.

    Returns:
        Path to the written prices cache file.

    Raises:
        PriceError: If pricehist is not installed.
    """
    executable = _pricehist_path()
    if executable is None:
        raise PriceError(
            "pricehist not found. Install it with: pipx install pricehist"
        )

    today = date.today().isoformat()
    lines: list[str] = []

    for commodity, yahoo_ticker in tickers.items():
        try:
            result = subprocess.run(
                [
                    executable, "fetch", "yahoo", yahoo_ticker,
                    "-s", today, "-e", today,
                    "-o", "ledger",
                    "--fmt-base", commodity,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            for line in result.stdout.splitlines():
                if line.startswith("P "):
                    lines.append(line)
        except subprocess.CalledProcessError:
            pass  # ticker unavailable or market closed, skip silently

    cache = _cache_path()
    cache.write_text("\n".join(lines) + ("\n" if lines else ""))
    return cache


def get_prices_file(tickers: dict[str, str]) -> Path | None:
    """Return a prices cache file path, fetching if the cache is stale.

    Returns ``None`` when no tickers are configured or pricehist is unavailable.

    Args:
        tickers: Mapping from journal commodity name to Yahoo Finance ticker.

    Returns:
        Path to the prices cache file, or ``None``.
    """
    if not tickers or not has_pricehist():
        return None

    if not prices_are_fresh():
        try:
            return fetch_prices(tickers)
        except PriceError:
            return None

    path = _cache_path()
    return path if path.exists() else None
