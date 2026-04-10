"""Transaction form modal for creating and editing transactions."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import SuggestFromList
from textual.widgets import Button, Input, Label, Select, Static

from hledger_textual.config import load_default_commodity
from hledger_textual.hledger import (
    HledgerError,
    load_accounts,
    load_descriptions,
    load_investment_cost,
    load_investment_positions,
)
from hledger_textual.models import (
    Amount,
    AmountStyle,
    Posting,
    Transaction,
    TransactionStatus,
)
from hledger_textual.widgets.autocomplete_input import AutocompleteInput
from hledger_textual.widgets.date_input import DateInput
from hledger_textual.widgets.posting_row import PostingRow

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------------------
# Hledger amount string parser
# ---------------------------------------------------------------------------
_SYM = r"[€$£¥₿₹]"
_NAME = r"[A-Za-z][A-Za-z0-9.]*"
_COMMODITY = rf"(?:{_SYM}|{_NAME})"
_UNSIGNED_QTY = r"\d+(?:\.\d+)?"
_SIGNED_QTY = r"-?\d+(?:\.\d+)?"

# -5.00 XEON @@ €742.59  OR  -5.00 XEON @ €148.518
_AMOUNT_COST_RE = re.compile(rf"^({_SIGNED_QTY})\s+({_COMMODITY})\s+(@@?)\s+(.+)$")
# -5.00 XEON  OR  5 USD
_AMOUNT_QTY_COMM_RE = re.compile(rf"^({_SIGNED_QTY})\s+({_COMMODITY})\s*$")
# €742.59  OR  -€742.59
_AMOUNT_SYM_QTY_RE = re.compile(rf"^(-?)({_SYM})({_UNSIGNED_QTY})\s*$")


def _decimal_places(qty_str: str) -> int:
    """Return the number of decimal places in a numeric string."""
    return len(qty_str.split(".")[1]) if "." in qty_str else 0


def _extract_commodity_and_qty(
    s: str,
) -> tuple[Decimal, str, Decimal | None] | None:
    """Extract signed quantity, commodity name, and optional total proceeds.

    Handles amounts with named commodities such as ``-5 XEON`` or
    ``-5 XEON @@ €742.55``.  Returns ``None`` for currency-symbol-prefixed
    amounts (``€50``) and plain numbers.

    Args:
        s: Raw amount string entered by the user.

    Returns:
        ``(signed_qty, commodity, proceeds)`` when a named commodity is found,
        else ``None``.  ``signed_qty`` preserves the original sign so callers
        can distinguish sells (negative) from buys (positive).  ``proceeds``
        is the total transaction value when a cost annotation (``@`` or ``@@``)
        is present and parseable, otherwise ``None``.
    """
    s = s.strip()
    m = _AMOUNT_COST_RE.match(s)
    if m:
        qty_str, commodity, at_sign, cost_str = (
            m.group(1), m.group(2), m.group(3), m.group(4)
        )
        qty = Decimal(qty_str)
        proceeds: Decimal | None = None
        cost_amount = _parse_simple_amount_str(cost_str.strip(), "")
        if cost_amount is not None:
            if at_sign == "@":
                proceeds = abs(cost_amount.quantity) * abs(qty)
            else:  # @@
                proceeds = abs(cost_amount.quantity)
        return qty, commodity, proceeds
    m = _AMOUNT_QTY_COMM_RE.match(s)
    if m:
        qty_str, commodity = m.groups()
        return Decimal(qty_str), commodity, None
    return None


def _build_commodity_data(
    positions: list[tuple[str, Decimal, str]],
    costs: dict[str, tuple[Decimal, str]],
) -> dict[str, tuple[Decimal, Decimal, str]]:
    """Build a per-commodity summary of positions and book costs.

    Cross-joins positions and costs by account.  If any account contributing
    to a commodity has no cost entry, that commodity is excluded entirely.

    Args:
        positions: ``(account, quantity, commodity)`` from
            :func:`load_investment_positions`.
        costs: ``{account: (cost_amount, currency)}`` from
            :func:`load_investment_cost`.

    Returns:
        ``{commodity: (total_units, total_cost, currency)}``.
        Commodities with zero or negative total units are excluded.
    """
    units: dict[str, Decimal] = {}
    total_cost: dict[str, Decimal] = {}
    currency_map: dict[str, str] = {}
    excluded: set[str] = set()

    for account, qty, commodity in positions:
        if commodity in excluded:
            continue
        if account not in costs:
            excluded.add(commodity)
            units.pop(commodity, None)
            total_cost.pop(commodity, None)
            currency_map.pop(commodity, None)
            continue
        cost_amount, currency = costs[account]
        units[commodity] = units.get(commodity, Decimal(0)) + qty
        total_cost[commodity] = total_cost.get(commodity, Decimal(0)) + cost_amount
        if commodity not in currency_map:
            currency_map[commodity] = currency

    result: dict[str, tuple[Decimal, Decimal, str]] = {}
    for commodity, total_units in units.items():
        if total_units <= 0:
            continue
        result[commodity] = (
            total_units,
            total_cost.get(commodity, Decimal(0)),
            currency_map.get(commodity, ""),
        )
    return result


def _parse_simple_amount_str(s: str, default_commodity: str) -> Amount | None:
    """Parse a simple hledger amount string (no cost annotation).

    Handles: ``€742.59``, ``-€742.59``, ``-5.00 XEON``, ``742.59``.
    Returns None if the string cannot be parsed.
    """
    s = s.strip()

    m = _AMOUNT_SYM_QTY_RE.match(s)
    if m:
        sign, sym, qty_str = m.groups()
        qty = Decimal(f"{sign}{qty_str}")
        style = AmountStyle(
            commodity_side="L",
            commodity_spaced=False,
            precision=max(_decimal_places(qty_str), 2),
        )
        return Amount(commodity=sym, quantity=qty, style=style)

    m = _AMOUNT_QTY_COMM_RE.match(s)
    if m:
        qty_str, commodity = m.groups()
        qty = Decimal(qty_str)
        style = AmountStyle(
            commodity_side="R",
            commodity_spaced=True,
            precision=_decimal_places(qty_str),
        )
        return Amount(commodity=commodity, quantity=qty, style=style)

    try:
        qty = Decimal(s)
        style = AmountStyle(
            commodity_side="L" if not default_commodity[:1].isdigit() else "R",
            commodity_spaced=len(default_commodity) > 1,
            precision=max(_decimal_places(s), 2),
        )
        return Amount(commodity=default_commodity, quantity=qty, style=style)
    except InvalidOperation:
        return None


def parse_amount_str(s: str, default_commodity: str) -> Amount | None:
    """Parse a hledger amount string including an optional cost annotation.

    Supports:

    - Simple number: ``742.59``, ``-742.59``
    - Currency prefix: ``€742.59``, ``-€742.59``
    - Quantity + commodity: ``-5.00 XEON``, ``5 USD``
    - With total cost: ``-5.00 XEON @@ €742.59``
    - With unit cost: ``-5.00 XEON @ €148.518`` (converted to total cost)

    Returns None if the string cannot be parsed.
    """
    s = s.strip()
    if not s:
        return None

    m = _AMOUNT_COST_RE.match(s)
    if m:
        qty_str, commodity, at_sign, cost_str = m.groups()
        qty = Decimal(qty_str)
        style = AmountStyle(
            commodity_side="R",
            commodity_spaced=True,
            precision=_decimal_places(qty_str),
        )
        cost_amount = _parse_simple_amount_str(cost_str.strip(), default_commodity)
        if cost_amount is None:
            return None
        if at_sign == "@":
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity * qty),
                style=cost_amount.style,
            )
        else:
            # Normalise @@ cost to always positive (hledger requires it).
            cost_amount = Amount(
                commodity=cost_amount.commodity,
                quantity=abs(cost_amount.quantity),
                style=cost_amount.style,
            )
        return Amount(commodity=commodity, quantity=qty, style=style, cost=cost_amount)

    return _parse_simple_amount_str(s, default_commodity)

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
        clone: bool = False,
    ) -> None:
        """Initialize the form modal.

        Args:
            journal_file: Path to the journal file.
            transaction: Existing transaction to edit, or None for new.
            clone: If True, pre-fill from *transaction* but treat as new.
        """
        super().__init__()
        self.journal_file = journal_file
        self.transaction = transaction
        self._clone = clone
        self.posting_count = 0
        self.accounts: list[str] = []
        self.commodity_data: dict[str, tuple[Decimal, Decimal, str]] = {}

    @property
    def _has_template(self) -> bool:
        """Whether a transaction template is available for pre-filling."""
        return self.transaction is not None

    @property
    def is_edit(self) -> bool:
        """Whether this form is editing an existing transaction."""
        return self._has_template and not self._clone

    def compose(self) -> ComposeResult:
        """Create the modal form layout."""
        if self._clone:
            title = "Clone Transaction"
        elif self.is_edit:
            title = "Edit Transaction"
        else:
            title = "New Transaction"

        with Vertical(id="form-dialog"):
            yield Static(title, id="form-title")

            with VerticalScroll(id="form-scroll"):
                # Date field
                with Horizontal(classes="form-field"):
                    yield Label("Date:")
                    yield DateInput(
                        value=self.transaction.date if self._has_template else date.today().isoformat(),
                        id="input-date",
                    )

                # Description field
                with Horizontal(classes="form-field"):
                    yield Label("Description:")
                    yield AutocompleteInput(
                        value=self.transaction.description if self._has_template else "",
                        placeholder="Transaction description",
                        id="input-description",
                    )

                # Status field
                with Horizontal(classes="form-field"):
                    yield Label("Status:")
                    initial_status = (
                        self.transaction.status if self._has_template else TransactionStatus.UNMARKED
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
                        value=self.transaction.code if self._has_template else "",
                        placeholder="Optional transaction code",
                        id="input-code",
                    )

                # Comment field
                with Horizontal(classes="form-field"):
                    yield Label("Comment:")
                    yield Input(
                        value=self.transaction.comment if self._has_template else "",
                        placeholder="Optional comment",
                        id="input-comment",
                    )

                # Postings section
                yield Static("Postings", id="postings-header")
                yield Static(
                    "Amount: plain number (50.00), currency prefix (€50.00), "
                    "or commodity with cost (-5 STCK @@ €200.00 / -5 STCK @ €40.00). "
                    "Leave one amount blank to auto-balance.",
                    id="postings-hint",
                )
                yield Static(
                    f"Default commodity: {load_default_commodity()}",
                    id="default-commodity-hint",
                )
                yield Vertical(id="postings-container")
                yield Static("", id="cost-basis-hint")

                with Horizontal(id="posting-buttons"):
                    yield Button("\\[+] Add posting", id="btn-add-posting")
                    yield Button("\\[-] Remove last", id="btn-remove-posting")

            with Horizontal(id="form-buttons"):
                yield Button("Cancel", variant="default", id="btn-form-cancel")
                yield Button("Save", variant="primary", id="btn-save")

    def on_mount(self) -> None:
        """Load accounts and descriptions for autocomplete, and add initial posting rows."""
        try:
            self.accounts = load_accounts(self.journal_file)
        except HledgerError:
            self.accounts = []

        try:
            descriptions = load_descriptions(self.journal_file)
        except HledgerError:
            descriptions = []
        if descriptions:
            self.query_one("#input-description", AutocompleteInput).suggester = (
                SuggestFromList(descriptions, case_sensitive=False)
            )

        self._load_commodity_data()

        if self._has_template:
            for i, posting in enumerate(self.transaction.postings):
                amount_str = ""
                commodity = load_default_commodity()
                if posting.amounts:
                    amt = posting.amounts[0]
                    if amt.cost is not None:
                        # Complex amount with cost annotation: preserve as full string.
                        amount_str = amt.format()
                    else:
                        amount_str = f"{amt.quantity:.{amt.style.precision}f}"
                        commodity = amt.commodity
                label = f"#{i + 1}:"
                self._add_posting_row(
                    label=label,
                    account=posting.account,
                    amount=amount_str,
                    commodity=commodity,
                    initial_amounts=posting.amounts if posting.amounts else None,
                )
        else:
            default_commodity = load_default_commodity()
            self._add_posting_row(label="#1:", commodity=default_commodity)
            self._add_posting_row(label="#2:", commodity=default_commodity)

    def _add_posting_row(
        self,
        label: str = "",
        account: str = "",
        amount: str = "",
        commodity: str = "",
        initial_amounts: list[Amount] | None = None,
    ) -> None:
        """Add a new posting row to the form."""
        container = self.query_one("#postings-container", Vertical)
        if not label:
            label = f"#{self.posting_count + 1}:"
        if not commodity:
            commodity = load_default_commodity()
        row = PostingRow(
            label=label,
            account=account,
            amount=amount,
            commodity=commodity,
            row_index=self.posting_count,
            account_suggestions=self.accounts,
            initial_amounts=initial_amounts,
        )
        container.mount(row)
        self.posting_count += 1

    def _remove_last_posting_row(self) -> None:
        """Remove the last posting row from the form."""
        container = self.query_one("#postings-container", Vertical)
        rows = container.query(PostingRow)
        if len(rows) > 0:
            rows.last().remove()
            self.posting_count -= 1

    @work(thread=True, exclusive=True)
    def _load_commodity_data(self) -> None:
        """Load investment positions and costs in a background thread."""
        try:
            positions = load_investment_positions(self.journal_file)
            costs = load_investment_cost(self.journal_file)
            data = _build_commodity_data(positions, costs)
        except HledgerError:
            data = {}
        self.app.call_from_thread(self._set_commodity_data, data)

    def _set_commodity_data(self, data: dict[str, tuple[Decimal, Decimal, str]]) -> None:
        """Update commodity data and refresh any already-typed amount hints.

        Args:
            data: Commodity summary from :func:`_build_commodity_data`.
        """
        self.commodity_data = data
        hint_widget = self.query_one("#cost-basis-hint", Static)
        container = self.query_one("#postings-container", Vertical)
        for row in container.query(PostingRow):
            amount_input = row.query_one(f"#amount-{row.row_index}", Input)
            parsed = _extract_commodity_and_qty(amount_input.value)
            if parsed:
                qty, commodity, proceeds = parsed
                hint = self._build_cost_hint(commodity, qty, proceeds)
                if hint:
                    hint_widget.update(hint)
                    hint_widget.add_class("visible")
                    return
        hint_widget.update("")
        hint_widget.remove_class("visible")

    def _build_cost_hint(
        self,
        commodity: str,
        qty: Decimal,
        proceeds: Decimal | None = None,
    ) -> str:
        """Build a cost basis hint string for a commodity and quantity.

        When ``qty`` is negative (a sell) and ``proceeds`` are provided, the
        capital gain or loss is appended to the hint.

        Args:
            commodity: The commodity ticker (e.g. ``'XEON'``).
            qty: Signed quantity (negative = sell, positive = buy).
            proceeds: Total sale proceeds when a cost annotation is present.

        Returns:
            A formatted hint string, or empty string if commodity not in data.
        """
        if commodity not in self.commodity_data:
            return ""
        total_units, total_cost, currency = self.commodity_data[commodity]
        avg_cost = total_cost / total_units
        abs_qty = abs(qty)
        cost_basis = abs_qty * avg_cost

        def _fmt(d: Decimal) -> str:
            return format(d.normalize(), "f")

        hint = (
            f"{commodity}: {_fmt(total_units)} units · "
            f"avg {currency}{avg_cost:.2f}/unit · "
            f"cost basis for {_fmt(abs_qty)} units ≈ {currency}{cost_basis:.2f}"
        )

        if qty < 0 and proceeds is not None:
            gain = proceeds - cost_basis
            sign = "+" if gain >= 0 else ""
            hint += f" · gain ≈ {sign}{currency}{gain:.2f}"

        return hint

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update cost basis hint when an amount field changes.

        Args:
            event: The Input.Changed event from any input in the form.
        """
        if not event.input.id or not event.input.id.startswith("amount-"):
            return
        hint_widget = self.query_one("#cost-basis-hint", Static)
        parsed = _extract_commodity_and_qty(event.value)
        if parsed:
            qty, commodity, proceeds = parsed
            hint = self._build_cost_hint(commodity, qty, proceeds)
            if hint:
                hint_widget.update(hint)
                hint_widget.add_class("visible")
                return
        hint_widget.update("")
        hint_widget.remove_class("visible")

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

    @staticmethod
    def _reuse_initial_amounts(row: PostingRow) -> list[Amount] | None:
        """Return the original amounts if *row*'s input is semantically unchanged.

        Preserves the original :class:`AmountStyle` (decimal mark, digit
        grouping, commodity side) when editing a transaction without modifying
        the amount field.  This avoids round-tripping through
        :func:`parse_amount_str`, which would otherwise reset the style to a
        US-formatted default and — in journals declaring European formatting
        via a ``commodity`` directive — cause hledger to re-interpret the
        rewritten amount, scaling it by 100× (issue #111).

        The comparison is tolerant of the :class:`AmountInput` blur
        auto-format, which normalises simple decimals to 2 decimal places
        (e.g. ``"10"`` → ``"10.00"``) without changing the semantic value.

        Args:
            row: The posting row whose current input should be compared
                against the values it was initialised with.

        Returns:
            The original amounts list when the input is unchanged, otherwise
            ``None`` to signal that the caller should re-parse the input.
        """
        if row.initial_amounts is None:
            return None

        if row.amount == row.initial_amount.strip():
            return row.initial_amounts

        # Tolerate blur auto-format for plain single-amount postings.
        if len(row.initial_amounts) == 1 and row.initial_amounts[0].cost is None:
            try:
                if Decimal(row.amount) == row.initial_amounts[0].quantity:
                    return row.initial_amounts
            except InvalidOperation:
                pass

        return None

    @staticmethod
    def _omit_balancing_amount(postings: list[Posting]) -> list[Posting]:
        """Clear the last posting's amounts when hledger can infer the balance.

        Only acts when every posting has exactly one amount, all amounts share the
        same commodity, and the amounts sum to zero.

        Args:
            postings: The list of postings to process.

        Returns:
            The (potentially modified) list of postings.
        """
        if len(postings) < 2:
            return postings
        # Every posting must have exactly one amount.
        if not all(len(p.amounts) == 1 for p in postings):
            return postings
        # All commodities must be the same.
        commodities = {p.amounts[0].commodity for p in postings}
        if len(commodities) != 1:
            return postings
        # Amounts must sum to zero.
        total = sum(p.amounts[0].quantity for p in postings)
        if total != 0:
            return postings
        postings[-1].amounts = []
        return postings

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
                # When the amount input is unchanged from the value the form
                # was initialised with, reuse the original Amount objects so
                # their AmountStyle (decimal mark, digit grouping, commodity
                # side) is preserved.  Re-parsing the displayed string would
                # fall back to a default US-style AmountStyle, which — on a
                # journal that declares European formatting via a commodity
                # directive — causes hledger to re-interpret the written
                # amount and scale it by 100× (issue #111).
                reused = self._reuse_initial_amounts(row)
                if reused is not None:
                    amounts.extend(reused)
                else:
                    default_commodity = row.commodity or load_default_commodity()
                    amount = parse_amount_str(row.amount, default_commodity)
                    if amount is None:
                        self.notify(
                            f"Invalid amount: \"{row.amount}\". "
                            "Use: 50.00 | €50.00 | -5 STCK @@ €200.00 | -5 STCK @ €40.00",
                            severity="error",
                            timeout=6,
                        )
                        return
                    amounts.append(amount)

            postings.append(Posting(account=account, amounts=amounts))

        postings = self._omit_balancing_amount(postings)

        # Pre-save balance check: only for simple single-commodity transactions
        # where every posting has exactly one plain amount (no cost annotation).
        # Cross-commodity and cost-annotation cases are delegated to hledger.
        all_plain = all(
            len(p.amounts) == 1 and p.amounts[0].cost is None
            for p in postings
        )
        if all_plain:
            commodities = {p.amounts[0].commodity for p in postings}
            if len(commodities) == 1:
                total = sum(p.amounts[0].quantity for p in postings)
                if total != 0:
                    commodity_sym = next(iter(commodities))
                    self.notify(
                        f"Transaction is unbalanced (sum: {total:+g} {commodity_sym}). "
                        "Negate one amount or leave one blank to auto-balance.",
                        severity="error",
                        timeout=6,
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
