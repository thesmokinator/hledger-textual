"""Integration tests for the Textual app."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from hledger_textual.app import HledgerTuiApp
from hledger_textual.hledger import load_transactions
from tests.conftest import has_hledger

pytestmark = pytest.mark.skipif(not has_hledger(), reason="hledger not installed")


@pytest.fixture
def app_journal(tmp_path: Path) -> Path:
    """A temporary journal with current-month dates for app testing.

    Uses dates within the current month so that the default "thismonth"
    period filter always shows all three transactions.
    """
    today = date.today()
    # Use today for all dates so they are always in the past, avoiding the
    # "Scheduled" separator row that _update_table adds for future dates.
    d = today.isoformat()

    content = (
        "; Test journal for app integration tests\n"
        "\n"
        f"{d} * (INV-001) Grocery shopping  ; weekly groceries\n"
        "    expenses:food:groceries              €40.80\n"
        "    assets:bank:checking\n"
        "\n"
        f"{d} Salary\n"
        "    assets:bank:checking               €3000.00\n"
        "    income:salary\n"
        "\n"
        f"{d} ! Office supplies  ; for home office\n"
        "    expenses:office                      €25.00\n"
        "    expenses:shipping                    €10.00\n"
        "    assets:bank:checking\n"
    )
    dest = tmp_path / "app_test.journal"
    dest.write_text(content)
    return dest


@pytest.fixture
def app(app_journal: Path) -> HledgerTuiApp:
    """Create an app instance with the test journal."""
    return HledgerTuiApp(journal_file=app_journal)


class TestAppStartup:
    """Tests for application startup."""

    async def test_app_starts_on_summary(self, app: HledgerTuiApp):
        """The app opens on the Summary tab by default."""
        from textual.widgets import ContentSwitcher

        async with app.run_test() as pilot:
            await pilot.pause()
            switcher = app.screen.query_one("#content-switcher", ContentSwitcher)
            assert switcher.current == "summary"

    async def test_switch_to_transactions_shows_table(self, app: HledgerTuiApp):
        """Switching to Transactions shows the data table with rows."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=1.0)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_quit_key(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")


class TestFilter:
    """Tests for the filter functionality."""

    async def test_filter_shows_input(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("slash")
            from hledger_textual.widgets.transactions_table import TransactionsTable
            txn_table = app.screen.query_one(TransactionsTable)
            filter_bar = txn_table.query_one(".filter-bar")
            assert filter_bar.has_class("visible")

    async def test_search_narrows_results(self, app: HledgerTuiApp):
        """Searching with hledger query narrows results."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("slash")
            search_input = app.screen.query_one("#txn-search-input")
            search_input.value = "desc:Grocery"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 1

    async def test_escape_clears_search(self, app: HledgerTuiApp):
        """Pressing escape clears the search and restores all results."""
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("slash")
            search_input = app.screen.query_one("#txn-search-input")
            search_input.value = "desc:Grocery"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            await pilot.press("escape")
            await pilot.pause(delay=1.0)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_search_by_account(self, app: HledgerTuiApp):
        """Searching with acct: query filters by account."""
        from textual.widgets import Input

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            from hledger_textual.widgets.transactions_table import TransactionsTable
            txn_table = app.screen.query_one(TransactionsTable)
            txn_table.show_filter()
            await pilot.pause()
            search_input = txn_table.query_one("#txn-search-input", Input)
            search_input.focus()
            search_input.value = "acct:office"
            await pilot.press("enter")
            await pilot.pause(delay=1.0)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 1


class TestRefresh:
    """Tests for the refresh functionality."""

    async def test_refresh_reloads(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3
            await pilot.press("r")
            await pilot.pause()
            assert table.row_count == 3


class TestDelete:
    """Tests for the delete flow."""

    async def test_delete_shows_modal(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("d")
            await pilot.pause()
            from hledger_textual.screens.delete_confirm import DeleteConfirmModal

            assert isinstance(app.screen, DeleteConfirmModal)

    async def test_delete_cancel(self, app: HledgerTuiApp):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            table = app.screen.query_one("#transactions-table")
            assert table.row_count == 3

    async def test_delete_confirm(self, app: HledgerTuiApp, app_journal: Path):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            await pilot.press("d")
            await pilot.pause()
            delete_btn = app.screen.query_one("#btn-delete")
            await pilot.click(delete_btn)
            await pilot.pause(delay=1.0)
            txns = load_transactions(app_journal)
            assert len(txns) == 2


class TestGitSync:
    """Tests for the git sync action."""

    async def test_git_sync_not_a_repo(self, app: HledgerTuiApp, monkeypatch):
        """Pressing s when not in a git repo shows a warning notification."""
        from hledger_textual.sync import GitSyncBackend

        backend = GitSyncBackend(app.journal_file)
        monkeypatch.setattr(backend, "is_available", lambda: False)
        app._sync_backend = backend
        async with app.run_test(notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause(delay=0.5)
            assert any(
                "Git is not available" in str(n.message)
                for n in app._notifications
            )

    async def test_git_sync_shows_confirm_dialog(
        self, app: HledgerTuiApp, monkeypatch
    ):
        """Pressing s in a git repo opens the confirmation dialog."""
        from hledger_textual.screens.sync_confirm import SyncConfirmModal
        from hledger_textual.sync import GitSyncBackend

        backend = GitSyncBackend(app.journal_file)
        monkeypatch.setattr(backend, "is_available", lambda: True)
        app._sync_backend = backend
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SyncConfirmModal)

    async def test_git_sync_cancel(self, app: HledgerTuiApp, monkeypatch):
        """Cancelling the dialog does not run git_sync."""
        from hledger_textual.sync import GitSyncBackend

        backend = GitSyncBackend(app.journal_file)
        monkeypatch.setattr(backend, "is_available", lambda: True)
        sync_called = False

        def _track(action, journal_file):
            nonlocal sync_called
            sync_called = True
            return "ok"

        monkeypatch.setattr(backend, "run", _track)
        app._sync_backend = backend
        async with app.run_test(notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(delay=0.5)
            assert not sync_called

    async def test_git_sync_confirm_success(
        self, app: HledgerTuiApp, monkeypatch
    ):
        """Confirming sync runs backend and shows success notification."""
        from hledger_textual.sync import GitSyncBackend

        backend = GitSyncBackend(app.journal_file)
        monkeypatch.setattr(backend, "is_available", lambda: True)
        monkeypatch.setattr(
            backend, "run",
            lambda action, jf: "Committed and pushed successfully",
        )
        app._sync_backend = backend
        async with app.run_test(notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            sync_btn = app.screen.query_one("#btn-sync-sync")
            await pilot.click(sync_btn)
            await pilot.pause(delay=0.5)
            assert any(
                "Committed and pushed" in str(n.message)
                for n in app._notifications
            )

    async def test_git_sync_confirm_error(
        self, app: HledgerTuiApp, monkeypatch
    ):
        """SyncError during sync shows an error notification."""
        from hledger_textual.sync import GitSyncBackend, SyncError

        backend = GitSyncBackend(app.journal_file)
        monkeypatch.setattr(backend, "is_available", lambda: True)

        def _raise(action, journal_file):
            raise SyncError("push failed")

        monkeypatch.setattr(backend, "run", _raise)
        app._sync_backend = backend
        async with app.run_test(notifications=True) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            sync_btn = app.screen.query_one("#btn-sync-sync")
            await pilot.click(sync_btn)
            await pilot.pause(delay=0.5)
            assert any(
                "push failed" in str(n.message)
                for n in app._notifications
            )


class TestTabNavigation:
    """Tests for keyboard number shortcuts that switch sections."""

    async def test_number_keys_switch_sections(self, app: HledgerTuiApp):
        """Pressing 1-6 switches to the corresponding section."""
        from textual.widgets import ContentSwitcher

        async with app.run_test() as pilot:
            await pilot.pause()
            sections = [
                ("1", "summary"),
                ("2", "transactions"),
                ("3", "recurring"),
                ("4", "budget"),
                ("5", "reports"),
                ("6", "accounts"),
            ]
            for key, expected in sections:
                await pilot.press(key)
                await pilot.pause()
                switcher = app.screen.query_one(
                    "#content-switcher", ContentSwitcher
                )
                assert switcher.current == expected

    async def test_footer_updates_on_switch(self, app: HledgerTuiApp):
        """Footer help text updates when switching sections."""
        from textual.widgets import Static

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause(delay=0.5)
            footer = app.screen.query_one("#footer-bar", Static)
            rendered = str(footer.renderable)
            assert "Add" in rendered
            assert "Search" in rendered

    async def test_help_in_all_footers(self, app: HledgerTuiApp):
        """[?] Help appears in the footer of every tab."""
        from textual.widgets import Static

        async with app.run_test() as pilot:
            for key in ("1", "2", "3", "4", "5", "6"):
                await pilot.press(key)
                await pilot.pause()
                footer = app.screen.query_one("#footer-bar", Static)
                rendered = str(footer.renderable)
                assert "Help" in rendered, f"Help missing in tab {key}"
