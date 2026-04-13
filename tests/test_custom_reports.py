"""Tests for custom report CRUD (config) and hledger execution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from hledger_textual.config import (
    delete_custom_report,
    load_custom_reports,
    save_custom_report,
    save_theme,
)
from hledger_textual.hledger import HledgerError, run_custom_report
from hledger_textual.models import CustomReport


# ---------------------------------------------------------------------------
# Config CRUD tests
# ---------------------------------------------------------------------------


class TestLoadCustomReports:
    """Tests for load_custom_reports."""

    def test_returns_empty_when_no_section(self, tmp_path, monkeypatch):
        """Returns an empty dict when config.toml has no [custom_reports] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text('theme = "nord"\n')
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        assert load_custom_reports() == {}

    def test_returns_empty_when_config_missing(self, tmp_path, monkeypatch):
        """Returns an empty dict when the config file does not exist."""
        monkeypatch.setattr(
            "hledger_textual.config._CONFIG_PATH", tmp_path / "nonexistent.toml"
        )
        assert load_custom_reports() == {}

    def test_returns_reports_from_config(self, tmp_path, monkeypatch):
        """Returns the name-to-command mapping from the [custom_reports] section."""
        config_path = tmp_path / "config.toml"
        config_path.write_text(
            '[custom_reports]\n'
            '"Monthly expenses" = "balance expenses --tree -M"\n'
            '"Salary" = "register income:salary"\n'
        )
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        result = load_custom_reports()
        assert result == {
            "Monthly expenses": "balance expenses --tree -M",
            "Salary": "register income:salary",
        }


class TestSaveCustomReport:
    """Tests for save_custom_report."""

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        """save_custom_report persists a report that load_custom_reports retrieves."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_custom_report("My report", "balance expenses --tree")
        result = load_custom_reports()
        assert result == {"My report": "balance expenses --tree"}

    def test_save_multiple_reports(self, tmp_path, monkeypatch):
        """Multiple custom reports can be saved and all are returned."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_custom_report("Expenses", "balance expenses")
        save_custom_report("Income", "balance income")
        result = load_custom_reports()
        assert result["Expenses"] == "balance expenses"
        assert result["Income"] == "balance income"

    def test_save_overwrites_existing_name(self, tmp_path, monkeypatch):
        """Saving with an existing name updates the command."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_custom_report("Report", "balance expenses")
        save_custom_report("Report", "balance income --tree")
        assert load_custom_reports()["Report"] == "balance income --tree"

    def test_preserves_other_settings(self, tmp_path, monkeypatch):
        """Saving a custom report does not corrupt other config sections."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_theme("nord")
        save_custom_report("Report", "balance expenses")
        from hledger_textual.config import load_theme
        assert load_theme() == "nord"
        assert load_custom_reports()["Report"] == "balance expenses"


class TestDeleteCustomReport:
    """Tests for delete_custom_report."""

    def test_delete_removes_report(self, tmp_path, monkeypatch):
        """delete_custom_report removes the named report from config."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_custom_report("A", "balance")
        save_custom_report("B", "register")
        delete_custom_report("A")
        result = load_custom_reports()
        assert "A" not in result
        assert result["B"] == "register"

    def test_delete_nonexistent_is_noop(self, tmp_path, monkeypatch):
        """Deleting a report that does not exist does not raise."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_custom_report("keep", "balance")
        delete_custom_report("nonexistent")
        assert load_custom_reports() == {"keep": "balance"}

    def test_delete_preserves_other_sections(self, tmp_path, monkeypatch):
        """Deleting a custom report does not corrupt other config sections."""
        config_path = tmp_path / ".config" / "hledger-textual" / "config.toml"
        monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_path)
        save_theme("gruvbox")
        save_custom_report("A", "balance")
        delete_custom_report("A")
        from hledger_textual.config import load_theme
        assert load_theme() == "gruvbox"
        assert load_custom_reports() == {}


# ---------------------------------------------------------------------------
# CustomReport model tests
# ---------------------------------------------------------------------------


class TestCustomReportModel:
    """Tests for the CustomReport dataclass."""

    def test_fields(self):
        """CustomReport stores name and command."""
        r = CustomReport(name="My report", command="balance expenses --tree")
        assert r.name == "My report"
        assert r.command == "balance expenses --tree"


# ---------------------------------------------------------------------------
# run_custom_report tests
# ---------------------------------------------------------------------------


class TestRunCustomReport:
    """Tests for run_custom_report in hledger.py."""

    def test_passes_args_to_run_hledger(self, tmp_path):
        """run_custom_report splits the command and calls run_hledger correctly."""
        journal = tmp_path / "test.journal"
        journal.write_text("")

        captured: list[tuple] = []

        def _mock_run_hledger(*args, file=None):
            captured.append((args, file))
            return "output"

        with patch("hledger_textual.hledger.run_hledger", _mock_run_hledger):
            result = run_custom_report(journal, "balance expenses --tree")

        assert result == "output"
        assert len(captured) == 1
        args, file = captured[0]
        assert args == ("balance", "expenses", "--tree")
        assert file == journal

    def test_handles_quoted_args(self, tmp_path):
        """run_custom_report handles shell-quoted arguments correctly."""
        journal = tmp_path / "test.journal"
        journal.write_text("")

        captured: list[tuple] = []

        def _mock_run_hledger(*args, file=None):
            captured.append((args, file))
            return ""

        with patch("hledger_textual.hledger.run_hledger", _mock_run_hledger):
            run_custom_report(journal, 'register "income:freelance work"')

        args, _ = captured[0]
        assert args == ("register", "income:freelance work")

    def test_propagates_hledger_error(self, tmp_path):
        """HledgerError raised by run_hledger propagates to the caller."""
        journal = tmp_path / "test.journal"
        journal.write_text("")

        def _mock_run_hledger(*args, file=None):
            raise HledgerError("command failed")

        with patch("hledger_textual.hledger.run_hledger", _mock_run_hledger):
            with pytest.raises(HledgerError, match="command failed"):
                run_custom_report(journal, "balance")


# ---------------------------------------------------------------------------
# _format_custom_output tests
# ---------------------------------------------------------------------------


class TestFormatCustomOutput:
    """Tests for the _format_custom_output Rich formatter."""

    def _render(self, raw: str) -> str:
        """Render a Rich Text to a plain string for assertion."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        return _format_custom_output(raw).plain

    def test_replaces_pipe_separators(self):
        """|| is replaced with the Unicode box-drawing character │."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        raw = "Title\n  Account  ||  Jan\n"
        plain = _format_custom_output(raw).plain
        assert "│" in plain
        assert "||" not in plain

    def test_replaces_plus_plus_separators(self):
        """++ is replaced with ┼."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        raw = "Title\n=========++==========\n"
        plain = _format_custom_output(raw).plain
        assert "┼" in plain
        assert "++" not in plain

    def test_title_line_is_bold(self):
        """The first non-empty line is rendered bold."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        raw = "Balance changes in 2026Q1:\n  Account  ||  Jan\n"
        text = _format_custom_output(raw)
        # Find the span covering the title
        styles = {span.style for span in text._spans}
        assert any("bold" in str(s) for s in styles)

    def test_total_rows_after_dashes(self):
        """Lines after the --- separator are styled bold yellow."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        raw = (
            "Title\n"
            "  Expenses  ||  €100\n"
            "------------++---------\n"
            "            ||  €100\n"
        )
        text = _format_custom_output(raw)
        styles = {str(span.style) for span in text._spans}
        assert any("yellow" in s for s in styles)

    def test_standalone_zeros_are_dimmed(self):
        """Standalone 0 values are dimmed; 0 inside amounts like €0.50 is not."""
        from hledger_textual.widgets.reports_pane import _format_custom_output
        raw = "Title\n  Accounting  ||        0   €36.50\n"
        text = _format_custom_output(raw)
        # There should be a dim span; the plain text retains the 0
        assert "0" in text.plain
        dim_spans = [s for s in text._spans if "dim" in str(s.style)]
        assert len(dim_spans) > 0


# ---------------------------------------------------------------------------
# ReportsPane integration tests
# ---------------------------------------------------------------------------


class TestReportsPaneCustomReports:
    """Integration tests for custom report selection in ReportsPane."""

    async def test_custom_report_select_is_present(
        self, tmp_path: Path, monkeypatch
    ):
        """The custom-report-select widget is mounted in ReportsPane."""
        from textual.app import App, ComposeResult
        from textual.widgets import Select
        from hledger_textual.models import ReportData
        from hledger_textual.widgets.reports_pane import ReportsPane

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *a, **kw: ReportData(title="", period_headers=[], rows=[]),
        )

        journal = tmp_path / "test.journal"
        journal.write_text("")

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ReportsPane(journal)

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            select = app.query_one("#custom-report-select", Select)
            assert select is not None

    async def test_selecting_custom_report_shows_output_widget(
        self, tmp_path: Path, monkeypatch
    ):
        """Selecting a custom report hides the DataTable and shows the output widget."""
        from textual.app import App, ComposeResult
        from textual.containers import VerticalScroll
        from textual.widgets import DataTable, Select
        from hledger_textual.models import ReportData
        from hledger_textual.widgets.reports_pane import ReportsPane

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *a, **kw: ReportData(title="", period_headers=[], rows=[]),
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_custom_reports",
            lambda: {"My report": "balance expenses"},
        )
        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.run_custom_report",
            lambda *a, **kw: "expenses  €100",
        )

        journal = tmp_path / "test.journal"
        journal.write_text("")

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ReportsPane(journal)

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.3)
            app.query_one(ReportsPane)
            select = app.query_one("#custom-report-select", Select)
            select.value = "My report"
            await pilot.pause(delay=0.3)
            table = app.query_one("#reports-table", DataTable)
            output = app.query_one("#custom-report-output", VerticalScroll)
            assert not table.display
            assert output.display

    async def test_n_key_opens_custom_report_form(
        self, tmp_path: Path, monkeypatch
    ):
        """Pressing n opens the CustomReportFormScreen."""
        from textual.app import App, ComposeResult
        from hledger_textual.models import ReportData
        from hledger_textual.screens.custom_report_form import CustomReportFormScreen
        from hledger_textual.widgets.reports_pane import ReportsPane

        monkeypatch.setattr(
            "hledger_textual.widgets.reports_pane.load_report",
            lambda *a, **kw: ReportData(title="", period_headers=[], rows=[]),
        )

        journal = tmp_path / "test.journal"
        journal.write_text("")

        class _App(App):
            def compose(self) -> ComposeResult:
                yield ReportsPane(journal)

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.3)
            pane = app.query_one(ReportsPane)
            pane.focus()
            await pilot.press("n")
            await pilot.pause()
            assert isinstance(app.screen, CustomReportFormScreen)
