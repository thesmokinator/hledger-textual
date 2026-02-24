"""Transaction form modal for creating and editing transactions."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from hledger_tui.hledger import HledgerError, load_accounts
from hledger_tui.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)
from hledger_tui.widgets.posting_row import PostingRow

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STATUS_OPTIONS = [
    ("Unmarked", TransactionStatus.UNMARKED),
    ("Pending (!)", TransactionStatus.PENDING),
    ("Cleared (*)", TransactionStatus.CLEARED),
]


class TransactionFormScreen(ModalScreen[Transaction | None]):
    """Centered modal form for creating or editing a transaction."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        journal_file: Path,
        transaction: Transaction | None = None,
    ) -> None:
        """Initialize the form modal.

        Args:
            journal_file: Path to the journal file.
            transaction: Existing transaction to edit, or None for new.
        """
        super().__init__()
        self.journal_file = journal_file
        self.transaction = transaction
        self.posting_count = 0
        self.accounts: list[str] = []

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing transaction."""
        return self.transaction is not None

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        title = "Edit Transaction" if self.is_edit else "New Transaction"

        with Vertical(id="form-dialog"):
            yield Static(title, id="form-title")

            with VerticalScroll(id="form-scroll"):
                # Date field
                with Horizontal(classes="form-field"):
                    yield Label("Date:")
                    yield Input(
                        value=self.transaction.date if self.is_edit else date.today().isoformat(),
                        placeholder="YYYY-MM-DD",
                        id="input-date",
                        max_length=10,
                    )

                # Description field
                with Horizontal(classes="form-field"):
                    yield Label("Description:")
                    yield Input(
                        value=self.transaction.description if self.is_edit else "",
                        placeholder="Transaction description",
                        id="input-description",
                    )

                # Status field
                with Horizontal(classes="form-field"):
                    yield Label("Status:")
                    initial_status = (
                        self.transaction.status if self.is_edit else TransactionStatus.UNMARKED
                    )
                    yield Select(
                        options=STATUS_OPTIONS,
                        value=initial_status,
                        id="select-status",
                    )

                # Code field
                with Horizontal(classes="form-field"):
                    yield Label("Code:")
                    yield Input(
                        value=self.transaction.code if self.is_edit else "",
                        placeholder="Optional transaction code",
                        id="input-code",
                    )

                # Comment field
                with Horizontal(classes="form-field"):
                    yield Label("Comment:")
                    yield Input(
                        value=self.transaction.comment if self.is_edit else "",
                        placeholder="Optional comment",
                        id="input-comment",
                    )

                # Postings section
                yield Static("Postings", id="postings-header")
                yield Vertical(id="postings-container")

                with Horizontal(id="posting-buttons"):
                    yield Button("\\[+] Add posting", id="btn-add-posting")
                    yield Button("\\[-] Remove last", id="btn-remove-posting")

            with Horizontal(id="form-buttons"):
                yield Button("Cancel", id="btn-form-cancel")
                yield Button("Save", id="btn-save")

    def on_mount(self) -> None:
        """Load accounts for autocomplete and add initial posting rows."""
        try:
            self.accounts = load_accounts(self.journal_file)
        except HledgerError:
            self.accounts = []

        if self.is_edit and self.transaction:
            for i, posting in enumerate(self.transaction.postings):
                amount_str = ""
                commodity = ""
                if posting.amounts:
                    amt = posting.amounts[0]
                    amount_str = str(amt.quantity)
                    commodity = amt.commodity
                label = f"#{i + 1}:"
                self._add_posting_row(
                    label=label,
                    account=posting.account,
                    amount=amount_str,
                    commodity=commodity,
                )
        else:
            self._add_posting_row(label="Debit:")
            self._add_posting_row(label="Credit:")

    def _add_posting_row(
        self,
        label: str = "",
        account: str = "",
        amount: str = "",
        commodity: str = "",
    ) -> None:
        """Add a new posting row to the form."""
        container = self.query_one("#postings-container", Vertical)
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
        container = self.query_one("#postings-container", Vertical)
        rows = container.query(PostingRow)
        if len(rows) > 2:
            rows.last().remove()
            self.posting_count -= 1
        else:
            self.notify("Minimum 2 postings required", severity="warning", timeout=3)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        match event.button.id:
            case "btn-add-posting":
                self._add_posting_row()
            case "btn-remove-posting":
                self._remove_last_posting_row()
            case "btn-save":
                self._save()
            case "btn-form-cancel":
                self.dismiss(None)

    def action_cancel(self) -> None:
        """Cancel the form."""
        self.dismiss(None)

    def _validate_date(self, date_str: str) -> bool:
        """Validate that the date is in ISO format YYYY-MM-DD.

        Args:
            date_str: The date string to validate.

        Returns:
            True if the date is valid.
        """
        if not DATE_RE.match(date_str):
            return False
        try:
            year, month, day = date_str.split("-")
            date(int(year), int(month), int(day))
            return True
        except ValueError:
            return False

    def _save(self) -> None:
        """Validate and save the transaction."""
        date_str = self.query_one("#input-date", Input).value.strip()
        description = self.query_one("#input-description", Input).value.strip()
        status = self.query_one("#select-status", Select).value
        code = self.query_one("#input-code", Input).value.strip()
        comment = self.query_one("#input-comment", Input).value.strip()

        # Date validation
        if not date_str:
            self.notify("Date is required", severity="error", timeout=3)
            return

        if not self._validate_date(date_str):
            self.notify(
                "Invalid date. Use ISO format: YYYY-MM-DD",
                severity="error",
                timeout=3,
            )
            return

        if not description:
            self.notify("Description is required", severity="error", timeout=3)
            return

        # Parse postings
        container = self.query_one("#postings-container", Vertical)
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

                commodity = row.commodity or "€"
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

        transaction = Transaction(
            index=0,
            date=date_str,
            description=description,
            status=status if isinstance(status, TransactionStatus) else TransactionStatus.UNMARKED,
            code=code,
            comment=comment,
            postings=postings,
        )

        self.dismiss(transaction)
