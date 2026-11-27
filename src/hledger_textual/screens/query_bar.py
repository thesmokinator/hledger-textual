"""Modal screen for viewing and editing the global query (issue #281)."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from hledger_textual.query import InvalidQueryError, validate_query


class QueryBarModal(ModalScreen[str | None]):
    """View, edit, validate and clear the app-wide hledger query.

    Dismisses with the new query on Enter (``""`` clears the filter), or
    with ``None`` when closed without applying.
    """

    BINDINGS = [
        Binding("escape", "dismiss_none", "Close", show=True),
        Binding("ctrl+s", "save_current", "Save", show=True),
        Binding("f", "browse_saved", "Saved", show=True),
    ]

    def __init__(
        self, current_query: str = "", journal_file: Path | str | None = None,
        **kwargs,
    ) -> None:
        """Initialise the modal.

        Args:
            current_query: The active global query shown for editing.
            journal_file: Journal used to validate the query with hledger.
        """
        super().__init__(**kwargs)
        self._current_query = current_query
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Render the query bar dialog."""
        with Vertical(id="query-bar-dialog"):
            yield Static("Global Query", id="query-bar-title")
            yield Input(
                value=self._current_query,
                placeholder="hledger query, e.g. tag:reimbursable not:cleared",
                id="query-bar-input",
            )
            yield Static("", id="query-bar-error")
            yield Static(
                "Enter: apply  ·  f: saved queries  ·  ctrl+s: save"
                "  ·  Escape: cancel",
                id="query-bar-hint",
            )

    def on_mount(self) -> None:
        """Focus the query input."""
        self.query_one("#query-bar-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Validate the query with hledger, then apply it or show the error."""
        query = event.value.strip()
        if self._journal_file is not None:
            try:
                validate_query(self._journal_file, query)
            except InvalidQueryError as exc:
                self.query_one("#query-bar-error", Static).update(
                    f"[red]{exc}[/red]"
                )
                return
        self.dismiss(query)

    def action_save_current(self) -> None:
        """Save the current input as a named filter (shared store)."""
        from hledger_textual.screens.save_filter import SaveFilterModal

        current = self.query_one("#query-bar-input", Input).value
        self.app.push_screen(SaveFilterModal(current_query=current))

    def action_browse_saved(self) -> None:
        """Fill the input from a saved filter."""
        from hledger_textual.screens.saved_filters import SavedFiltersModal

        def on_select(query: str | None) -> None:
            if query:
                input_widget = self.query_one("#query-bar-input", Input)
                input_widget.value = query
                input_widget.focus()

        self.app.push_screen(SavedFiltersModal(), callback=on_select)

    def action_dismiss_none(self) -> None:
        """Close the modal without changing the query."""
        self.dismiss(None)
