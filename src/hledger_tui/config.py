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


def _load_config_toml() -> str | None:
    """Load journal_file from config.toml if it exists.

    Returns:
        The journal_file value, or None if not found.
    """
    config_path = Path.home() / ".config" / "hledger-tui" / "config.toml"
    if not config_path.exists():
        return None

    try:
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            import tomli as tomllib

        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("journal_file")
    except Exception:
        return None


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
