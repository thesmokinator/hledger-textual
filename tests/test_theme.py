"""Tests for resolving the saved theme against Textual's themes."""

from __future__ import annotations

from pathlib import Path

from hledger_textual.app import HledgerTuiApp, _resolve_saved_theme


def test_textual_ansi_migrates_to_ansi_dark() -> None:
    """The removed textual-ansi theme maps to ansi-dark when available."""
    assert _resolve_saved_theme("textual-ansi", {"ansi-dark": object()}) == "ansi-dark"


def test_textual_ansi_falls_back_when_ansi_dark_is_missing() -> None:
    """Older Textual 8 releases do not ship ansi-dark."""
    assert _resolve_saved_theme("textual-ansi", {"textual-dark": object()}) is None


def test_unknown_theme_is_ignored() -> None:
    """An unknown theme name falls back to Textual's default."""
    assert _resolve_saved_theme("does-not-exist", {"textual-dark": object()}) is None


def test_no_saved_theme_keeps_default() -> None:
    """No saved theme keeps Textual's default theme."""
    assert _resolve_saved_theme(None, {"textual-dark": object()}) is None


def test_app_uses_migrated_theme(
    tmp_path: Path, monkeypatch
) -> None:
    """A saved textual-ansi theme does not crash app construction."""
    monkeypatch.setattr("hledger_textual.app.load_theme", lambda: "textual-ansi")
    journal = tmp_path / "theme.journal"
    journal.write_text("", encoding="utf-8")

    app = HledgerTuiApp(journal_file=journal)

    assert app.theme in {"ansi-dark", "textual-dark"}
