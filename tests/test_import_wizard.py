"""UI tests for the CSV import wizard and preview screens."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from hledger_textual.csv_import import generate_rules_content, save_rules_file

_has_hledger = shutil.which("hledger") is not None

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_CSV = FIXTURES / "sample_bank.csv"
SAMPLE_RULES = FIXTURES / "sample_bank.rules"


class TestCsvFileSelectModal:
    """Tests for the CsvFileSelectModal screen."""

    @pytest.mark.asyncio
    async def test_dismiss_with_valid_path(self) -> None:
        """Dismissing with a valid CSV path should return the path."""
        from hledger_textual.screens.csv_file_select import CsvFileSelectModal

        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    CsvFileSelectModal(), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#csv-file-path-input")
            inp.value = str(SAMPLE_CSV)
            btn = app.screen.query_one("#btn-csv-next")
            await pilot.click(btn)
            await pilot.pause()

        assert len(results) == 1
        assert results[0] == SAMPLE_CSV.resolve()

    @pytest.mark.asyncio
    async def test_dismiss_with_cancel(self) -> None:
        """Cancelling should return None."""
        from hledger_textual.screens.csv_file_select import CsvFileSelectModal

        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    CsvFileSelectModal(), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-csv-cancel")
            await pilot.click(btn)
            await pilot.pause()

        assert results == [None]

    @pytest.mark.asyncio
    async def test_invalid_path_keeps_modal_open(self) -> None:
        """An invalid path should not dismiss the modal."""
        from hledger_textual.screens.csv_file_select import CsvFileSelectModal

        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    CsvFileSelectModal(), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#csv-file-path-input")
            inp.value = "/nonexistent/path/file.csv"
            btn = app.screen.query_one("#btn-csv-next")
            await pilot.click(btn)
            await pilot.pause()
            # Modal should still be open (no result yet)
            assert len(results) == 0


class TestRulesManagerModal:
    """Tests for the RulesManagerModal screen."""

    @pytest.mark.asyncio
    async def test_empty_rules_dir(self, tmp_path: Path) -> None:
        """With no rules files, should show empty message."""
        from hledger_textual.screens.rules_manager import RulesManagerModal

        journal = tmp_path / "test.journal"
        journal.write_text("")

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(RulesManagerModal(journal))

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            empty_msg = app.screen.query_one("#rules-manager-empty")
            assert empty_msg.display is True

    @pytest.mark.asyncio
    async def test_new_button_returns_new(self, tmp_path: Path) -> None:
        """Clicking '+ New' should dismiss with ('new', None)."""
        from hledger_textual.screens.rules_manager import RulesManagerModal

        journal = tmp_path / "test.journal"
        journal.write_text("")
        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    RulesManagerModal(journal), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-rules-new")
            await pilot.click(btn)
            await pilot.pause()

        assert results == [("new", None)]

    @pytest.mark.asyncio
    async def test_lists_existing_rules(self, tmp_path: Path) -> None:
        """Should display rules files found in the rules directory."""
        from textual.widgets import DataTable

        from hledger_textual.screens.rules_manager import RulesManagerModal

        journal = tmp_path / "test.journal"
        journal.write_text("")
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        content = generate_rules_content(
            name="Test Bank", separator=",", date_format="%Y-%m-%d",
            skip=1, field_mapping=["date", "description", "amount"],
            currency="EUR", account1="assets:bank:test", conditional_rules=[],
        )
        save_rules_file(rules_dir, "Test Bank", content)

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(RulesManagerModal(journal))

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#rules-manager-table", DataTable)
            assert table.row_count == 1


class _WizardHostApp(App):
    """Host app that opens the import wizard on mount.

    Mirrors the production ``check_action`` veto: while the wizard modal
    is on top, the app-level command palette must not swallow Ctrl+P.
    """

    def __init__(self, csv_path: Path, journal: Path) -> None:
        super().__init__()
        self._csv_path = csv_path
        self._journal = journal

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> bool | None:
        """Veto the command palette while the wizard is open."""
        from hledger_textual.screens.import_wizard import ImportWizardScreen

        if action == "command_palette" and isinstance(
            self.screen, ImportWizardScreen
        ):
            return False
        return True

    def compose(self) -> ComposeResult:
        yield Static("test")

    def on_mount(self) -> None:
        from hledger_textual.screens.import_wizard import ImportWizardScreen

        self.push_screen(ImportWizardScreen(self._csv_path, self._journal))


class TestImportWizardProgress:
    """Pilot tests for the progress strip, focus and Ctrl+N/P navigation."""

    @staticmethod
    def _indicator(screen) -> str:
        """Return the progress strip as plain text."""
        return str(screen.query_one("#wizard-step-indicator", Static).renderable)

    @pytest.mark.asyncio
    async def test_indicator_and_focus_on_mount(self, tmp_path: Path) -> None:
        """Mounting shows step 1 in the strip and focuses the separator."""
        from hledger_textual.screens.import_wizard import ImportWizardScreen

        journal = tmp_path / "test.journal"
        journal.write_text("")
        app = _WizardHostApp(SAMPLE_CSV, journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ImportWizardScreen)
            strip = self._indicator(screen)
            assert "● ○ ○ ○ ○" in strip
            assert "Step 1 of 5" in strip
            assert "CSV Preview" in strip
            assert "next:" in strip
            assert screen.focused is not None
            assert screen.focused.id == "wizard-separator"

    @pytest.mark.asyncio
    async def test_ctrl_navigates_and_restores_focus(
        self, tmp_path: Path
    ) -> None:
        """Ctrl+N/P move between steps focusing each step's first input."""
        from textual.widgets import Button, Input

        from hledger_textual.screens.import_wizard import ImportWizardScreen
        from hledger_textual.widgets.autocomplete_input import AutocompleteInput

        journal = tmp_path / "test.journal"
        journal.write_text("")
        app = _WizardHostApp(SAMPLE_CSV, journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ImportWizardScreen)

            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 1
            assert "Step 2 of 5" in self._indicator(screen)
            assert "Column Mapping" in self._indicator(screen)
            assert screen.focused is not None
            assert screen.focused.id == "mapping-select-0"

            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 2
            assert screen.focused is not None
            assert screen.focused.id == "wizard-rules-name"

            # Settings step requires name + account before advancing.
            screen.query_one("#wizard-rules-name", Input).value = "Test Bank"
            screen.query_one("#wizard-account1", AutocompleteInput).value = (
                "assets:bank:test"
            )
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 3
            # No conditional rules yet: focus lands on the Add button.
            assert screen.focused is not None
            assert screen.focused.id == "btn-wizard-add-rule"

            # Add a rule, go back and forth: focus lands on its pattern.
            screen.query_one("#btn-wizard-add-rule", Button).press()
            await pilot.pause()
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert screen.state.current_step == 2
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 3
            assert screen.focused is not None
            assert screen.focused.id == "cond-pattern-0"

            # Last step: all dots filled, no "next", editor focused.
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 4
            strip = self._indicator(screen)
            assert "● ● ● ● ●" in strip
            assert "Step 5 of 5" in strip
            assert "Review & Save" in strip
            assert "next:" not in strip
            assert screen.focused is not None
            assert screen.focused.id == "wizard-raw-editor"

    @pytest.mark.asyncio
    async def test_ctrl_n_validates_before_advancing(
        self, tmp_path: Path
    ) -> None:
        """Ctrl+N on an invalid mapping stays put like the Next button."""
        from textual.widgets import Select

        from hledger_textual.screens.import_wizard import ImportWizardScreen

        journal = tmp_path / "test.journal"
        journal.write_text("")
        app = _WizardHostApp(SAMPLE_CSV, journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, ImportWizardScreen)
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 1

            screen.query_one("#mapping-select-0", Select).value = ""
            await pilot.pause()
            await pilot.press("ctrl+n")
            await pilot.pause()
            assert screen.state.current_step == 1


@pytest.mark.skipif(not _has_hledger, reason="hledger not installed")
class TestImportPreviewScreen:
    """Tests for the ImportPreviewScreen."""

    @pytest.mark.asyncio
    async def test_shows_transactions(self) -> None:
        """Should display the transactions in a DataTable."""
        from textual.widgets import DataTable

        from hledger_textual.csv_import import preview_import
        from hledger_textual.screens.import_preview import ImportPreviewScreen

        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(ImportPreviewScreen(txns, duplicates_count=0))

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.screen.query_one("#import-preview-table", DataTable)
            assert table.row_count == 26

    @pytest.mark.asyncio
    async def test_cancel_returns_none(self) -> None:
        """Cancelling should return None."""
        from textual.widgets import Button

        from hledger_textual.csv_import import preview_import
        from hledger_textual.screens.import_preview import ImportPreviewScreen

        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)
        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    ImportPreviewScreen(txns), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-import-cancel", Button)
            btn.press()
            await pilot.pause()

        assert results == [None]

    @pytest.mark.asyncio
    async def test_import_returns_transactions(self) -> None:
        """Confirming should return the transaction list."""
        from textual.widgets import Button

        from hledger_textual.csv_import import preview_import
        from hledger_textual.screens.import_preview import ImportPreviewScreen

        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)
        results: list = []

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(
                    ImportPreviewScreen(txns), callback=lambda r: results.append(r)
                )

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.screen.query_one("#btn-import-confirm", Button)
            btn.press()
            await pilot.pause()

        assert len(results) == 1
        assert len(results[0]) == 26

    @pytest.mark.asyncio
    async def test_duplicates_count_shown(self) -> None:
        """The summary should mention excluded duplicates."""
        from hledger_textual.csv_import import preview_import
        from hledger_textual.screens.import_preview import ImportPreviewScreen

        txns = preview_import(SAMPLE_CSV, SAMPLE_RULES)

        class _App(App):
            def compose(self) -> ComposeResult:
                yield Static("test")

            def on_mount(self) -> None:
                self.push_screen(ImportPreviewScreen(txns[:3], duplicates_count=2))

        app = _App()
        async with app.run_test() as pilot:
            await pilot.pause()
            summary = app.screen.query_one("#import-preview-summary")
            rendered = str(summary.renderable)
            assert "2 duplicates excluded" in rendered
