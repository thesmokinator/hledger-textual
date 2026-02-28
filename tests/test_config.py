"""Tests for configuration resolution."""

from pathlib import Path

import pytest

from hledger_textual.config import (
    _load_config_dict,
    _save_config_dict,
    load_default_commodity,
    load_price_tickers,
    load_theme,
    parse_args,
    resolve_journal_file,
    save_theme,
)


class TestParseArgs:
    """Tests for CLI argument parsing."""

    def test_file_short_flag(self):
        args = parse_args(["-f", "/some/file.journal"])
        assert args.file == "/some/file.journal"

    def test_file_long_flag(self):
        args = parse_args(["--file", "/some/file.journal"])
        assert args.file == "/some/file.journal"

    def test_no_args(self):
        args = parse_args([])
        assert args.file is None


class TestResolveJournalFile:
    """Tests for journal file resolution."""

    def test_cli_file_takes_priority(self, tmp_path: Path, monkeypatch):
        journal = tmp_path / "cli.journal"
        journal.write_text("")
        monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "env.journal"))

        result = resolve_journal_file(cli_file=str(journal))
        assert result == journal.resolve()

    def test_env_variable(self, tmp_path: Path, monkeypatch):
        journal = tmp_path / "env.journal"
        journal.write_text("")
        monkeypatch.setenv("LEDGER_FILE", str(journal))

        result = resolve_journal_file()
        assert result == journal.resolve()

    def test_missing_cli_file_exits(self, tmp_path: Path):
        with pytest.raises(SystemExit):
            resolve_journal_file(cli_file=str(tmp_path / "nonexistent.journal"))

    def test_missing_env_file_exits(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("LEDGER_FILE", str(tmp_path / "nonexistent.journal"))
        with pytest.raises(SystemExit):
            resolve_journal_file()

    def test_config_toml(self, tmp_path: Path, monkeypatch):
        """Test config.toml resolution."""
        journal = tmp_path / "toml.journal"
        journal.write_text("")

        config_dir = tmp_path / ".config" / "hledger-textual"
        config_dir.mkdir(parents=True)
        config_file = config_dir / "config.toml"
        config_file.write_text(f'journal_file = "{journal}"\n')

        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # _CONFIG_PATH is computed at import time, so we must patch it directly
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)

        result = resolve_journal_file()
        assert result == journal.resolve()

    def test_default_path(self, tmp_path: Path, monkeypatch):
        """Test default ~/.hledger.journal fallback."""
        journal = tmp_path / ".hledger.journal"
        journal.write_text("")

        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = resolve_journal_file()
        assert result == journal

    def test_no_file_found_exits(self, tmp_path: Path, monkeypatch):
        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        with pytest.raises(SystemExit):
            resolve_journal_file()

    def test_config_toml_missing_journal_exits(self, tmp_path: Path, monkeypatch):
        """resolve_journal_file exits when config.toml references a missing journal."""
        config_path = tmp_path / "config.toml"
        missing = tmp_path / "nonexistent.journal"
        config_path.write_text(f'journal_file = "{missing}"\n')

        monkeypatch.delenv("LEDGER_FILE", raising=False)
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)

        with pytest.raises(SystemExit):
            resolve_journal_file()


class TestLoadConfigDict:
    """Tests for the _load_config_dict private helper."""

    def test_returns_empty_dict_when_config_missing(self, tmp_path, monkeypatch):
        """Returns an empty dict when the config file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "nonexistent.toml"
        )
        assert _load_config_dict() == {}

    def test_returns_empty_dict_on_malformed_toml(self, tmp_path, monkeypatch):
        """Returns an empty dict when the TOML file is invalid."""
        bad_toml = tmp_path / "bad.toml"
        bad_toml.write_text("not valid toml === !!!")
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", bad_toml)
        assert _load_config_dict() == {}

    def test_returns_parsed_dict_from_valid_toml(self, tmp_path, monkeypatch):
        """Returns the correct dict when the TOML file is valid."""
        config = tmp_path / "config.toml"
        config.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config)
        assert _load_config_dict() == {"theme": "nord"}


class TestSaveAndLoadTheme:
    """Tests for save_theme and load_theme round-trip."""

    def test_save_theme_creates_config_file(self, tmp_path, monkeypatch):
        """save_theme creates the config file with the theme entry."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_theme("nord")
        assert config_path.exists()
        assert "nord" in config_path.read_text()

    def test_load_theme_returns_saved_value(self, tmp_path, monkeypatch):
        """load_theme returns the theme name that was previously saved."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_theme("textual-dark")
        assert load_theme() == "textual-dark"

    def test_load_theme_returns_none_when_not_set(self, tmp_path, monkeypatch):
        """load_theme returns None when no theme has been saved."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_theme() is None

    def test_save_theme_overwrites_previous_value(self, tmp_path, monkeypatch):
        """Calling save_theme twice keeps only the most recent value."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_theme("nord")
        save_theme("gruvbox")
        assert load_theme() == "gruvbox"


class TestLoadDefaultCommodity:
    """Tests for load_default_commodity configuration helper."""

    def test_returns_dollar_when_not_set(self, tmp_path, monkeypatch):
        """Returns '$' when config has no default_commodity key."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_default_commodity() == "$"

    def test_returns_configured_value(self, tmp_path, monkeypatch):
        """Returns the configured commodity when set in config."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('default_commodity = "\u20ac"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_default_commodity() == "\u20ac"

    def test_returns_dollar_when_config_missing(self, tmp_path, monkeypatch):
        """Returns '$' when the config file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "nonexistent.toml"
        )
        assert load_default_commodity() == "$"


class TestLoadPriceTickers:
    """Tests for load_price_tickers configuration helper."""

    def test_returns_empty_when_no_prices_section(self, tmp_path, monkeypatch):
        """Returns an empty dict when config.toml has no [prices] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_price_tickers() == {}

    def test_returns_tickers_from_config(self, tmp_path, monkeypatch):
        """Returns the commodity-to-ticker mapping from the [prices] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[prices]\nXDWD = "XDWD.DE"\nXEON = "XEON.DE"\n'
        )
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        result = load_price_tickers()
        assert result == {"XDWD": "XDWD.DE", "XEON": "XEON.DE"}


class TestSavePreservesNestedSections:
    """Tests that _save_config_dict preserves nested TOML sections."""

    def test_save_preserves_prices_section(self, tmp_path, monkeypatch):
        """Saving a theme does not corrupt the [prices] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            'theme = "nord"\n\n[prices]\nXDWD = "XDWD.DE"\nXEON = "XEON.DE"\n'
        )
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)

        # Change theme — this must not lose [prices]
        save_theme("dracula")

        assert load_theme() == "dracula"
        tickers = load_price_tickers()
        assert tickers == {"XDWD": "XDWD.DE", "XEON": "XEON.DE"}

    def test_save_config_dict_with_nested_dict(self, tmp_path, monkeypatch):
        """_save_config_dict correctly writes nested dict sections."""
        config_path = tmp_path / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)

        data = {
            "theme": "gruvbox",
            "prices": {"A": "A.DE", "B": "B.DE"},
        }
        _save_config_dict(data)

        loaded = _load_config_dict()
        assert loaded["theme"] == "gruvbox"
        assert loaded["prices"] == {"A": "A.DE", "B": "B.DE"}
