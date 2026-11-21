"""Reusable "go to period" modal shared by every pane (issue #266).

Accepts hledger-style period expressions — ``2024``, ``2024-03``,
``2024-01..2024-06``, ``2024-03-05..2024-04-02``, ``last month``, ``ytd``,
``all`` — validated against the journal's date span so empty views are
rejected with an explanatory message instead of a blank pane.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from hledger_textual.models import JournalStats
from hledger_textual.period import PeriodSelection, parse_period


class PeriodPickerModal(ModalScreen[PeriodSelection | None]):
    """Prompt for a period expression and jump to it.

    Args:
        journal_stats: Journal statistics carrying the date span; when
            available, selections outside the span are rejected with a
            helpful message.  None skips span validation.
        current: The selection active when the modal opened, used as the
            input placeholder.
    """

    BINDINGS = [
        Binding("escape", "dismiss_modal", "Cancel", show=True),
    ]

    def __init__(
        self,
        journal_stats: JournalStats | None = None,
        current: PeriodSelection | None = None,
        **kwargs,
    ) -> None:
        """Initialise the modal."""
        super().__init__(**kwargs)
        self._journal_stats = journal_stats
        self._current = current

    def compose(self) -> ComposeResult:
        """Render the period dialog."""
        placeholder = (
            self._current.period_expr if self._current is not None else "2024-03"
        )
        with Vertical(id="period-picker-dialog"):
            yield Static("Go to period", id="period-picker-title")
            yield Input(
                placeholder=placeholder,
                id="period-picker-input",
            )
            yield Static(
                "2024 · 2024-03 · 2024-01..2024-06 · 2024-03-05..2024-04-02 · "
                "this/last/next month/year · ytd · all",
                id="period-picker-syntax",
            )
            yield Static("", id="period-picker-error")
            yield Static(
                "Enter: go  ·  Escape: cancel", id="period-picker-hint"
            )

    def on_mount(self) -> None:
        """Focus the input."""
        self.query_one("#period-picker-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Validate the period expression and close the modal."""
        text = event.value.strip()
        if not text:
            self._set_error("Enter a period, e.g. 2024-03")
            return
        selection = parse_period(text)
        if selection is None:
            self._set_error(
                f"Invalid period: {text!r}. "
                "Try 2024, 2024-03, 2024-01..2024-06, last month, ytd."
            )
            return
        stats = self._journal_stats
        if stats is not None and not selection.overlaps_span(
            stats.first_date, stats.last_date
        ):
            self._set_error(
                f"No transactions in that period — this journal spans "
                f"{stats.first_date.isoformat()} to {stats.last_date.isoformat()}."
            )
            return
        self.dismiss(selection)

    def _set_error(self, message: str) -> None:
        """Show a validation error without closing the modal.

        Args:
            message: The user-facing error text.
        """
        self.query_one("#period-picker-error", Static).update(
            f"[red]{message}[/red]"
        )

    def action_dismiss_modal(self) -> None:
        """Close without changing the period."""
        self.dismiss(None)
