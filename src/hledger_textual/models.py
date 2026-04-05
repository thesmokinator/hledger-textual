"""Data models for hledger transactions, postings, and amounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path


class TransactionStatus(Enum):
    """Transaction clearing status."""

    UNMARKED = "Unmarked"
    PENDING = "Pending"
    CLEARED = "Cleared"

    @property
    def symbol(self) -> str:
        """Return the journal symbol for this status."""
        match self:
            case TransactionStatus.CLEARED:
                return "*"
            case TransactionStatus.PENDING:
                return "!"
            case TransactionStatus.UNMARKED:
                return ""


@dataclass
class SourcePosition:
    """A position in a source file."""

    source_name: str
    source_line: int
    source_column: int


@dataclass
class AmountStyle:
    """Formatting style for an amount."""

    commodity_side: str = "L"
    commodity_spaced: bool = False
    decimal_mark: str = "."
    digit_group_separator: str | None = None
    digit_group_sizes: list[int] = field(default_factory=list)
    precision: int = 2


@dataclass
class Amount:
    """A monetary amount with commodity and style.

    The optional ``cost`` field holds the cost annotation (``@`` or ``@@``)
    already converted to a total cost, so that callers do not need to
    distinguish between per-unit and total cost.
    """

    commodity: str
    quantity: Decimal
    style: AmountStyle = field(default_factory=AmountStyle)
    cost: Amount | None = None

    def format(self) -> str:
        """Format the amount as a string for display."""
        qty_str = f"{abs(self.quantity):.{self.style.precision}f}"
        sign = "-" if self.quantity < 0 else ""

        if self.style.commodity_side == "L":
            space = " " if self.style.commodity_spaced else ""
            base = f"{sign}{self.commodity}{space}{qty_str}"
        else:
            space = " " if self.style.commodity_spaced else ""
            base = f"{sign}{qty_str}{space}{self.commodity}"

        if self.cost is not None:
            # Cost annotations are always written as positive values in hledger.
            cost_display = Amount(
                commodity=self.cost.commodity,
                quantity=abs(self.cost.quantity),
                style=self.cost.style,
            )
            base += f" @@ {cost_display.format()}"

        return base


@dataclass
class Posting:
    """A single posting within a transaction."""

    account: str
    amounts: list[Amount] = field(default_factory=list)
    comment: str = ""
    status: TransactionStatus = TransactionStatus.UNMARKED


@dataclass
class Transaction:
    """A complete journal transaction."""

    index: int
    date: str
    description: str
    postings: list[Posting] = field(default_factory=list)
    status: TransactionStatus = TransactionStatus.UNMARKED
    code: str = ""
    comment: str = ""
    date2: str | None = None
    source_pos: tuple[SourcePosition, SourcePosition] | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def type_indicator(self) -> str:
        """Return 'I' for income, 'E' for expense, '-' for mixed/transfer."""
        has_income = False
        has_expense = False
        for posting in self.postings:
            top = posting.account.split(":")[0].lower()
            if top in ("income", "revenues", "revenue"):
                has_income = True
            elif top in ("expenses", "expense"):
                has_expense = True
        if has_income and not has_expense:
            return "I"
        if has_expense and not has_income:
            return "E"
        return "-"

    @property
    def total_amount(self) -> str:
        """Return the sum of positive amounts for display.

        When a posting carries a cost annotation (e.g. ``10 XDWD @@ €1185``),
        the cost is included in the totals so that the display shows the EUR
        value invested rather than unrelated small amounts like bank fees.
        """
        positive_amounts: dict[str, Decimal] = {}
        styles: dict[str, AmountStyle] = {}
        for posting in self.postings:
            for amount in posting.amounts:
                if amount.quantity > 0:
                    key = amount.commodity
                    positive_amounts[key] = positive_amounts.get(key, Decimal(0)) + amount.quantity
                    if key not in styles:
                        styles[key] = amount.style
                    if amount.cost is not None:
                        ck = amount.cost.commodity
                        positive_amounts[ck] = positive_amounts.get(ck, Decimal(0)) + abs(amount.cost.quantity)
                        if ck not in styles:
                            styles[ck] = amount.cost.style
        if not positive_amounts:
            return ""
        parts = []
        for commodity, qty in positive_amounts.items():
            style = styles.get(commodity, AmountStyle())
            # Cap currency amounts (left-side symbol, e.g. €) to 2 decimal
            # places for display. Named commodities (XEON, BTC on the right)
            # keep their natural precision.
            if style.commodity_side == "L" and style.precision > 2:
                style = AmountStyle(
                    commodity_side=style.commodity_side,
                    commodity_spaced=style.commodity_spaced,
                    decimal_mark=style.decimal_mark,
                    digit_group_separator=style.digit_group_separator,
                    digit_group_sizes=style.digit_group_sizes,
                    precision=2,
                )
            amt = Amount(commodity=commodity, quantity=qty, style=style)
            parts.append(amt.format())
        return ", ".join(parts)

    def _find_style(self, commodity: str) -> AmountStyle:
        """Find the AmountStyle used for a given commodity in this transaction."""
        for posting in self.postings:
            for amount in posting.amounts:
                if amount.commodity == commodity:
                    return amount.style
        return AmountStyle()


@dataclass
class JournalStats:
    """Journal statistics from hledger stats."""

    transaction_count: int
    account_count: int
    commodities: list[str] = field(default_factory=list)


@dataclass
class PeriodSummary:
    """Financial summary for a single period (e.g. one month).

    The net value represents disposable income: income minus expenses minus
    new investment purchases, i.e. what actually stays in the bank account.
    """

    income: Decimal
    expenses: Decimal
    commodity: str
    investments: Decimal = Decimal("0")

    @property
    def net(self) -> Decimal:
        """Return net disposable income (income minus expenses minus investments)."""
        return self.income - self.expenses - self.investments


@dataclass
class BudgetRule:
    """A single budget rule mapping an account to a monthly amount."""

    account: str
    amount: Amount
    category: str = ""


@dataclass
class BudgetRow:
    """A row in the budget report comparing actual vs budgeted spending."""

    account: str
    actual: Decimal
    budget: Decimal
    commodity: str

    @property
    def remaining(self) -> Decimal:
        """Return the remaining budget (budget - actual)."""
        return self.budget - self.actual

    @property
    def usage_pct(self) -> float:
        """Return the usage percentage (actual / budget * 100)."""
        if self.budget == 0:
            return 0.0
        return float(self.actual / self.budget * 100)


@dataclass
class ReportRow:
    """A single row in a multi-period financial report.

    Represents an account line, a section header (e.g. "Revenues"),
    or a total/net row.
    """

    account: str
    amounts: list[str] = field(default_factory=list)
    is_section_header: bool = False
    is_total: bool = False
    depth: int = 0


@dataclass
class RecurringRule:
    """A single recurring transaction rule stored in recurring.journal."""

    rule_id: str
    period_expr: str
    description: str
    postings: list[Posting] = field(default_factory=list)
    status: TransactionStatus = TransactionStatus.UNMARKED
    start_date: str | None = None
    end_date: str | None = None
    comment: str = ""
    code: str = ""


@dataclass
class AccountNode:
    """A node in the account hierarchy tree.

    Each node represents an account at a certain depth, with optional
    children and an expand/collapse state for tree rendering.
    """

    name: str
    full_path: str
    balance: str
    depth: int
    children: list[AccountNode] = field(default_factory=list)
    expanded: bool = True


@dataclass
class AccountDirective:
    """An hledger account directive with optional metadata.

    Represents a line like::

        account expenses:groceries  ; note:Weekly shopping, category:food
    """

    name: str
    comment: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class CsvRulesFile:
    """Metadata for an hledger CSV rules file used by the import wizard.

    Each instance corresponds to a ``.rules`` file on disk. The structured
    fields are extracted from the rules syntax so that the wizard UI can
    display and edit them without requiring the user to hand-edit text.
    """

    name: str
    path: Path
    account1: str
    separator: str
    date_format: str
    skip: int
    field_mapping: list[str]
    currency: str
    conditional_rules: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class CustomReport:
    """A user-defined custom hledger report.

    The ``command`` field holds the hledger argument string without the
    ``-f`` journal flag (e.g. ``"balance expenses --tree -M"``).
    """

    name: str
    command: str


@dataclass
class ReportData:
    """Parsed output of a multi-period hledger report (IS, BS, CF).

    Contains the report title, period column headers, and all data rows.
    """

    title: str
    period_headers: list[str] = field(default_factory=list)
    rows: list[ReportRow] = field(default_factory=list)
