"""Preview and confirm any directive write before it touches the journal (issue #273).

Directive writes (include insertions, account-note edits) show the exact
target file and line diff first.  A "Don't ask again" check persists
``confirm_directive_writes = false`` in the config; setting the key back
to ``true`` restores the prompt.
"""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from hledger_textual.config import (
    load_confirm_directive_writes,
    save_confirm_directive_writes,
)
from hledger_textual.models import DirectiveWritePlan


def confirm_directive_writes(
    widget,
    plans: list[DirectiveWritePlan],
    reason: str,
    on_ok: Callable[[], None],
) -> None:
    """Run *on_ok* after previewing the directive writes, when enabled.

    When ``confirm_directive_writes`` is disabled in config the callback
    runs immediately.  Otherwise the preview modal is pushed; cancelling
    leaves every file untouched.

    Args:
        widget: The widget initiating the write (provides ``app``).
        plans: The planned writes to preview.
        reason: A human explanation of why the directive is written.
        on_ok: Zero-arg callback running the confirmed write.
    """
    if not load_confirm_directive_writes():
        on_ok()
        return
    if not plans:
        on_ok()
        return

    from hledger_textual.screens.directive_confirm import DirectiveConfirmModal

    def on_result(result: tuple[bool, bool] | None) -> None:
        if result is None:
            return
        confirmed, dont_ask = result
        if dont_ask:
            save_confirm_directive_writes(False)
        if confirmed:
            on_ok()

    widget.app.push_screen(
        DirectiveConfirmModal(plans, reason), callback=on_result
    )


class DirectiveConfirmModal(ModalScreen[tuple[bool, bool] | None]):
    """Show the exact diff of upcoming directive writes and ask for confirmation.

    Args:
        plans: The planned writes (target file, added/removed lines).
        reason: Why the directive is needed.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=True),
    ]

    def __init__(self, plans: list[DirectiveWritePlan], reason: str, **kwargs) -> None:
        """Initialise the modal."""
        super().__init__(**kwargs)
        self._plans = plans
        self._reason = reason

    def compose(self) -> ComposeResult:
        """Render the preview dialog."""
        with Vertical(id="directive-confirm-dialog"):
            yield Static("Confirm journal changes", id="directive-confirm-title")
            yield Static(self._reason, id="directive-confirm-reason")
            yield Static(self._diff_text(), id="directive-confirm-diff")
            yield Checkbox("Don't ask again", id="directive-confirm-dont-ask")
            with Vertical(id="directive-confirm-buttons"):
                yield Button("Confirm", id="btn-directive-confirm", variant="primary")
                yield Button("Cancel", id="btn-directive-cancel")

    def _diff_text(self) -> str:
        """Render the plans as a file-by-file diff preview."""
        try:
            journal_dir = self._plans[0].target_file.parents[0]
        except IndexError:
            journal_dir = None
        parts: list[str] = []
        for plan in self._plans:
            try:
                rel = plan.target_file.relative_to(journal_dir)
            except ValueError:
                rel = plan.target_file
            if plan.creates_file:
                parts.append(f"[bold]Create {rel}[/bold] (new file)")
                continue
            parts.append(f"[bold]{rel}[/bold]")
            for line in plan.added:
                parts.append(f"  [green]+ {line}[/green]")
            for line in plan.removed:
                parts.append(f"  [red]- {line}[/red]")
        return "\n".join(parts)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Confirm / Cancel."""
        if event.button.id == "btn-directive-confirm":
            dont_ask = self.query_one("#directive-confirm-dont-ask", Checkbox).value
            self.dismiss((True, dont_ask))
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Close without writing."""
        self.dismiss(None)
