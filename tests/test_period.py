"""Tests for the shared period selection module (issue #263)."""

from datetime import date

import pytest

from hledger_textual.period import (
    PeriodSelection,
    all_selection,
    current_month_selection,
    month_range_selection,
    month_selection,
    parse_period,
    period_from_flags,
    range_selection,
    shift_months,
    shift_years,
    year_range,
    year_selection,
)


class TestMonthSelection:
    """month_selection builds a single calendar month."""

    def test_day_is_ignored(self):
        selection = month_selection(date(2024, 3, 17))
        assert selection.kind == "month"
        assert selection.begin == date(2024, 3, 1)
        assert selection.end == date(2024, 4, 1)  # exclusive

    def test_label_is_month_name(self):
        assert month_selection(date(2024, 3, 1)).label == "March 2024"

    def test_query_uses_month_granularity(self):
        assert month_selection(date(2024, 3, 1)).query() == "date:2024-03"

    def test_hledger_args(self):
        assert month_selection(date(2024, 3, 1)).hledger_args() == ("-p", "2024-03")


class TestRangeSelection:
    """range_selection stores an exclusive end bound."""

    def test_inclusive_end_becomes_exclusive(self):
        selection = range_selection(date(2024, 3, 5), date(2024, 4, 2))
        assert selection.kind == "range"
        assert selection.begin == date(2024, 3, 5)
        assert selection.end == date(2024, 4, 3)

    def test_query_uses_day_granularity(self):
        selection = range_selection(date(2024, 3, 5), date(2024, 4, 2))
        assert selection.query() == "date:2024-03-05..2024-04-02"

    def test_full_month_range_normalises_to_month_selection(self):
        selection = range_selection(date(2024, 1, 1), date(2024, 1, 31))
        assert selection.kind == "month"
        assert selection.query() == "date:2024-01"

    def test_swapped_bounds_are_ordered(self):
        selection = range_selection(date(2024, 4, 2), date(2024, 3, 5))
        assert selection.begin == date(2024, 3, 5)
        assert selection.end == date(2024, 4, 3)


class TestMonthRangeSelection:
    """month_range_selection covers whole calendar months."""

    def test_span_query(self):
        selection = month_range_selection(date(2024, 1, 15), date(2024, 6, 2))
        assert selection.query() == "date:2024-01..2024-06"
        assert selection.contains(date(2024, 6, 30))
        assert not selection.contains(date(2024, 7, 1))

    def test_label(self):
        selection = month_range_selection(date(2024, 1, 1), date(2024, 6, 1))
        assert selection.label == "Jan 2024 → Jun 2024"

    def test_swapped_months_are_ordered(self):
        selection = month_range_selection(date(2024, 6, 1), date(2024, 1, 1))
        assert selection.begin == date(2024, 1, 1)
        assert selection.end == date(2024, 7, 1)


class TestYearSelection:
    """year_selection covers a whole calendar year."""

    def test_bounds(self):
        selection = year_selection(2024)
        assert selection.begin == date(2024, 1, 1)
        assert selection.end == date(2025, 1, 1)

    def test_query_uses_year_granularity(self):
        # A Jan-to-Dec month span formats as a compact year expression.
        assert year_selection(2024).query() == "date:2024"

    def test_year_range(self):
        selection = year_range(2023, 2025)
        assert selection.query() == "date:2023..2025"
        assert selection.label == "2023 → 2025"


class TestAllSelection:
    """all_selection is unbounded."""

    def test_empty_query_and_args(self):
        selection = all_selection()
        assert selection.kind == "all"
        assert selection.query() == ""
        assert selection.hledger_args() == ()
        assert selection.label == "All time"

    def test_contains_everything(self):
        assert all_selection().contains(date(1999, 1, 1))


class TestContains:
    """contains honours the exclusive end."""

    def test_month_boundaries(self):
        selection = month_selection(date(2024, 3, 1))
        assert selection.contains(date(2024, 3, 1))
        assert selection.contains(date(2024, 3, 31))
        assert not selection.contains(date(2024, 4, 1))

    def test_range_boundaries(self):
        selection = range_selection(date(2024, 3, 5), date(2024, 4, 2))
        assert selection.contains(date(2024, 3, 5))
        assert selection.contains(date(2024, 4, 2))
        assert not selection.contains(date(2024, 4, 3))

    def test_overlaps_months(self):
        selection = month_range_selection(date(2024, 3, 1), date(2024, 6, 1))
        assert selection.overlaps_months(date(2024, 3, 20))
        assert selection.overlaps_months(date(2024, 6, 1))
        assert not selection.overlaps_months(date(2024, 7, 1))
        assert not selection.overlaps_months(date(2024, 2, 28))


class TestOverlapsSpan:
    """overlaps_span rejects selections outside the journal's data."""

    def test_inside_span(self):
        selection = month_selection(date(2024, 3, 1))
        assert selection.overlaps_span(date(2024, 1, 1), date(2024, 6, 30))

    def test_before_span(self):
        assert not month_selection(date(2023, 1, 1)).overlaps_span(
            date(2024, 1, 1), date(2024, 6, 30)
        )

    def test_after_span(self):
        assert not month_selection(date(2025, 1, 1)).overlaps_span(
            date(2024, 1, 1), date(2024, 6, 30)
        )

    def test_partially_overlapping(self):
        selection = month_range_selection(date(2024, 5, 1), date(2024, 8, 1))
        assert selection.overlaps_span(date(2024, 1, 1), date(2024, 6, 30))

    def test_all_selection(self):
        assert all_selection().overlaps_span(date(2024, 1, 1), date(2024, 6, 30))

    def test_unknown_span_never_rejects(self):
        assert month_selection(date(2020, 1, 1)).overlaps_span(None, None)


class TestShiftMonths:
    """shift_months moves month-aligned selections by whole months."""

    def test_month_forward(self):
        selection = shift_months(month_selection(date(2024, 3, 1)), 1)
        assert selection.begin == date(2024, 4, 1)

    def test_month_across_year_boundary(self):
        selection = shift_months(month_selection(date(2024, 12, 1)), 1)
        assert selection.begin == date(2025, 1, 1)
        assert selection.label == "January 2025"

    def test_month_backward_across_year_boundary(self):
        selection = shift_months(month_selection(date(2024, 1, 1)), -1)
        assert selection.begin == date(2023, 12, 1)

    def test_range_keeps_length(self):
        selection = range_selection(date(2024, 3, 5), date(2024, 4, 2))
        shifted = shift_months(selection, -2)
        assert shifted.begin == date(2024, 1, 5)
        assert shifted.end == date(2024, 2, 3)
        assert (shifted.end - shifted.begin).days == (selection.end - selection.begin).days

    def test_all_is_unchanged(self):
        assert shift_months(all_selection(), 3) == all_selection()

    def test_year_shift_is_twelve_months(self):
        selection = shift_years(month_selection(date(2024, 3, 1)), 2)
        assert selection.begin == date(2026, 3, 1)
        selection = shift_years(month_selection(date(2024, 3, 1)), -1)
        assert selection.begin == date(2023, 3, 1)


class TestCurrentMonthSelection:
    """current_month_selection defaults to today."""

    def test_uses_today(self):
        today = date.today()
        selection = current_month_selection()
        assert selection.begin == today.replace(day=1)

    def test_explicit_today(self):
        selection = current_month_selection(date(2024, 8, 9))
        assert selection.label == "August 2024"


class TestParsePeriod:
    """parse_period accepts hledger-style period expressions."""

    def test_year(self):
        selection = parse_period("2024")
        assert selection is not None
        assert selection.query() == "date:2024"
        assert selection.contains(date(2024, 12, 31))
        assert not selection.contains(date(2025, 1, 1))

    def test_month(self):
        selection = parse_period("2024-03")
        assert selection is not None
        assert selection.query() == "date:2024-03"

    def test_month_single_digit(self):
        assert parse_period("2024-3").query() == "date:2024-03"

    def test_month_span(self):
        selection = parse_period("2024-01..2024-06")
        assert selection is not None
        assert selection.query() == "date:2024-01..2024-06"
        assert selection.contains(date(2024, 6, 30))
        assert not selection.contains(date(2024, 7, 1))

    def test_year_span(self):
        selection = parse_period("2023..2025")
        assert selection is not None
        assert selection.query() == "date:2023..2025"
        assert selection.contains(date(2025, 12, 31))
        assert not selection.contains(date(2026, 1, 1))

    def test_day_range(self):
        selection = parse_period("2024-03-05..2024-04-02")
        assert selection is not None
        assert selection.begin == date(2024, 3, 5)
        assert selection.end == date(2024, 4, 3)

    def test_swapped_span_bounds_are_ordered(self):
        selection = parse_period("2024-06..2024-01")
        assert selection is not None
        assert selection.begin == date(2024, 1, 1)

    def test_single_date(self):
        selection = parse_period("2024-03-05")
        assert selection is not None
        assert selection.contains(date(2024, 3, 5))
        assert not selection.contains(date(2024, 3, 6))

    def test_relative_aliases(self):
        today = date(2024, 8, 15)
        assert parse_period("this month", today).query() == "date:2024-08"
        assert parse_period("last month", today).query() == "date:2024-07"
        assert parse_period("next month", today).query() == "date:2024-09"
        assert parse_period("this year", today).query() == "date:2024"
        assert parse_period("last year", today).query() == "date:2023"
        assert parse_period("next year", today).query() == "date:2025"

    def test_ytd(self):
        today = date(2024, 8, 15)
        selection = parse_period("ytd", today)
        assert selection is not None
        assert selection.begin == date(2024, 1, 1)
        assert selection.end == date(2024, 8, 16)

    def test_all(self):
        assert parse_period("all") == all_selection()

    def test_invalid(self):
        assert parse_period("") is None
        assert parse_period("   ") is None
        assert parse_period("not a period") is None
        assert parse_period("2024-13") is None
        assert parse_period("2024-02-30") is None
        assert parse_period("2024..banana") is None

    def test_month_name(self):
        assert parse_period("march", date(2024, 8, 1)).query() == "date:2024-03"
        assert parse_period("mar 2023", date(2024, 8, 1)).query() == "date:2023-03"

    def test_whitespace_is_tolerated(self):
        assert parse_period("  2024-03  ") is not None
        assert parse_period("2024-01 .. 2024-06") is not None

    def test_period_expr_month(self):
        assert month_selection(date(2024, 3, 1)).period_expr == "2024-03"

    def test_selection_is_frozen(self):
        selection = month_selection(date(2024, 3, 1))
        with pytest.raises(AttributeError):
            selection.begin = date(2025, 1, 1)


class TestFormatBound:
    """Bounds use the coarsest unambiguous granularity."""

    def test_first_of_month_is_month_form(self):
        assert PeriodSelection._format_bound(date(2024, 3, 1)) == "2024-03"

    def test_other_days_keep_full_form(self):
        assert PeriodSelection._format_bound(date(2024, 3, 17)) == "2024-03-17"


class TestPeriodFromFlags:
    """period_from_flags builds the startup period from -p/-b/-e (issue #268)."""

    def test_period_only(self):
        selection = period_from_flags("2024-03", None, None)
        assert selection.query() == "date:2024-03"

    def test_period_relative(self):
        selection = period_from_flags("last month", None, None)
        assert selection == parse_period("last month")

    def test_begin_and_end_dates(self):
        selection = period_from_flags(None, "2024-01-01", "2024-06-30")
        assert selection.begin == date(2024, 1, 1)
        # --end is exclusive, like hledger: June 30 itself is excluded.
        assert selection.end == date(2024, 6, 30)
        assert selection.query() == "date:2024-01-01..2024-06-29"

    def test_bounds_override_period(self):
        selection = period_from_flags("2024-03", "2024-01-01", "2024-06-30")
        assert selection.begin == date(2024, 1, 1)

    def test_begin_only(self):
        selection = period_from_flags(None, "2024-03-05", None)
        assert selection.begin == date(2024, 3, 5)
        assert selection.end is None
        assert selection.query() == "date:2024-03-05.."

    def test_end_only(self):
        selection = period_from_flags(None, None, "2024-06-30")
        assert selection.begin is None
        # --end is exclusive: June 30 itself is excluded.
        assert selection.end == date(2024, 6, 30)
        assert selection.query() == "date:..2024-06-29"

    def test_month_bound_end(self):
        selection = period_from_flags(None, None, "2024-04")
        # Like hledger -e, a month bound is exclusive at its first day:
        # the period runs through March 2024.
        assert selection.query() == "date:..2024-03"

    def test_year_month_bounds_label(self):
        selection = period_from_flags(None, "2024-01-01", "2024-04-01")
        assert selection.label == "Jan 2024 → Mar 2024"

    def test_swapped_bounds_are_ordered(self):
        selection = period_from_flags(None, "2024-06-30", "2024-01-01")
        assert selection.begin == date(2024, 1, 1)

    def test_invalid_period_raises(self):
        with pytest.raises(ValueError):
            period_from_flags("banana", None, None)

    def test_invalid_begin_raises(self):
        with pytest.raises(ValueError):
            period_from_flags(None, "banana", None)

    def test_invalid_end_raises(self):
        with pytest.raises(ValueError):
            period_from_flags(None, None, "2024-02-30")

    def test_no_flags_raises(self):
        with pytest.raises(ValueError):
            period_from_flags(None, None, None)
