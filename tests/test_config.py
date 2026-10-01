"""Tests for configuration resolution."""

from pathlib import Path

import pytest

from hledger_textual.config import (
    _load_config_dict,
    _save_config_dict,
    delete_filter,
    load_configured_default_commodity,
    load_default_commodity,
    load_price_tickers,
    load_saved_filters,
    load_theme,
    parse_args,
    resolve_default_commodity,
    resolve_journal_file,
    save_filter,
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


class TestLoadConfiguredDefaultCommodity:
    """Tests for load_configured_default_commodity configuration helper."""

    def test_returns_none_when_not_set(self, tmp_path, monkeypatch):
        """Returns None when config has no default_commodity key."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_configured_default_commodity() is None

    def test_returns_configured_value(self, tmp_path, monkeypatch):
        """Returns the raw configured commodity when set."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('default_commodity = "\u20ac"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_configured_default_commodity() == "\u20ac"

    def test_returns_none_when_config_missing(self, tmp_path, monkeypatch):
        """Returns None when the config file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "nonexistent.toml"
        )
        assert load_configured_default_commodity() is None


class TestResolveDefaultCommodity:
    """Tests for resolve_default_commodity (config-first, ledger fallback)."""

    def _patch_config(self, tmp_path, monkeypatch, content: str | None):
        config_path = tmp_path / "config.toml"
        if content is not None:
            config_path.write_text(content)
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)

    def test_config_wins_over_journal_directive(self, tmp_path, monkeypatch):
        """An explicit config value beats a journal `commodity` directive."""
        self._patch_config(tmp_path, monkeypatch, 'default_commodity = "$"\n')
        journal = tmp_path / "test.journal"
        journal.write_text(
            "commodity €1,000.00\n"
            "commodity $1,000.00\n"
            "\n"
            "2026-01-01 * x\n"
            "    assets:bank  €100.00\n"
            "    income:salary\n"
        )
        assert resolve_default_commodity(journal) == "$"

    def test_journal_directive_used_when_config_unset(self, tmp_path, monkeypatch):
        """With no config value, the journal's first directive is used."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text("commodity €1,000.00\n")
        assert resolve_default_commodity(journal) == "€"

    def test_first_directive_wins(self, tmp_path, monkeypatch):
        """The first `commodity` directive is used, not a later one."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text(
            "commodity $1,000.00\n"
            "commodity €1,000.00\n"
        )
        assert resolve_default_commodity(journal) == "$"

    def test_right_side_named_commodity_format(self, tmp_path, monkeypatch):
        """A `commodity` directive with a named unit on the right is resolved."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text("commodity 0.0000 XEON\n")
        assert resolve_default_commodity(journal) == "XEON"

    def test_include_directive_is_followed(self, tmp_path, monkeypatch):
        """Commodity declarations in an included journal are considered."""
        self._patch_config(tmp_path, monkeypatch, None)
        (tmp_path / "included.journal").write_text("commodity £1,000.00\n")
        journal = tmp_path / "main.journal"
        journal.write_text("include included.journal\n")
        assert resolve_default_commodity(journal) == "£"

    def test_main_directive_beats_included(self, tmp_path, monkeypatch):
        """A directive in the main file wins over an included file's."""
        self._patch_config(tmp_path, monkeypatch, None)
        (tmp_path / "included.journal").write_text("commodity £1,000.00\n")
        journal = tmp_path / "main.journal"
        journal.write_text(
            "include included.journal\n"
            "commodity €1,000.00\n"
        )
        assert resolve_default_commodity(journal) == "€"

    def test_quoted_symbol_is_unwrapped(self, tmp_path, monkeypatch):
        """A quoted symbol is returned without its quotes."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text('commodity "USD" 1,000.00\n')
        assert resolve_default_commodity(journal) == "USD"

    def test_trailing_comment_is_ignored(self, tmp_path, monkeypatch):
        """A trailing comment after a directive does not hide the symbol."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text("commodity €1,000.00 ; euro\n")
        assert resolve_default_commodity(journal) == "€"

    def test_glob_include_is_expanded(self, tmp_path, monkeypatch):
        """An `include *.journal` glob is expanded and followed."""
        self._patch_config(tmp_path, monkeypatch, None)
        (tmp_path / "prices.journal").write_text("commodity £1,000.00\n")
        journal = tmp_path / "main.journal"
        journal.write_text("include *.journal\n")
        assert resolve_default_commodity(journal) == "£"

    def test_config_fallback_when_no_directive(self, tmp_path, monkeypatch):
        """With no journal directive, the configured default commodity is used."""
        self._patch_config(tmp_path, monkeypatch, 'default_commodity = "€"\n')
        journal = tmp_path / "test.journal"
        journal.write_text(
            "2026-01-01 * x\n    assets:bank  €100.00\n    income:salary\n"
        )
        assert resolve_default_commodity(journal) == "€"

    def test_none_when_no_directive_and_no_config(self, tmp_path, monkeypatch):
        """With neither a journal directive nor config, returns None."""
        self._patch_config(tmp_path, monkeypatch, None)
        journal = tmp_path / "test.journal"
        journal.write_text(
            "2026-01-01 * x\n    assets:bank  €100.00\n    income:salary\n"
        )
        assert resolve_default_commodity(journal) is None

    def test_missing_journal_returns_config(self, tmp_path, monkeypatch):
        """A missing journal file falls back to the configured value."""
        self._patch_config(tmp_path, monkeypatch, 'default_commodity = "$"\n')
        assert resolve_default_commodity(tmp_path / "nonexistent.journal") == "$"

    def test_commented_directive_is_ignored(self, tmp_path, monkeypatch):
        """A `;`-commented directive is not treated as a declaration."""
        self._patch_config(tmp_path, monkeypatch, 'default_commodity = "$"\n')
        journal = tmp_path / "test.journal"
        journal.write_text("; commodity €1,000.00\n")
        assert resolve_default_commodity(journal) == "$"


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


class TestSavedFilters:
    """Tests for saved search filter CRUD in config.toml."""

    def test_load_returns_empty_when_no_filters_section(self, tmp_path, monkeypatch):
        """Returns an empty dict when config.toml has no [filters] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_saved_filters() == {}

    def test_load_returns_empty_when_config_missing(self, tmp_path, monkeypatch):
        """Returns an empty dict when the config file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "nonexistent.toml"
        )
        assert load_saved_filters() == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """save_filter persists a filter that load_saved_filters can retrieve."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("groceries", "desc:grocery amt:>50")
        result = load_saved_filters()
        assert result == {"groceries": "desc:grocery amt:>50"}

    def test_save_multiple_filters(self, tmp_path, monkeypatch):
        """Multiple filters can be saved and all are returned."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("groceries", "acct:food")
        save_filter("big expenses", "amt:>500")
        result = load_saved_filters()
        assert result["groceries"] == "acct:food"
        assert result["big expenses"] == "amt:>500"

    def test_save_overwrites_existing_name(self, tmp_path, monkeypatch):
        """Saving with an existing name updates the query."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("work", "acct:income:salary")
        save_filter("work", "acct:income:freelance")
        assert load_saved_filters()["work"] == "acct:income:freelance"

    def test_delete_removes_filter(self, tmp_path, monkeypatch):
        """delete_filter removes the named filter from config."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("groceries", "acct:food")
        save_filter("big expenses", "amt:>500")
        delete_filter("groceries")
        result = load_saved_filters()
        assert "groceries" not in result
        assert result["big expenses"] == "amt:>500"

    def test_delete_nonexistent_is_noop(self, tmp_path, monkeypatch):
        """Deleting a filter that does not exist does not raise."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("keep", "acct:food")
        delete_filter("nonexistent")
        assert load_saved_filters() == {"keep": "acct:food"}

    def test_filters_preserved_when_saving_other_settings(self, tmp_path, monkeypatch):
        """Saving a theme does not corrupt saved filters."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_filter("groceries", "acct:food")
        save_theme("gruvbox")
        assert load_saved_filters() == {"groceries": "acct:food"}
        assert load_theme() == "gruvbox"
