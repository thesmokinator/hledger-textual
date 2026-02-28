"""Chart widget for the Reports pane using textual-plotext."""

from __future__ import annotations

from textual_plotext import PlotextPlot

from hledger_textual.hledger import _parse_budget_amount
from hledger_textual.models import ReportData


def parse_report_amount(s: str) -> float:
    """Parse a report amount string like ``-€40.80`` into a float.

    Handles the sign-before-commodity format produced by hledger IS/BS/CF
    CSV output.  Delegates to :func:`_parse_budget_amount` for the core
    parsing after stripping any leading minus sign.

    Args:
        s: The amount string from hledger CSV output.

    Returns:
        The parsed amount as a float.  Returns ``0.0`` for empty or
        unparseable values.
    """
    s = s.strip()
    if not s:
        return 0.0

    negate = False
    if s.startswith("-"):
        negate = True
        s = s[1:]

    qty, _ = _parse_budget_amount(s)
    result = float(qty)
    return -result if negate else result


def extract_chart_data(data: ReportData, report_type: str) -> dict:
    """Extract numeric chart data from a :class:`ReportData`.

    Args:
        data: The parsed report data.
        report_type: One of ``"is"``, ``"bs"``, or ``"cf"``.

    Returns:
        A dict with chart-specific keys:

        - **IS**: ``labels``, ``income``, ``expenses``, ``net``
        - **BS**: ``labels``, ``totals``
        - **CF**: ``labels``, ``net``

        Returns an empty dict if the data is insufficient.
    """
    if not data or not data.period_headers or not data.rows:
        return {}

    labels = list(data.period_headers)
    n_periods = len(labels)

    if report_type == "is":
        income = [0.0] * n_periods
        expenses = [0.0] * n_periods
        net = [0.0] * n_periods

        current_section = ""
        for row in data.rows:
            if row.is_section_header:
                current_section = row.account.lower()
                continue

            if row.is_total and row.account.lower().startswith("net:"):
                for i, amt in enumerate(row.amounts[:n_periods]):
                    net[i] = parse_report_amount(amt)
                continue

            # Skip other totals
            if row.is_total:
                continue

            # Accumulate into the right section
            for i, amt in enumerate(row.amounts[:n_periods]):
                val = parse_report_amount(amt)
                if "revenue" in current_section or "income" in current_section:
                    income[i] += val
                elif "expense" in current_section:
                    expenses[i] += val

        return {"labels": labels, "income": income, "expenses": expenses, "net": net}

    if report_type == "bs":
        totals = [0.0] * n_periods
        for row in data.rows:
            if row.is_total and row.account.lower().startswith("total:"):
                for i, amt in enumerate(row.amounts[:n_periods]):
                    totals[i] = parse_report_amount(amt)
                break
        return {"labels": labels, "totals": totals}

    if report_type == "cf":
        net = [0.0] * n_periods
        for row in data.rows:
            label = row.account.lower()
            if row.is_total and (
                label.startswith("net:") or label.startswith("total:")
            ):
                for i, amt in enumerate(row.amounts[:n_periods]):
                    net[i] = parse_report_amount(amt)
                break
        return {"labels": labels, "net": net}

    return {}


class ReportChart(PlotextPlot):
    """Chart widget that renders bar charts for financial reports."""

    def replot(self, chart_data: dict, report_type: str) -> None:
        """Clear and redraw the chart with new data.

        Args:
            chart_data: Data dict from :func:`extract_chart_data`.
            report_type: One of ``"is"``, ``"bs"``, or ``"cf"``.
        """
        plt = self.plt
        plt.clear_figure()
        plt.theme("clear")

        if not chart_data or "labels" not in chart_data:
            return

        labels = chart_data["labels"]

        if report_type == "is":
            income = chart_data.get("income", [])
            expenses = chart_data.get("expenses", [])
            plt.multiple_bar(
                labels,
                [income, expenses],
                labels=["Income", "Expenses"],
                color=["green", "red"],
            )
            plt.title("Income vs Expenses")

        elif report_type == "bs":
            totals = chart_data.get("totals", [])
            plt.bar(labels, totals, color="blue")
            plt.title("Total Balance")

        elif report_type == "cf":
            net = chart_data.get("net", [])
            colors = ["green" if v >= 0 else "red" for v in net]
            plt.bar(labels, net, color=colors)
            plt.title("Net Cash Flow")

        self.refresh()
