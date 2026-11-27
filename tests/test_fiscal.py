"""Fiscal year boundary arithmetic (issue #279)."""

from __future__ import annotations

from datetime import date


class TestFiscalYearOf:
    """fiscal_year_of labels a day by its fiscal year (starting-year)."""

    def test_january_start_matches_calendar(self) -> None:
        from hledger_textual.fiscal import fiscal_year_of

        assert fiscal_year_of(date(2024, 6, 15), 1) == 2024

    def test_april_start_january_belongs_to_prior_fy(self) -> None:
        from hledger_textual.fiscal import fiscal_year_of

        assert fiscal_year_of(date(2024, 1, 15), 4) == 2023
        assert fiscal_year_of(date(2024, 3, 31), 4) == 2023

    def test_april_start_april_belongs_to_new_fy(self) -> None:
        from hledger_textual.fiscal import fiscal_year_of

        assert fiscal_year_of(date(2024, 4, 1), 4) == 2024
        assert fiscal_year_of(date(2025, 3, 31), 4) == 2024

    def test_july_start_december_boundary(self) -> None:
        from hledger_textual.fiscal import fiscal_year_of

        assert fiscal_year_of(date(2024, 6, 30), 7) == 2023
        assert fiscal_year_of(date(2024, 7, 1), 7) == 2024


class TestFiscalBounds:
    """Begin/end-exclusive bounds for a fiscal year."""

    def test_april_bounds(self) -> None:
        from hledger_textual.fiscal import (
            fiscal_year_begin,
            fiscal_year_end_exclusive,
        )

        assert fiscal_year_begin(2024, 4) == date(2024, 4, 1)
        assert fiscal_year_end_exclusive(2024, 4) == date(2025, 4, 1)

    def test_january_bounds_match_calendar(self) -> None:
        from hledger_textual.fiscal import (
            fiscal_year_begin,
            fiscal_year_end_exclusive,
        )

        assert fiscal_year_begin(2024, 1) == date(2024, 1, 1)
        assert fiscal_year_end_exclusive(2024, 1) == date(2025, 1, 1)


class TestFiscalYtd:
    """fiscal_ytd spans the fiscal start through today."""

    def test_ytd_starts_at_fiscal_start(self) -> None:
        from hledger_textual.fiscal import fiscal_ytd

        sel = fiscal_ytd(date(2024, 6, 15), 4)
        assert (sel.begin, sel.end) == (date(2024, 4, 1), date(2024, 6, 16))

    def test_january_ytd_matches_calendar(self) -> None:
        from hledger_textual.fiscal import fiscal_ytd
        from hledger_textual.period import range_selection

        assert fiscal_ytd(date(2024, 6, 15), 1) == range_selection(
            date(2024, 1, 1), date(2024, 6, 15)
        )

    def test_ytd_on_first_day_of_fy_is_single_day(self) -> None:
        from hledger_textual.fiscal import fiscal_ytd

        sel = fiscal_ytd(date(2024, 4, 1), 4)
        assert (sel.begin, sel.end) == (date(2024, 4, 1), date(2024, 4, 2))

    def test_leap_day_inside_april_fy(self) -> None:
        from hledger_textual.fiscal import fiscal_ytd

        sel = fiscal_ytd(date(2024, 2, 29), 4)
        assert (sel.begin, sel.end) == (date(2023, 4, 1), date(2024, 3, 1))
