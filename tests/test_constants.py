"""Tests for the centralized option/label constants."""

from __future__ import annotations

from hledger_textual.models import TransactionStatus
from hledger_textual.recurring import SUPPORTED_PERIODS
from hledger_textual.widgets.constants import (
    BUDGET_OVERVIEW_PERIOD_OPTIONS,
    CUSTOM_REPORT_EXAMPLES,
    FIELD_OPTIONS,
    HEADER_OPTIONS,
    KEY_LABELS,
    RECURRING_PERIOD_OPTIONS,
    REPORT_LABELS,
    REPORT_PERIOD_LABELS,
    REPORT_PERIOD_RANGES,
    REPORT_TYPES,
    SEPARATOR_OPTIONS,
    TRANSACTION_STATUS_OPTIONS,
)

OPTION_LISTS = [
    TRANSACTION_STATUS_OPTIONS,
    RECURRING_PERIOD_OPTIONS,
    REPORT_TYPES,
    REPORT_PERIOD_RANGES,
    BUDGET_OVERVIEW_PERIOD_OPTIONS,
    SEPARATOR_OPTIONS,
    HEADER_OPTIONS,
    FIELD_OPTIONS,
    CUSTOM_REPORT_EXAMPLES,
]


def test_option_lists_have_unique_values_and_non_empty_labels():
    """Every option list has unique values and a label for each entry."""
    for options in OPTION_LISTS:
        labels = [label for label, _ in options]
        values = [value for _, value in options]
        assert all(labels), options
        assert len(values) == len(set(values)), options


def test_report_labels_cover_report_types():
    """Report labels are derived from the report types, with no drift."""
    assert REPORT_LABELS == {value: label for label, value in REPORT_TYPES}


def test_report_period_labels_cover_period_ranges():
    """Period labels cover exactly the selectable period ranges."""
    assert REPORT_PERIOD_LABELS == {months: label for label, months in REPORT_PERIOD_RANGES}
    assert BUDGET_OVERVIEW_PERIOD_OPTIONS == REPORT_PERIOD_RANGES[:3]


def test_recurring_period_options_extend_supported_periods():
    """Recurring options mirror SUPPORTED_PERIODS plus the custom entry."""
    expected = [(p.capitalize(), p) for p in SUPPORTED_PERIODS] + [("Custom", "custom")]
    assert RECURRING_PERIOD_OPTIONS == expected


def test_transaction_status_options_cover_all_statuses():
    """Status options cover every TransactionStatus member exactly once."""
    assert {value for _, value in TRANSACTION_STATUS_OPTIONS} == set(TransactionStatus)


def test_field_options_start_with_skip():
    """The first CSV field option is the empty (skip) mapping."""
    assert FIELD_OPTIONS[0] == ("(skip)", "")


def test_key_labels_cover_common_keys():
    """Key labels include the keys rendered by the help screen."""
    for key in ("slash", "enter", "escape", "space"):
        assert KEY_LABELS[key]
