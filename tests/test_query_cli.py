"""Tests for the repeatable --query flag and startup validation (#281)."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_query_flag_repeatable() -> None:
    from hledger_textual.config import parse_args

    args = parse_args(["--query", "tag:a", "--query", "not:cleared"])
    assert args.query == ["tag:a", "not:cleared"]


def test_query_flag_absent_is_none() -> None:
    from hledger_textual.config import parse_args

    assert parse_args([]).query is None


def test_resolve_joins_and_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    from hledger_textual.__main__ import _resolve_initial_query

    seen: list[str] = []

    def fake_validate(file, query: str) -> None:
        seen.append(query)

    monkeypatch.setattr(
        "hledger_textual.__main__.validate_query", fake_validate
    )
    result = _resolve_initial_query(
        ["tag:a", "not:cleared"], Path("j.journal")
    )
    assert result == "tag:a not:cleared"
    assert seen == ["tag:a not:cleared"]


def test_resolve_no_flag_returns_none() -> None:
    from hledger_textual.__main__ import _resolve_initial_query

    assert _resolve_initial_query(None, Path("j.journal")) is None
    assert _resolve_initial_query([], Path("j.journal")) is None


def test_resolve_invalid_aborts(monkeypatch: pytest.MonkeyPatch) -> None:
    from hledger_textual.__main__ import _resolve_initial_query
    from hledger_textual.query import InvalidQueryError

    def fake_validate(file, query: str) -> None:
        raise InvalidQueryError(f"Invalid query {query!r}: boom")

    monkeypatch.setattr(
        "hledger_textual.__main__.validate_query", fake_validate
    )
    with pytest.raises(ValueError, match="Invalid --query"):
        _resolve_initial_query(["tag:["], Path("j.journal"))
