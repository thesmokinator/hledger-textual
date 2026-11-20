"""Tests for the Textual compatibility helpers.

The helpers exist because Textual renamed the "nothing selected" sentinel of
``Select`` (``BLANK`` in 7.x, ``NULL`` in 8.x).  Referencing the attribute
directly crashes on the wrong version, so these tests lock in the portable
``isinstance`` check and forbid direct references in the codebase.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import Select
from textual.widgets.select import NoSelection

from hledger_textual.textual_compat import (
    is_no_selection,
    is_supported_textual,
    parse_textual_version,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "hledger_textual"


def _no_selection_sentinel() -> object:
    """Return the installed Textual's "no selection" sentinel."""
    return getattr(Select, "NULL", getattr(Select, "BLANK", None))


class TestIsNoSelection:
    """is_no_selection recognises the sentinel on every Textual version."""

    @pytest.mark.parametrize("value", [_no_selection_sentinel(), NoSelection()])
    def test_sentinel_is_detected(self, value: object) -> None:
        """The sentinel, however it is named, counts as no selection."""
        assert is_no_selection(value) is True

    @pytest.mark.parametrize("value", ["yes", "", "2024-01", 0, 1, None, False])
    def test_real_values_are_not_sentinels(self, value: object) -> None:
        """Actual option values never count as no selection."""
        assert is_no_selection(value) is False


class TestParseTextualVersion:
    """Version strings are parsed into comparable tuples."""

    @pytest.mark.parametrize(
        ("version", "expected"),
        [
            ("8.2.8", (8, 2, 8)),
            ("8", (8,)),
            ("8.3.0b1", (8, 3, 0)),
            ("8.2.8+local", (8, 2, 8)),
            ("", ()),
            ("unknown", ()),
        ],
    )
    def test_parse(self, version: str, expected: tuple[int, ...]) -> None:
        """Only leading numeric components are kept."""
        assert parse_textual_version(version) == expected


class TestIsSupportedTextual:
    """The supported range mirrors pyproject's textual>=8.0,<9."""

    @pytest.mark.parametrize("version", ["8.0.0", "8.2.8", "8", "8.3.0b1"])
    def test_supported(self, version: str) -> None:
        """Textual 8.x is supported."""
        assert is_supported_textual(version) is True

    @pytest.mark.parametrize("version", ["7.4.0", "7", "9.0.0", "10.0", "", "x"])
    def test_unsupported(self, version: str) -> None:
        """Textual 7.x, 9+ and unparsable versions are rejected."""
        assert is_supported_textual(version) is False


def test_no_direct_select_sentinel_references() -> None:
    """No module may reference Select.NULL / Select.BLANK directly.

    Direct references are what produced the crash
    ``AttributeError: type object 'Select' has no attribute 'NULL'`` on
    Textual 7.x.  The compat module is the only allowed place, and only in
    documentation strings.
    """
    offenders: list[str] = []
    for path in SOURCE_ROOT.rglob("*.py"):
        if path.name == "textual_compat.py":
            continue
        text = path.read_text(encoding="utf-8")
        for marker in ("Select.NULL", "Select.BLANK"):
            if marker in text:
                offenders.append(f"{path.relative_to(SOURCE_ROOT)}: {marker}")
    assert offenders == [], offenders
