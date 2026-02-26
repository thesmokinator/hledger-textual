"""Tests for the InfoPane widget."""

from __future__ import annotations

import importlib.metadata
from datetime import date
from pathlib import Path

import pytest

from textual.app import App, ComposeResult
from textual.widgets import Static

from hledger_tui.widgets.info_pane import InfoPane, _fmt_size
from tests.conftest import has_hledger


class _InfoApp(App):
    """Minimal app wrapping InfoPane for isolated widget testing."""

    def __init__(self, journal_file: Path) -> None:
        """Initialize with a journal file path."""
        super().__init__()
        self._journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Compose a single InfoPane."""
        yield InfoPane(self._journal_file)


@pytest.fixture
def info_journal(tmp_path: Path) -> Path:
    """A minimal journal for InfoPane testing."""
    today = date.today()
    d1 = today.replace(day=1)
    content = (
        f"{d1.isoformat()} * Grocery shopping\n"
        "    expenses:food              €40.80\n"
        "    assets:bank:checking\n"
    )
    journal = tmp_path / "test.journal"
    journal.write_text(content)
    return journal


# ------------------------------------------------------------------
# Pure-function tests (no hledger needed)
# ------------------------------------------------------------------


class TestFmtSize:
    """Tests for _fmt_size helper."""

    def test_bytes(self):
        """Sizes below 1 KiB are displayed as bytes."""
        assert _fmt_size(512) == "512 B"

    def test_kilobytes(self):
        """Sizes in KiB range display with one decimal."""
        assert _fmt_size(1024) == "1.0 KB"
        assert _fmt_size(int(12.4 * 1024)) == "12.4 KB"

    def test_megabytes(self):
        """Sizes in MiB range display as MB."""
        assert _fmt_size(2 * 1024 * 1024) == "2.0 MB"


# ------------------------------------------------------------------
# Integration tests (require hledger)
# ------------------------------------------------------------------


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestInfoPaneMount:
    """Tests for InfoPane initial render."""

    async def test_pane_mounts_without_error(self, info_journal: Path):
        """InfoPane mounts without raising exceptions."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one(InfoPane) is not None

    async def test_journal_section_title_exists(self, info_journal: Path):
        """The Journal section title is present."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            titles = [
                s.renderable
                for s in app.query(".info-section-title")
            ]
            assert "Journal" in [str(t) for t in titles]

    async def test_about_section_title_exists(self, info_journal: Path):
        """The About section title is present."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            titles = [
                s.renderable
                for s in app.query(".info-section-title")
            ]
            assert "About" in [str(t) for t in titles]


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestInfoPaneDataLoad:
    """Tests for background data loading in InfoPane."""

    async def test_path_shown_after_load(self, info_journal: Path):
        """After loading, the journal path is shown in #info-path."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            path_label = app.query_one("#info-path", Static)
            assert str(info_journal) in str(path_label.renderable)

    async def test_version_shown(self, info_journal: Path):
        """Project version is displayed in #info-version."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            version_label = app.query_one("#info-version", Static)
            text = str(version_label.renderable)
            # Should show a version string (not empty or "?")
            assert text and text != "?"

    async def test_name_shown(self, info_journal: Path):
        """Project name is displayed in #info-name."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            name_label = app.query_one("#info-name", Static)
            assert "hledger-tui" in str(name_label.renderable)

    async def test_txn_count_shown(self, info_journal: Path):
        """Transaction count is shown after data loads."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            txn_label = app.query_one("#info-txn-count", Static)
            text = str(txn_label.renderable)
            assert text.isdigit()


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestInfoPaneErrors:
    """Tests for error handling in InfoPane."""

    async def test_load_stats_error_does_not_crash(
        self, info_journal: Path, monkeypatch
    ):
        """HledgerError during stats load is silently handled."""
        from hledger_tui.hledger import HledgerError

        def _raise(*args, **kwargs):
            raise HledgerError("stats failed")

        monkeypatch.setattr(
            "hledger_tui.widgets.info_pane.load_journal_stats", _raise
        )
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            assert app.query_one(InfoPane) is not None


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestInfoPaneRefresh:
    """Tests for the refresh action."""

    async def test_r_key_triggers_refresh(self, info_journal: Path):
        """Pressing r reloads data without crashing."""
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=0.5)
            await pilot.press("r")
            await pilot.pause(delay=0.5)
            assert app.query_one(InfoPane) is not None


@pytest.mark.skipif(not has_hledger(), reason="hledger not installed")
class TestInfoPaneMetadataFallbacks:
    """Tests for metadata fallback paths in InfoPane."""

    async def test_package_not_found_fallback(
        self, info_journal: Path, monkeypatch
    ):
        """When PackageNotFoundError is raised, the pane still shows 'hledger-tui'."""

        def _raise_not_found(name):
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(
            "hledger_tui.widgets.info_pane.importlib.metadata.metadata",
            _raise_not_found,
        )
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause()
            name_label = app.query_one("#info-name", Static)
            assert "hledger-tui" in str(name_label.renderable)

    async def test_os_error_file_size(
        self, info_journal: Path, monkeypatch
    ):
        """When Path.stat raises OSError, #info-size shows '?'."""
        original_stat = Path.stat

        def _stat_raises(self, *args, **kwargs):
            if self.suffix == ".journal":
                raise OSError("disk error")
            return original_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", _stat_raises)
        app = _InfoApp(info_journal)
        async with app.run_test() as pilot:
            await pilot.pause(delay=1.0)
            size_label = app.query_one("#info-size", Static)
            assert str(size_label.renderable) == "?"
