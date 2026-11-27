"""Tests for global query compose/validate helpers (issue #281)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_compose_skips_empties() -> None:
    from hledger_textual.query import compose_query

    assert compose_query("date:2024", "", None, "tag:x") == "date:2024 tag:x"


def test_compose_all_empty_is_none() -> None:
    from hledger_textual.query import compose_query

    assert compose_query("", None, "   ") is None


def test_compose_single_part() -> None:
    from hledger_textual.query import compose_query

    assert compose_query("tag:x") == "tag:x"


def test_validate_ok_calls_print_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from hledger_textual.query import validate_query

    seen: list[tuple[tuple[str, ...], Path | None]] = []

    def fake_run(*args: str, file=None) -> str:
        seen.append((args, file))
        return ""

    monkeypatch.setattr("hledger_textual.query.run_hledger", fake_run)
    validate_query(Path("j.journal"), "tag:x")
    assert seen == [(("print", "tag:x", "-n", "1"), Path("j.journal"))]


def test_validate_blank_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    from hledger_textual.query import validate_query

    def fake_run(*args: str, file=None) -> str:  # pragma: no cover
        raise AssertionError("must not invoke hledger for a blank query")

    monkeypatch.setattr("hledger_textual.query.run_hledger", fake_run)
    validate_query(Path("j.journal"), "   ")


def test_validate_bad_query_raises_clean_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hledger_textual.hledger import HledgerError
    from hledger_textual.query import InvalidQueryError, validate_query

    def fake_run(*args: str, file=None) -> str:
        raise HledgerError("no matching matchers?")

    monkeypatch.setattr("hledger_textual.query.run_hledger", fake_run)
    with pytest.raises(InvalidQueryError, match=r"tag:\["):
        validate_query(Path("j.journal"), "tag:[")
