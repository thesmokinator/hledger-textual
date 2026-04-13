"""End-to-end round-trip tests: TUI action → journal file mutation.

Each test opens the app against a temporary journal, performs an action via the
pilot (add / edit / status-toggle / delete), and then asserts that the journal
file on disk reflects the change.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.screens.transaction_form import TransactionFormScreen

from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")

# Use current-month dates so the default "thismonth" filter shows transactions.
_TODAY = date.today()
_D1 = _TODAY.replace(day=1)
_D2 = _TODAY.replace(day=2)
_D3 = _TODAY.replace(day=3)


@pytest.fixture
def round_trip_journal(tmp_path: Path) -> Path:
    """A temporary journal with three current-month transactions."""
    content = (
        "; Round-trip test journal\n"
        "\n"
        f"{_D1.isoformat()} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
        "\n"
        f"{_D2.isoformat()} Grocery shopping\n"
        "    expenses:food:groceries              €40.00\n"
        "    assets:bank:checking\n"
        "\n"
        f"{_D3.isoformat()} ! Office supplies\n"
        "    expenses:office                      €25.00\n"
        "    assets:bank:checking\n"
    )
    dest = tmp_path / "round_trip.journal"
    dest.write_text(content, encoding="utf-8")
    return dest


@pytest.fixture
def app(round_trip_journal: Path) -> HledgerTuiApp:
    return HledgerTuiApp(journal_file=round_trip_journal)


class TestRoundTrip:
    """Full TUI → journal-file round-trip tests."""

    async def test_add_transaction_appears_in_journal(
        self, app: HledgerTuiApp, round_trip_journal: Path
    ) -> None:
        """Adding a transaction via the form should append it to the journal file."""
        from textual.widgets import Input

        from hledger_textual.widgets.posting_row import PostingRow

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("a")
            await pilot.pause(delay=0.5)

            form = app.screen
            assert isinstance(form, TransactionFormScreen)

            form.query_one("#input-description", Input).value = "Round Trip Add"
            rows = list(form.query(PostingRow))
            rows[0].query_one("#account-0", Input).value = "expenses:test"
            rows[0].query_one("#amount-0", Input).value = "€99.00"
            rows[1].query_one("#account-1", Input).value = "assets:bank:checking"

            form._save()
            await pilot.pause(delay=1.0)

        content = round_trip_journal.read_text(encoding="utf-8")
        assert "Round Trip Add" in content
        assert "expenses:test" in content

    async def test_edit_description_updates_journal(
        self, app: HledgerTuiApp, round_trip_journal: Path
    ) -> None:
        """Editing a transaction description should update the journal file."""
        from textual.widgets import Input

        # Table is sorted newest-first → D3 (Office supplies) is at the top
        original_desc = "Office supplies"
        new_desc = "Updated Office Visit"

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("e")
            await pilot.pause(delay=0.5)

            form = app.screen
            assert isinstance(form, TransactionFormScreen)

            desc_input = form.query_one("#input-description", Input)
            desc_input.value = new_desc

            form._save()
            await pilot.pause(delay=1.0)

        content = round_trip_journal.read_text(encoding="utf-8")
        assert new_desc in content
        assert original_desc not in content

    async def test_toggle_cleared_status_updates_journal(
        self, app: HledgerTuiApp, round_trip_journal: Path
    ) -> None:
        """Pressing '*' on an unmarked transaction should write '* ' to the journal."""
        before = round_trip_journal.read_text(encoding="utf-8")
        # The first transaction (Salary) has no status marker
        assert f"{_D3.isoformat()} !" in before

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            # Toggle cleared on the currently selected transaction
            await pilot.press("*")
            await pilot.pause(delay=1.0)

        content = round_trip_journal.read_text(encoding="utf-8")
        # At least one transaction should now have the cleared marker
        assert "* " in content

    async def test_delete_transaction_removes_from_journal(
        self, app: HledgerTuiApp, round_trip_journal: Path
    ) -> None:
        """Confirming deletion should remove the transaction from the journal file."""
        before = round_trip_journal.read_text(encoding="utf-8")
        # Identify one description that should disappear
        # The table is sorted newest-first; "Office supplies" is at top (D3)
        assert "Office supplies" in before

        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            # Trigger delete → pushes DeleteConfirmModal
            await pilot.press("d")
            await pilot.pause(delay=0.5)
            # Click the "Delete" confirm button
            from hledger_textual.screens.delete_confirm import DeleteConfirmModal
            assert isinstance(app.screen, DeleteConfirmModal)
            await pilot.click("#btn-delete")
            await pilot.pause(delay=1.0)

        content = round_trip_journal.read_text(encoding="utf-8")
        assert "Office supplies" not in content
