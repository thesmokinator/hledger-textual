"""Tests for period presets and saved-view helpers (issue #277)."""

from __future__ import annotations

from datetime import date

import pytest

from hledger_textual.period import parse_period


class TestGetPreset:
    """Each preset resolves through the shared PeriodSelection state."""

    def test_this_month(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("this-month", date(2024, 6, 15))
        assert sel.kind == "month"
        assert (sel.begin, sel.end) == (date(2024, 6, 1), date(2024, 7, 1))

    def test_last_month(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-month", date(2024, 6, 15))
        assert sel.kind == "month"
        assert (sel.begin, sel.end) == (date(2024, 5, 1), date(2024, 6, 1))

    def test_last_month_across_year_boundary(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-month", date(2024, 1, 10))
        assert (sel.begin, sel.end) == (date(2023, 12, 1), date(2024, 1, 1))

    def test_this_year(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("this-year", date(2024, 6, 15))
        assert (sel.begin, sel.end) == (date(2024, 1, 1), date(2025, 1, 1))
        assert sel.period_expr == "2024"

    def test_last_year(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-year", date(2024, 6, 15))
        assert (sel.begin, sel.end) == (date(2023, 1, 1), date(2024, 1, 1))
        assert sel.period_expr == "2023"

    def test_last_12_months_spans_twelve_months_ending_this_month(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-12-months", date(2024, 6, 15))
        assert (sel.begin, sel.end) == (date(2023, 7, 1), date(2024, 7, 1))

    def test_last_12_months_across_year_boundary(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-12-months", date(2024, 1, 10))
        assert (sel.begin, sel.end) == (date(2023, 2, 1), date(2024, 2, 1))

    def test_ytd_starts_jan_first(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("ytd", date(2024, 6, 15))
        assert (sel.begin, sel.end) == (date(2024, 1, 1), date(2024, 6, 16))

    def test_ytd_on_jan_first_is_single_day(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("ytd", date(2024, 1, 1))
        assert (sel.begin, sel.end) == (date(2024, 1, 1), date(2024, 1, 2))

    def test_all_time(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("all", date(2024, 6, 15))
        assert sel.kind == "all"
        assert sel.period_expr == ""

    def test_leap_day_this_month(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("this-month", date(2024, 2, 29))
        assert (sel.begin, sel.end) == (date(2024, 2, 1), date(2024, 3, 1))

    def test_last_month_of_leap_february(self):
        from hledger_textual.period_presets import get_preset

        sel = get_preset("last-month", date(2024, 3, 15))
        assert (sel.begin, sel.end) == (date(2024, 2, 1), date(2024, 3, 1))

    def test_unknown_preset_raises(self):
        from hledger_textual.period_presets import get_preset

        with pytest.raises(KeyError):
            get_preset("fiscal-quarter", date(2024, 6, 15))

    def test_every_preset_round_trips_through_parse(self):
        from hledger_textual.period_presets import get_preset, list_presets

        today = date(2024, 6, 15)
        for preset_id, _label in list_presets():
            sel = get_preset(preset_id, today)
            expr = sel.period_expr
            if expr == "":
                continue  # all time is unbounded by design
            reparsed = parse_period(expr, today=today)
            assert reparsed is not None, f"preset {preset_id} expr {expr!r} does not parse"
            assert (reparsed.begin, reparsed.end) == (sel.begin, sel.end)


class TestListPresets:
    """The preset catalogue is stable and complete."""

    def test_lists_seven_presets_in_order(self):
        from hledger_textual.period_presets import list_presets

        ids = [preset_id for preset_id, _label in list_presets()]
        assert ids == [
            "this-month",
            "last-month",
            "this-year",
            "last-year",
            "last-12-months",
            "ytd",
            "all",
        ]
