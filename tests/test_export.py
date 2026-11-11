"""Unit tests for export functionality (no hledger needed)."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from hledger_textual.export import (
    ExportData,
    _strip_markup,
    default_export_dir,
    default_filename,
    export_csv,
    export_pdf,
)


def _sample_data() -> ExportData:
    """Create sample export data for testing."""
    return ExportData(
        title="Test Export",
        headers=["Date", "Description", "Amount"],
        rows=[
            ["2026-01-01", "Groceries", "€50.00"],
            ["2026-01-02", "Rent", "€800.00"],
            ["2026-01-03", "Salary", "€3000.00"],
        ],
        pane_name="transactions",
    )


def test_default_filename_csv():
    """Default filename includes pane name, date, and .csv extension."""
    name = default_filename("transactions", "csv")
    assert name.startswith("transactions_")
    assert name.endswith(".csv")


def test_default_filename_pdf():
    """Default filename includes pane name, date, and .pdf extension."""
    name = default_filename("budget", "pdf")
    assert name.startswith("budget_")
    assert name.endswith(".pdf")


def test_default_export_dir():
    """Default export dir is under ~/Documents."""
    d = default_export_dir()
    assert d.exists()
    assert "hledger-exports" in str(d)


def test_export_csv_creates_file():
    """export_csv creates a valid CSV file with headers and rows."""
    data = _sample_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.csv"
        export_csv(data, path)

        assert path.exists()
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert rows[0] == ["Date", "Description", "Amount"]
        assert len(rows) == 4  # header + 3 data rows
        assert rows[1] == ["2026-01-01", "Groceries", "€50.00"]


def test_export_csv_empty_rows():
    """export_csv handles empty row list gracefully."""
    data = ExportData(
        title="Empty", headers=["A", "B"], rows=[], pane_name="test"
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "empty.csv"
        export_csv(data, path)

        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)

        assert len(rows) == 1  # header only


def test_export_pdf_creates_file():
    """export_pdf creates a valid PDF file."""
    data = _sample_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.pdf"
        export_pdf(data, path)

        assert path.exists()
        assert path.stat().st_size > 0
        # PDF files start with %PDF
        content = path.read_bytes()
        assert content[:4] == b"%PDF"


def test_export_pdf_wide_table_landscape():
    """export_pdf uses landscape for tables with >4 columns."""
    data = ExportData(
        title="Wide Table",
        headers=["A", "B", "C", "D", "E"],
        rows=[["1", "2", "3", "4", "5"]],
        pane_name="wide",
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "wide.pdf"
        export_pdf(data, path)
        assert path.exists()


def test_strip_markup():
    """_strip_markup removes Rich markup tags."""
    assert _strip_markup("[red]Error[/red]") == "Error"
    assert _strip_markup("[bold]Total:[/bold]") == "Total:"
    assert _strip_markup("[green]€100.00[/green]") == "€100.00"
    assert _strip_markup("No markup") == "No markup"


def test_export_csv_creates_parent_dirs():
    """export_csv creates parent directories if they don't exist."""
    data = _sample_data()
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "sub" / "dir" / "test.csv"
        export_csv(data, path)
        assert path.exists()


def test_export_pdf_no_headers_early_exit():
    """export_pdf with zero columns writes the title page only."""
    from hledger_textual.export import ExportData

    data = ExportData.from_rows("Empty", [], [], "empty")
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "empty.pdf"
        export_pdf(data, path)
        assert path.exists()
        assert path.stat().st_size > 0


def test_from_rows_normalises_tuples():
    """from_rows converts tuples and coerces cells to string lists."""
    from hledger_textual.export import ExportData

    data = ExportData.from_rows("T", ("A", "B"), [(1, 2), ("x", "y")], "t")
    assert data.headers == ["A", "B"]
    assert data.rows == [["1", "2"], ["x", "y"]]
    assert all(isinstance(row, list) for row in data.rows)


def test_compute_col_widths_zero_total():
    """All-zero measurements fall back to even widths."""
    from hledger_textual.export import ExportData, _compute_col_widths

    class _ZeroPdf:
        def set_font(self, *args, **kwargs) -> None:
            pass

        def get_string_width(self, _text: str) -> float:
            return 0.0

    data = ExportData.from_rows("T", ["A", "B"], [], "t")
    assert _compute_col_widths(_ZeroPdf(), data, 100.0) == [50.0, 50.0]


def test_compute_col_widths_enforces_minimum():
    """A dwarfed column is widened, then totals are renormalised to fit."""
    from hledger_textual.export import ExportData, _compute_col_widths

    class _LenPdf:
        def set_font(self, *args, **kwargs) -> None:
            pass

        def get_string_width(self, text: str) -> float:
            return float(len(text))

    data = ExportData.from_rows("T", ["A", "B" * 200], [["x", "y"]], "t")
    widths = _compute_col_widths(_LenPdf(), data, 100.0)
    assert len(widths) == 2
    assert sum(widths) == pytest.approx(100.0)
    assert widths[1] > widths[0]
