"""Configuration resolution for hledger-textual.

Priority order (highest to lowest):
1. --file / -f CLI argument
2. LEDGER_FILE environment variable
3. ~/.config/hledger-textual/config.toml -> journal_file key
4. ~/.hledger.journal (default)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_CONFIG_PATH = Path.home() / ".config" / "hledger-textual" / "config.toml"

# Matches a hledger `commodity` directive, e.g.:
#   commodity €1,000.00      -> captures "€"
#   commodity 0.0000 XEON    -> captures "XEON"
_COMMODITY_DIRECTIVE_RE = re.compile(
    r"^commodity\s+(?:([^\d\s.,;-]+)[\d\s.,]*|[-\d\s.,]*([^\d\s.,;]+))\s*$"
)

# Matches an `include` directive, capturing the included path.
_INCLUDE_RE = re.compile(r'^include\s+([^;]+?)\s*(?:;.*)?$')


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
    import re as _re

    def _toml_key(k: str) -> str:
        """Return a TOML-safe key, quoting it if it contains non-bare characters."""
        if _re.fullmatch(r"[A-Za-z0-9_-]+", k):
            return k
        return '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'

    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    sections: dict[str, dict] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            sections[key] = value
        else:
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{_toml_key(key)} = "{escaped}"')
    for section_name, section_dict in sections.items():
        lines.append(f"\n[{_toml_key(section_name)}]")
        for k, v in section_dict.items():
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{_toml_key(k)} = "{escaped}"')
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


def load_default_commodity() -> str:
    """Return the configured default commodity symbol, or ``"$"`` if not set.

    Returns:
        Commodity string (e.g. ``"€"``, ``"$"``).
    """
    return _load_config_dict().get("default_commodity", "$")


def load_configured_default_commodity() -> str | None:
    """Return the explicitly configured default commodity, or ``None`` if unset.

    Unlike :func:`load_default_commodity`, this returns ``None`` when the
    ``default_commodity`` key is absent from config.toml.  Callers that
    should only convert currencies on explicit opt-in (e.g. the Accounts
    pane) use this; callers with established ``"$"``-default behaviour
    (e.g. the Reports pane) use :func:`load_default_commodity`.

    Returns:
        Commodity string (e.g. ``"€"``), or ``None`` when not configured.
    """
    return _load_config_dict().get("default_commodity")


def _first_commodity_directive(path: Path, *, _seen: frozenset[Path] = frozenset()) -> str | None:
    """Return the first ``commodity`` directive's unit in a journal, following includes.

    Reads the journal's text directly (no hledger invocation), scans lines in
    order, and follows ``include`` directives breadth-first when the main file
    declares nothing.  Cycles are guarded by the ``_seen`` set.  Comment lines
    (``;`` / ``#``) are ignored because the directive regex anchors at column 0
    on the word ``commodity``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    if path in _seen:
        return None
    _seen = _seen | {path}

    include_paths: list[Path] = []
    for line in text.splitlines():
        m = _COMMODITY_DIRECTIVE_RE.match(line)
        if m:
            return m.group(1) or m.group(2)
        inc = _INCLUDE_RE.match(line)
        if inc:
            include_paths.append(path.parent / inc.group(1))

    for included in include_paths:
        found = _first_commodity_directive(included, _seen=_seen)
        if found:
            return found
    return None


def resolve_default_commodity(journal_file: str | Path) -> str | None:
    """Resolve the default commodity, ledger-first then config.

    Uses the first ``commodity`` directive declared in the journal (following
    ``include`` directives).  Falls back to the ``default_commodity`` key in
    config.toml.  Returns ``None`` when neither is set — in which case callers
    should not convert (raw multi-currency display).

    Args:
        journal_file: Path to the top-level journal file.

    Returns:
        Commodity string (e.g. ``"€"``, ``"XEON"``), or ``None`` when
        undeclared and unconfigured.
    """
    declared = _first_commodity_directive(Path(journal_file))
    if declared:
        return declared
    return load_configured_default_commodity()


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


def load_saved_filters() -> dict[str, str]:
    """Return saved named search filters from config.toml.

    Reads the ``[filters]`` section, where each key is a display name and
    each value is an hledger query string.

    Returns:
        A dict mapping filter name → hledger query string.
        Returns an empty dict when no ``[filters]`` section exists.
    """
    config = _load_config_dict()
    filters = config.get("filters", {})
    return {str(k): str(v) for k, v in filters.items()}


def save_filter(name: str, query: str) -> None:
    """Save a named search filter to config.toml.

    Args:
        name: Display name for the filter.
        query: hledger query string to save.
    """
    data = _load_config_dict()
    if "filters" not in data:
        data["filters"] = {}
    data["filters"][name] = query
    _save_config_dict(data)


def delete_filter(name: str) -> None:
    """Delete a named search filter from config.toml.

    Args:
        name: The filter name to remove.  No-op if the name does not exist.
    """
    data = _load_config_dict()
    filters = data.get("filters", {})
    filters.pop(name, None)
    data["filters"] = filters
    _save_config_dict(data)


def load_accounts_view() -> str:
    """Return the saved accounts view mode, or ``"flat"`` if not set.

    Returns:
        ``"flat"`` or ``"tree"``.
    """
    val = _load_config_dict().get("accounts_view", "flat")
    return val if val in ("flat", "tree") else "flat"


def save_accounts_view(view: str) -> None:
    """Persist the selected accounts view mode to config.toml.

    Args:
        view: View mode to save (``"flat"`` or ``"tree"``).
    """
    data = _load_config_dict()
    data["accounts_view"] = view
    _save_config_dict(data)


def load_auto_generate_recurring() -> bool:
    """Return whether automatic generation of recurring transactions on startup is enabled.

    Reads the ``auto_generate_recurring`` key from config.toml.
    Defaults to ``False`` when the key is absent.

    Returns:
        ``True`` if auto-generation is enabled, ``False`` otherwise.
    """
    val = _load_config_dict().get("auto_generate_recurring", False)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "1", "yes")
    return False


def load_export_dir() -> Path:
    """Return the configured export directory, or the default.

    Reads the ``[export] dir`` key from config.toml.  Falls back to
    ``~/Documents/hledger-exports/``.

    Returns:
        Resolved path to the export directory.
    """
    config = _load_config_dict()
    export = config.get("export", {})
    dir_str = export.get("dir", "") if isinstance(export, dict) else ""
    if dir_str:
        return Path(dir_str).expanduser().resolve()
    return Path.home() / "Documents" / "hledger-exports"


def load_rules_dir() -> Path | None:
    """Return the configured CSV rules directory, or ``None`` for the default.

    Reads the ``[import] rules_dir`` key from config.toml.  When ``None``
    is returned the caller should fall back to ``{journal_dir}/rules/``.

    Returns:
        Resolved path if configured, otherwise ``None``.
    """
    config = _load_config_dict()
    imp = config.get("import", {})
    dir_str = imp.get("rules_dir", "") if isinstance(imp, dict) else ""
    if dir_str:
        return Path(dir_str).expanduser().resolve()
    return None


def load_number_locale() -> str:
    """Return the configured number locale, or ``"en_US"`` if not set or invalid.

    Reads the ``number_locale`` key from config.toml. The value is
    validated against babel's locale database; any unrecognised locale string
    falls back silently to ``"en_US"``.

    Example config.toml entry::

        number_locale = "it_IT"

    Returns:
        A babel-compatible locale string such as ``"en_US"`` or ``"it_IT"``.
    """
    config = _load_config_dict()
    val = config.get("number_locale", "en_US")
    try:
        from babel import Locale
        Locale.parse(str(val))
        return str(val)
    except Exception:
        return "en_US"


def load_budget_alert_threshold() -> float | None:
    """Return the configured budget alert threshold percentage, or ``None``.

    Reads the ``[budget] alert_threshold`` key from config.toml.  When the key
    is absent or invalid, returns ``None`` (alerts disabled).

    Example config.toml entry::

        [budget]
        alert_threshold = 80

    Returns:
        A float in the range (0, 100] if configured, otherwise ``None``.
    """
    config = _load_config_dict()
    budget_section = config.get("budget", {})
    val = budget_section.get("alert_threshold") if isinstance(budget_section, dict) else None
    if val is None:
        return None
    try:
        threshold = float(val)
        return threshold if 0 < threshold <= 100 else None
    except (TypeError, ValueError):
        return None


def load_custom_reports() -> dict[str, str]:
    """Return saved custom reports from config.toml.

    Reads the ``[custom_reports]`` section, where each key is a report name and
    each value is an hledger command string (args without the ``-f`` flag).

    Returns:
        A dict mapping report name → hledger command string.
        Returns an empty dict when no ``[custom_reports]`` section exists.
    """
    config = _load_config_dict()
    reports = config.get("custom_reports", {})
    return {str(k): str(v) for k, v in reports.items()}


def save_custom_report(name: str, command: str) -> None:
    """Save a named custom report to config.toml.

    Args:
        name: Display name for the report.
        command: hledger command string (args without ``-f``).
    """
    data = _load_config_dict()
    if "custom_reports" not in data:
        data["custom_reports"] = {}
    data["custom_reports"][name] = command
    _save_config_dict(data)


def delete_custom_report(name: str) -> None:
    """Delete a named custom report from config.toml.

    Args:
        name: The report name to remove.  No-op if the name does not exist.
    """
    data = _load_config_dict()
    reports = data.get("custom_reports", {})
    reports.pop(name, None)
    data["custom_reports"] = reports
    _save_config_dict(data)


def load_sync_config() -> dict | None:
    """Return sync configuration, or None if sync is disabled.

    Reads the ``[sync]`` section from config.toml::

        [sync]
        enabled = "true"
        method = "git"           # "git" or "rclone"
        # rclone-specific:
        remote = "gdrive"
        path = "hledger-backup"

    Returns:
        A dict with at least ``enabled`` and ``method`` keys, or ``None``
        when the section is absent or ``enabled`` is not ``"true"``.
    """
    config = _load_config_dict()
    sync = config.get("sync", {})
    if not isinstance(sync, dict):
        return None
    enabled = sync.get("enabled", False)
    if isinstance(enabled, str):
        enabled = enabled.lower() in ("true", "1", "yes")
    if not enabled:
        return None
    return {k: str(v) for k, v in sync.items()}


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
        prog="hledger-textual",
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
