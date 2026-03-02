"""Recurring rule form modal for creating and editing recurring transaction rules."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.timer import Timer
from textual.widgets import Button, Input, Label, Select, Static

from hledger_textual.config import load_default_commodity
from hledger_textual.hledger import HledgerError, load_accounts, load_descriptions
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    RecurringRule,
    TransactionStatus,
)
from hledger_textual.recurring import generate_rule_id
from hledger_textual.recurring_engine import validate_period_expression
from hledger_textual.widgets.autocomplete_input import AutocompleteInput
from hledger_textual.widgets.posting_row import PostingRow

STATUS_OPTIONS = [
    ("Unmarked", TransactionStatus.UNMARKED),
    ("Pending (!)", TransactionStatus.PENDING),
    ("Cleared (*)", TransactionStatus.CLEARED),
]

PERIOD_OPTIONS = [
    ("Daily", "daily"),
    ("Weekly", "weekly"),
    ("Every 2 weeks", "every 2 weeks"),
    ("Monthly", "monthly"),
    ("Bimonthly", "bimonthly"),
    ("Quarterly", "quarterly"),
    ("Yearly", "yearly"),
    ("Custom...", "__custom__"),
]


class RecurringFormScreen(ModalScreen[RecurringRule | None]):
    """Centered modal form for creating or editing a recurring rule."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        journal_file: Path,
        rule: RecurringRule | None = None,
    ) -> None:
        """Initialize the form modal.

        Args:
            journal_file: Path to the journal file.
            rule: Existing recurring rule to edit, or None for new.
        """
        super().__init__()
        self.journal_file = journal_file
        self.rule = rule
        self.posting_count = 0
        self.accounts: list[str] = []
        self._validation_timer: Timer | None = None

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing rule."""
        return self.rule is not None

    def _initial_period_value(self) -> str:
        """Return the initial period select value."""
        if not self.is_edit or not self.rule:
            return "monthly"
        known = {val for _, val in PERIOD_OPTIONS if val != "__custom__"}
        if self.rule.period_expr in known:
            return self.rule.period_expr
        return "__custom__"

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        title = "Edit Recurring Rule" if self.is_edit else "New Recurring Rule"

        with Vertical(id="recurring-form-dialog"):
            yield Static(title, id="recurring-form-title")

            with VerticalScroll(id="recurring-form-scroll"):
                # Period field
                with Horizontal(classes="form-field"):
                    yield Label("Period:")
                    yield Select(
                        options=PERIOD_OPTIONS,
                        value=self._initial_period_value(),
                        id="recurring-select-period",
                    )

                # Custom period field (hidden by default)
                with Horizontal(classes="form-field custom-period-field"):
                    yield Label("Custom:")
                    yield Input(
                        value=self.rule.period_expr if self.is_edit and self._initial_period_value() == "__custom__" else "",
                        placeholder="e.g. every 3 months",
                        id="recurring-input-custom-period",
                    )

                with Horizontal(classes="custom-period-hint-row"):
                    yield Label("", classes="hint-spacer")
                    yield Static("", id="custom-period-hint", classes="custom-period-hint")

                # Description field
                with Horizontal(classes="form-field"):
                    yield Label("Description:")
                    yield AutocompleteInput(
                        value=self.rule.description if self.is_edit else "",
                        placeholder="Transaction description",
                        id="recurring-input-description",
                    )

                # Status field
                with Horizontal(classes="form-field"):
                    yield Label("Status:")
                    initial_status = (
                        self.rule.status if self.is_edit else TransactionStatus.UNMARKED
                    )
                    yield Select(
                        options=STATUS_OPTIONS,
                        value=initial_status,
                        id="recurring-select-status",
                    )

                # Code field
                with Horizontal(classes="form-field"):
                    yield Label("Code:")
                    yield Input(
                        value=self.rule.code if self.is_edit else "",
                        placeholder="Optional transaction code",
                        id="recurring-input-code",
                    )

                # Comment field
                with Horizontal(classes="form-field"):
                    yield Label("Comment:")
                    yield Input(
                        value=self.rule.comment if self.is_edit else "",
                        placeholder="Optional comment",
                        id="recurring-input-comment",
                    )

                # Postings section
                yield Static("Postings", id="recurring-postings-header")
                yield Vertical(id="recurring-postings-container")

                with Horizontal(id="recurring-posting-buttons"):
                    yield Button("\\[+] Add posting", id="btn-recurring-add-posting")
                    yield Button("\\[-] Remove last", id="btn-recurring-remove-posting")

            with Horizontal(id="recurring-form-buttons"):
                yield Button("Cancel", id="btn-recurring-cancel")
                yield Button("Save", id="btn-recurring-save")

    def on_mount(self) -> None:
        """Load accounts and descriptions, set up initial posting rows."""
        try:
            self.accounts = load_accounts(self.journal_file)
        except HledgerError:
            self.accounts = []

        try:
            descriptions = load_descriptions(self.journal_file)
        except HledgerError:
            descriptions = []
        if descriptions:
            self.query_one("#recurring-input-description", AutocompleteInput).suggester = (
                SuggestFromList(descriptions, case_sensitive=False)
            )

        # Show/hide custom period field
        self._toggle_custom_period()

        if self.is_edit and self.rule:
            for i, posting in enumerate(self.rule.postings):
                amount_str = ""
                commodity = ""
                if posting.amounts:
                    amt = posting.amounts[0]
                    amount_str = f"{amt.quantity:.2f}"
                    commodity = amt.commodity
                label = f"#{i + 1}:"
                self._add_posting_row(
                    label=label,
                    account=posting.account,
                    amount=amount_str,
                    commodity=commodity,
                )
        else:
            default_commodity = load_default_commodity()
            self._add_posting_row(label="Debit:", commodity=default_commodity)
            self._add_posting_row(label="Credit:", commodity=default_commodity)

    def _toggle_custom_period(self) -> None:
        """Show or hide the custom period input based on the select value."""
        select = self.query_one("#recurring-select-period", Select)
        custom_field = self.query_one(".custom-period-field")
        if select.value == "__custom__":
            custom_field.add_class("visible")
        else:
            custom_field.remove_class("visible")
            self._update_hint("", "")

    def on_select_changed(self, event: Select.Changed) -> None:
        """Handle period select changes."""
        if event.select.id == "recurring-select-period":
            self._toggle_custom_period()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input changes with debounced validation for custom period."""
        if event.input.id != "recurring-input-custom-period":
            return

        if self._validation_timer:
            self._validation_timer.stop()

        value = event.value.strip()
        if not value:
            self._update_hint("", "")
            return

        self._validation_timer = self.set_timer(
            0.3, lambda: self._validate_period(value)
        )

    @work(thread=True)
    def _validate_period(self, expr: str) -> None:
        """Run hledger validation in a background thread."""
        is_valid, error = validate_period_expression(expr)
        if is_valid:
            self.app.call_from_thread(self._update_hint, "valid", f"Valid: {expr}")
        else:
            self.app.call_from_thread(self._update_hint, "invalid", error)

    def _update_hint(self, state: str, message: str) -> None:
        """Update the custom-period-hint label with validation feedback."""
        hint = self.query_one("#custom-period-hint", Static)
        hint_row = self.query_one(".custom-period-hint-row")
        custom_field = self.query_one(".custom-period-field")
        hint.update(message)
        hint.remove_class("valid", "invalid")
        if state:
            hint.add_class(state)
            hint_row.add_class("visible")
            custom_field.add_class("has-hint")
        else:
            hint_row.remove_class("visible")
            custom_field.remove_class("has-hint")

    def _add_posting_row(
        self,
        label: str = "",
        account: str = "",
        amount: str = "",
        commodity: str = "",
    ) -> None:
        """Add a new posting row to the form."""
        container = self.query_one("#recurring-postings-container", Vertical)
        if not label:
            label = f"#{self.posting_count + 1}:"
        row = PostingRow(
            label=label,
            account=account,
            amount=amount,
            commodity=commodity,
            row_index=self.posting_count,
            account_suggestions=self.accounts,
        )
        container.mount(row)
        self.posting_count += 1

    def _remove_last_posting_row(self) -> None:
        """Remove the last posting row from the form."""
        container = self.query_one("#recurring-postings-container", Vertical)
        rows = container.query(PostingRow)
        if len(rows) > 2:
            rows.last().remove()
            self.posting_count -= 1
        else:
            self.notify("Minimum 2 postings required", severity="warning", timeout=3)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        match event.button.id:
            case "btn-recurring-add-posting":
                self._add_posting_row()
            case "btn-recurring-remove-posting":
                self._remove_last_posting_row()
            case "btn-recurring-save":
                self._save()
            case "btn-recurring-cancel":
                self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the form."""
        self.dismiss(None)

    def _save(self) -> None:
        """Validate and save the recurring rule."""
        # Get period expression
        period_select = self.query_one("#recurring-select-period", Select)
        if period_select.value == "__custom__":
            period_expr = self.query_one("#recurring-input-custom-period", Input).value.strip()
            if not period_expr:
                self.notify("Custom period expression is required", severity="error", timeout=3)
                return
            is_valid, error = validate_period_expression(period_expr)
            if not is_valid:
                self.notify(
                    f"Invalid period: {error}",
                    severity="error",
                    timeout=3,
                )
                return
        else:
            period_expr = str(period_select.value)

        description = self.query_one("#recurring-input-description", Input).value.strip()
        if not description:
            self.notify("Description is required", severity="error", timeout=3)
            return

        status = self.query_one("#recurring-select-status", Select).value
        code = self.query_one("#recurring-input-code", Input).value.strip()
        comment = self.query_one("#recurring-input-comment", Input).value.strip()

        # Parse postings
        container = self.query_one("#recurring-postings-container", Vertical)
        posting_rows = list(container.query(PostingRow))

        postings: list[Posting] = []
        for row in posting_rows:
            account = row.account
            if not account:
                continue

            amounts: list[Amount] = []
            if row.amount:
                try:
                    qty = Decimal(row.amount)
                except InvalidOperation:
                    self.notify(
                        f"Invalid amount: {row.amount}",
                        severity="error",
                        timeout=3,
                    )
                    return

                commodity = row.commodity or load_default_commodity()
                style = AmountStyle(
                    commodity_side="L" if not commodity[0].isdigit() else "R",
                    commodity_spaced=len(commodity) > 1,
                    precision=max(
                        abs(qty.as_tuple().exponent)
                        if isinstance(qty.as_tuple().exponent, int)
                        else 2,
                        2,
                    ),
                )
                amounts.append(Amount(commodity=commodity, quantity=qty, style=style))

            postings.append(Posting(account=account, amounts=amounts))

        if len(postings) < 2:
            self.notify(
                "At least 2 postings with accounts are required",
                severity="error",
                timeout=3,
            )
            return

        # Determine rule_id
        if self.is_edit and self.rule:
            rule_id = self.rule.rule_id
            last_generated = self.rule.last_generated
        else:
            rule_id = generate_rule_id(description)
            last_generated = None

        rule = RecurringRule(
            rule_id=rule_id,
            period_expr=period_expr,
            description=description,
            postings=postings,
            status=status if isinstance(status, TransactionStatus) else TransactionStatus.UNMARKED,
            code=code,
            comment=comment,
            last_generated=last_generated,
        )

        self.dismiss(rule)
