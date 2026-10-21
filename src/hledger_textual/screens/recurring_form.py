"""Form modal for creating and editing recurring rules."""

from __future__ import annotations

import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static

from hledger_textual.amountutil import describe_amount_error
from hledger_textual.config import load_default_commodity
from hledger_textual.dateutil import describe_iso_date_error
from hledger_textual.models import Amount, AmountStyle, Posting, RecurringRule, TransactionStatus
from hledger_textual.recurring import SUPPORTED_PERIODS, validate_period_expr
from hledger_textual.screens._form_account_suggestions import FormAccountSuggestionsMixin
from hledger_textual.screens._dirty_guard import DirtyGuardMixin
from hledger_textual.screens.form_base import FormScreenBase
from hledger_textual.widgets.constants import RECURRING_PERIOD_OPTIONS
from hledger_textual.widgets.date_input import DateInput
from hledger_textual.widgets.posting_row import PostingRow
from hledger_textual.widgets.posting_sum import (
    collect_posting_totals,
    format_posting_sum,
)

def _slugify(text: str) -> str:
    """Convert a description string to a slug suitable for use as a rule ID prefix.

    Args:
        text: The description to slugify.

    Returns:
        A lowercase, hyphen-separated slug.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "rule"


class RecurringFormScreen(
    FormAccountSuggestionsMixin, DirtyGuardMixin, FormScreenBase[RecurringRule | None]
):
    """Centered modal form for creating or editing a recurring rule."""

    def __init__(
        self,
        journal_file: Path,
        rule: RecurringRule | None = None,
        clone: bool = False,
    ) -> None:
        """Initialize the form modal.

        Args:
            journal_file: Path to the journal file.
            rule: Existing recurring rule to edit, or None for new.
            clone: If True, pre-fill from *rule* but treat it as a new rule.
        """
        super().__init__()
        self.journal_file = journal_file
        self.rule = rule
        self._clone = clone
        self.posting_count = 0
        self.accounts: list[str] = []

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing rule."""
        return self.rule is not None and not self._clone

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        if self._clone:
            title = "Clone Recurring Rule"
        else:
            title = "Edit Recurring Rule" if self.is_edit else "New Recurring Rule"
        r = self.rule

        # Determine initial period selection and custom expression
        if r and r.period_expr not in SUPPORTED_PERIODS:
            initial_period = "custom"
            initial_custom = r.period_expr
        else:
            initial_period = r.period_expr if r else "monthly"
            initial_custom = ""

        with Vertical(id="form-dialog"):
            yield Static(title, id="form-title")

            with VerticalScroll(id="form-scroll"):
                with Horizontal(classes="form-field form-field--required"):
                    yield Label("Description:*")
                    yield Input(
                        value=r.description if r else "",
                        placeholder="e.g. Rent payment",
                        id="recurring-input-description",
                    )

                with Horizontal(classes="form-field form-field--required"):
                    yield Label("Period:*")
                    yield Select(
                        options=RECURRING_PERIOD_OPTIONS,
                        value=initial_period,
                        id="recurring-select-period",
                    )

                with Horizontal(classes="form-field form-field--required", id="recurring-custom-period-row"):
                    yield Label("Expression:*")
                    yield Input(
                        value=initial_custom,
                        placeholder="e.g. every 2 weeks  (also: every 3 days, monthly)",
                        id="recurring-input-custom-period",
                    )

                # Inline hint mirroring hledger's periodic-rules grammar so
                # users don't have to flip to the docs to discover what's
                # accepted. Sits above the validation feedback below.
                with Horizontal(classes="form-field", id="recurring-custom-period-hint-row"):
                    yield Label(
                        "Examples: every 2 weeks · every 3 days · weekly · biweekly · monthly",
                        id="recurring-custom-period-hint",
                        classes="form-hint",
                    )

                # Live validation feedback. Empty until the user submits
                # (Enter / focus-out); errors render here. Cleared whenever
                # the input becomes valid again.
                with Horizontal(classes="form-field", id="recurring-custom-period-error-row"):
                    yield Label(
                        "",
                        id="recurring-custom-period-error",
                        classes="form-error",
                    )

                with Horizontal(classes="form-field form-field--required"):
                    yield Label("Start date:*")
                    yield DateInput(
                        value=r.start_date if (r and r.start_date) else date.today().isoformat(),
                        id="recurring-input-start",
                    )

                with Horizontal(classes="form-field form-field--optional"):
                    yield Label("End date:")
                    yield DateInput(
                        value=r.end_date if (r and r.end_date) else "",
                        placeholder="YYYY-MM-DD (optional)",
                        id="recurring-input-end",
                    )

                yield Static("Postings*", id="postings-header")
                yield Vertical(id="postings-container")
                yield Static("", id="postings-sum")

                with Horizontal(id="posting-buttons"):
                    yield Button("\\[+] Add posting", id="btn-add-posting")
                    yield Button("\\[-] Remove last", id="btn-remove-posting")

            yield Static("* required", classes="form-required-footer")

            with Horizontal(id="form-buttons"):
                yield Button("Cancel", variant="default", id="btn-form-cancel")
                yield Button("Save", variant="primary", id="btn-save")

    def on_mount(self) -> None:
        """Load accounts for autocomplete and populate posting rows."""
        self._configure_account_suggestions()

        # Hide custom expression row unless the period is already "custom"
        period_select = self.query_one("#recurring-select-period", Select)
        if period_select.value != "custom":
            self.query_one("#recurring-custom-period-row").display = False

        if self.is_edit and self.rule:
            for i, posting in enumerate(self.rule.postings):
                amount_str = ""
                commodity = ""
                if posting.amounts:
                    amt = posting.amounts[0]
                    amount_str = f"{amt.quantity:.2f}"
                    commodity = amt.commodity
                self._add_posting_row(
                    label=f"#{i + 1}:",
                    account=posting.account,
                    amount=amount_str,
                    commodity=commodity,
                )
        else:
            default_commodity = load_default_commodity()
            self._add_posting_row(label="Debit:", commodity=default_commodity)
            self._add_posting_row(label="Credit:", commodity="")

        self.call_after_refresh(self.capture_initial_state)
        self.call_after_refresh(self._update_posting_sum)

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
        self.call_after_refresh(self._update_posting_sum)

    def _remove_last_posting_row(self) -> None:
        """Remove the last posting row from the form."""
        container = self.query_one("#postings-container", Vertical)
        rows = container.query(PostingRow)
        if len(rows) > 0:
            rows.last().remove()
            self.posting_count -= 1
            self.call_after_refresh(self._update_posting_sum)

    def _parse_posting_amount(
        self, text: str, commodity: str
    ) -> tuple[Decimal, str] | None:
        """Parse a plain-decimal posting amount for the running sum."""
        try:
            return Decimal(text), commodity or load_default_commodity()
        except InvalidOperation:
            return None

    def _update_posting_sum(self) -> None:
        """Recompute the running balance shown under the posting rows."""
        if not self.is_attached or not self.query("#postings-sum"):
            return
        widget = self.query_one("#postings-sum", Static)
        rows = list(self.query_one("#postings-container", Vertical).query(PostingRow))
        totals, incomplete = collect_posting_totals(rows, self._parse_posting_amount)
        widget.update(
            format_posting_sum(totals, incomplete, load_default_commodity())
        )

    @on(Input.Changed, ".amount-input")
    def on_amount_changed(self, event: Input.Changed) -> None:
        """Refresh the running balance as the user types an amount."""
        self._update_posting_sum()

    @on(Select.Changed, "#recurring-select-period")
    def on_recurring_select_period_changed(self, event: Select.Changed) -> None:
        """Show or hide the custom expression field based on period selection."""
        is_custom = event.value == "custom"
        for row_id in (
            "#recurring-custom-period-row",
            "#recurring-custom-period-hint-row",
            "#recurring-custom-period-error-row",
        ):
            self.query_one(row_id).display = is_custom
        if not is_custom:
            # Leave no stale error visible if the user flips back to a preset.
            self.query_one("#recurring-custom-period-error", Label).update("")

    @on(Input.Submitted, "#recurring-input-custom-period")
    def on_custom_period_submitted(self, event: Input.Submitted) -> None:
        """Validate the custom hledger period expression on submit (Enter).

        Catches typos before the user reaches the Save button. The same
        check still runs in :meth:`_save`; this just surfaces the error
        sooner.
        """
        self._refresh_custom_period_feedback(event.value)

    @on(Input.Changed, "#recurring-input-custom-period")
    def on_custom_period_changed(self, event: Input.Changed) -> None:
        """Clear any prior validation error as soon as the user edits."""
        # Avoid running hledger on every keystroke; just clear the error
        # so the form doesn't show a stale message while the user is mid-type.
        # Re-validation happens on Submitted (Enter) or Save.
        if not event.value.strip():
            self.query_one("#recurring-custom-period-error", Label).update("")
        else:
            current = self.query_one("#recurring-custom-period-error", Label)
            if str(current.renderable):
                current.update("")

    def _refresh_custom_period_feedback(self, expr: str) -> None:
        """Run :func:`validate_period_expr` and render the result inline."""
        error_label = self.query_one("#recurring-custom-period-error", Label)
        expr = expr.strip()
        if not expr:
            error_label.update("")
            return
        if validate_period_expr(expr):
            error_label.update("")
        else:
            error_label.update(f"Invalid period: {expr!r}. Try 'every 2 weeks' or 'every 3 days'.")

    def _on_extra_button(self, event: Button.Pressed) -> bool:
        """Handle posting-row buttons; Save/Cancel are routed by the base."""
        match event.button.id:
            case "btn-add-posting":
                self._add_posting_row()
            case "btn-remove-posting":
                self._remove_last_posting_row()
            case _:
                return False
        return True

    def _save(self) -> None:
        """Validate inputs and dismiss with a RecurringRule (or None on cancel)."""
        description = self.query_one("#recurring-input-description", Input).value.strip()
        period = self.query_one("#recurring-select-period", Select).value
        start_str = self.query_one("#recurring-input-start", Input).value.strip()
        end_str = self.query_one("#recurring-input-end", Input).value.strip()

        if not description:
            self.notify("Description is required", severity="error", timeout=3)
            return

        if period == "custom":
            custom_expr = self.query_one("#recurring-input-custom-period", Input).value.strip()
            if not custom_expr:
                self.notify("Custom period expression is required", severity="error", timeout=3)
                return
            if not validate_period_expr(custom_expr):
                self.notify(
                    f"Invalid period expression: {custom_expr!r}",
                    severity="error",
                    timeout=5,
                )
                return
            period = custom_expr
        elif not period or period == Select.BLANK:
            self.notify("Period is required", severity="error", timeout=3)
            return

        start_error = describe_iso_date_error(start_str) if start_str else None
        if start_error:
            self.notify(f"Invalid start date: {start_error}", severity="error", timeout=4)
            return

        end_error = describe_iso_date_error(end_str) if end_str else None
        if end_error:
            self.notify(f"Invalid end date: {end_error}", severity="error", timeout=4)
            return

        # Collect postings
        container = self.query_one("#postings-container", Vertical)
        rows = list(container.query(PostingRow))
        postings: list[Posting] = []
        default_commodity = load_default_commodity()

        for row in rows:
            account = row.account
            if not account:
                continue

            amount_str = row.amount
            commodity = row.commodity or default_commodity

            if amount_str:
                try:
                    quantity = Decimal(amount_str)
                except InvalidOperation:
                    self.notify(
                        f"Invalid amount: {describe_amount_error(amount_str)}",
                        severity="error",
                        timeout=4,
                    )
                    return

                style = AmountStyle(
                    commodity_side="L",
                    commodity_spaced=False,
                    precision=max(
                        abs(quantity.as_tuple().exponent) if isinstance(quantity.as_tuple().exponent, int) else 2,
                        2,
                    ),
                )
                postings.append(
                    Posting(
                        account=account,
                        amounts=[Amount(commodity=commodity, quantity=quantity, style=style)],
                    )
                )
            else:
                postings.append(Posting(account=account, amounts=[]))

        # Generate or preserve rule_id
        if self.is_edit and self.rule:
            rule_id = self.rule.rule_id
        else:
            slug = _slugify(description)
            short_id = uuid.uuid4().hex[:6]
            rule_id = f"{slug}-{short_id}"

        self.dismiss(
            RecurringRule(
                rule_id=rule_id,
                period_expr=str(period),
                description=description,
                postings=postings,
                status=TransactionStatus.UNMARKED,
                start_date=start_str or None,
                end_date=end_str or None,
            )
        )
