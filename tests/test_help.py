"""CI consistency check between the help screen and live BINDINGS (issue #148)."""

from __future__ import annotations

import pytest

from hledger_textual.screens.help import (
    _build_help_text,
    _format_key,
    help_sections,
)


def _section_bindings() -> dict[str, list]:
    """Return the BINDINGS lists the help sections are generated from."""
    from hledger_textual.app import HledgerTuiApp
    from hledger_textual.screens.recurring_form import RecurringFormScreen
    from hledger_textual.screens.transaction_form import TransactionFormScreen
    from hledger_textual.widgets.accounts_pane import AccountsPane
    from hledger_textual.widgets.budget_pane import BudgetPane
    from hledger_textual.widgets.recurring_pane import RecurringPane
    from hledger_textual.widgets.reports_pane import ReportsPane
    from hledger_textual.widgets.summary_pane import SummaryPane
    from hledger_textual.widgets.transactions_pane import TransactionsPane

    return {
        "Global": HledgerTuiApp.BINDINGS,
        "Summary": SummaryPane.BINDINGS,
        "Transactions": TransactionsPane.BINDINGS,
        "Recurring": RecurringPane.BINDINGS,
        "Budget": BudgetPane.BINDINGS,
        "Reports": ReportsPane.BINDINGS,
        "Accounts": AccountsPane.BINDINGS,
        "Transaction form": TransactionFormScreen.BINDINGS,
        "Recurring form": RecurringFormScreen.BINDINGS,
    }


class TestHelpBindings:
    """The help screen must stay in sync with the panes' BINDINGS."""

    def test_sections_cover_every_pane(self):
        """Every pane the help knows about has a non-empty section."""
        sections = dict(help_sections())
        assert set(sections) == set(_section_bindings())
        for title, rows in sections.items():
            assert rows, f"section {title!r} is empty"

    def test_every_binding_is_listed(self):
        """A binding with a description shows up in its section."""
        for title, rows in help_sections():
            documented = {part for key, _ in rows for part in key.split(" / ")}
            for binding in _section_bindings()[title]:
                if not binding.description:
                    continue
                for part in _format_key(binding.key).split(" / "):
                    assert part in documented, (
                        f"{title}: binding {binding.key!r} "
                        f"({binding.description}) missing from help"
                    )

    def test_no_stale_entries(self):
        """Every documented key belongs to a live binding."""
        for title, rows in help_sections():
            live: set[str] = set()
            for binding in _section_bindings()[title]:
                if binding.description:
                    live.update(_format_key(binding.key).split(" / "))
            for keys, description in rows:
                for part in keys.split(" / "):
                    assert part in live, (
                        f"{title}: help documents {part!r} ({description}) "
                        "but no binding uses it"
                    )

    def test_help_text_renders_sections(self):
        """The rendered text contains each section title and a known key."""
        text = _build_help_text()
        assert "Global" in text
        assert "Transactions" in text
        assert "/" in text
        assert "Esc" in text

    def test_key_labels(self):
        """Named keys are rendered with their symbol."""
        assert _format_key("slash") == "/"
        assert _format_key("question_mark") == "?"
        assert _format_key("left,h") == "Left / h"
        assert _format_key("ctrl+s") == "ctrl+s"


class TestHelpScreenSmoke:
    """The help modal still opens and shows the Shortcuts tab."""

    @pytest.mark.asyncio
    async def test_help_screen_shows_generated_content(self):
        from textual.app import App, ComposeResult

        from hledger_textual.screens.help import HelpScreen

        class _HelpApp(App):
            def compose(self) -> ComposeResult:
                yield HelpScreen()

        app = _HelpApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            content = app.screen.query_one("#help-content")
            assert "Global" in str(content.renderable)
            assert "Reports" in str(content.renderable)
