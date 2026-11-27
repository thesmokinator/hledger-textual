"""Tests for saved period views persistence (issue #277)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the config file at an empty temp path."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("hledger_textual.config._CONFIG_PATH", config_file)
    return config_file


class TestPeriodViews:
    """load/save/delete/rename round-trips in the [period_views] section."""

    def test_save_and_load_round_trip(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, save_period_view

        save_period_view("FY2024", "2024")
        assert load_period_views() == {"FY2024": "2024"}

    def test_values_coerced_to_str(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, save_period_view

        save_period_view("Q3", "2024-07..2024-09")
        assert load_period_views() == {"Q3": "2024-07..2024-09"}

    def test_blank_name_is_rejected(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, save_period_view

        save_period_view("   ", "2024-03")
        assert load_period_views() == {}

    def test_duplicate_name_overwrites(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, save_period_view

        save_period_view("FY2024", "2023")
        save_period_view("FY2024", "2024")
        assert load_period_views() == {"FY2024": "2024"}

    def test_delete_removes_view(self, tmp_config: Path) -> None:
        from hledger_textual.config import (
            delete_period_view,
            load_period_views,
            save_period_view,
        )

        save_period_view("FY2024", "2024")
        delete_period_view("FY2024")
        assert load_period_views() == {}

    def test_delete_missing_is_noop(self, tmp_config: Path) -> None:
        from hledger_textual.config import delete_period_view, load_period_views

        delete_period_view("ghost")  # must not raise
        assert load_period_views() == {}

    def test_rename_moves_expression(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, rename_period_view, save_period_view

        save_period_view("old", "2024")
        rename_period_view("old", "new")
        assert load_period_views() == {"new": "2024"}

    def test_rename_missing_source_is_noop(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, rename_period_view

        rename_period_view("ghost", "new")
        assert load_period_views() == {}

    def test_rename_to_blank_is_rejected(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, rename_period_view, save_period_view

        save_period_view("old", "2024")
        rename_period_view("old", "   ")
        assert load_period_views() == {"old": "2024"}

    def test_empty_config_returns_empty_dict(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views

        assert load_period_views() == {}

    def test_all_time_expression_round_trips(self, tmp_config: Path) -> None:
        from hledger_textual.config import load_period_views, save_period_view

        save_period_view("Everything", "")
        assert load_period_views() == {"Everything": ""}
