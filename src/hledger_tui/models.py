"""Data models for hledger transactions, postings, and amounts."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum


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
            return f"{sign}{self.commodity}{space}{qty_str}"
        else:
            space = " " if self.style.commodity_spaced else ""
            return f"{sign}{qty_str}{space}{self.commodity}"


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
