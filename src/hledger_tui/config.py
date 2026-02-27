"""Configuration resolution for hledger-tui.

Priority order (highest to lowest):
1. --file / -f CLI argument
2. LEDGER_FILE environment variable
3. ~/.config/hledger-tui/config.toml -> journal_file key
4. ~/.hledger.journal (default)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_CONFIG_PATH = Path.home() / ".config" / "hledger-tui" / "config.toml"


def _load_config_dict() -> dict:
    """Load the full config.toml as a dict, or return empty dict on failure."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        with open(_CONFIG_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _save_config_dict(data: dict) -> None:
    """Write a config dict to config.toml, preserving nested sections.

    Top-level string values are written first, followed by any nested dict
    sections (e.g. ``[prices]``).  This avoids corrupting section-based keys
    when only a scalar value like ``theme`` is updated.
    """
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    sections: dict[str, dict] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            sections[key] = value
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key} = "{escaped}"')
    for section_name, section_dict in sections.items():
        lines.append(f"\n[{section_name}]")
        for k, v in section_dict.items():
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"')
    _CONFIG_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_theme() -> str | None:
    """Return the saved theme name, or None if not set.

    Returns:
        Theme name string (e.g. 'textual-dark'), or None.
    """
    return _load_config_dict().get("theme")


def save_theme(theme: str) -> None:
    """Persist the selected theme to config.toml.

    Args:
        theme: Theme name to save (e.g. 'nord').
    """
    data = _load_config_dict()
    data["theme"] = theme
    _save_config_dict(data)


def load_price_tickers() -> dict[str, str]:
    """Load commodity-to-ticker mappings from the ``[prices]`` section of config.toml.

    Example config.toml::

        [prices]
        XDWD = "XDWD.DE"
        XEON = "XEON.DE"

    Returns:
        A dict mapping journal commodity names to Yahoo Finance tickers.
        Returns an empty dict when no ``[prices]`` section exists.
    """
    config = _load_config_dict()
    prices = config.get("prices", {})
    return {str(k): str(v) for k, v in prices.items()}


def _load_config_toml() -> str | None:
    """Load journal_file from config.toml if it exists.

    Returns:
        The journal_file value, or None if not found.
    """
    return _load_config_dict().get("journal_file")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Arguments to parse. Defaults to sys.argv[1:].

    Returns:
        Parsed namespace with 'file' attribute.
    """
    parser = argparse.ArgumentParser(
        prog="hledger-tui",
        description="A terminal user interface for managing hledger journal transactions.",
    )
    parser.add_argument(
        "-f",
        "--file",
        help="Path to the hledger journal file.",
        default=None,
    )
    return parser.parse_args(argv)


def resolve_journal_file(cli_file: str | None = None) -> Path:
    """Resolve the journal file path using the priority chain.

    Args:
        cli_file: Value from the --file CLI argument, if provided.

    Returns:
        Resolved path to the journal file.

    Raises:
        SystemExit: If no journal file is found.
    """
    # 1. CLI argument
    if cli_file:
        path = Path(cli_file).expanduser().resolve()
        if not path.exists():
            print(f"Error: journal file not found: {path}", file=sys.stderr)
            sys.exit(1)
        return path

    # 2. LEDGER_FILE environment variable
    env_file = os.environ.get("LEDGER_FILE")
    if env_file:
        path = Path(env_file).expanduser().resolve()
        if not path.exists():
            print(f"Error: LEDGER_FILE not found: {path}", file=sys.stderr)
            sys.exit(1)
        return path

    # 3. config.toml
    toml_file = _load_config_toml()
    if toml_file:
        path = Path(toml_file).expanduser().resolve()
        if not path.exists():
            print(
                f"Error: journal file from config.toml not found: {path}",
                file=sys.stderr,
            )
            sys.exit(1)
        return path

    # 4. Default
    default_path = Path.home() / ".hledger.journal"
    if default_path.exists():
        return default_path

    print(
        "Error: no journal file found. Use -f, set LEDGER_FILE, "
        "or create ~/.hledger.journal",
        file=sys.stderr,
    )
    sys.exit(1)
