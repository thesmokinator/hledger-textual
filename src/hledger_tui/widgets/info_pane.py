"""Info pane widget showing journal metadata and project information."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from hledger_tui.config import _CONFIG_PATH
from hledger_tui.hledger import HledgerError, get_hledger_version, load_journal_stats
from hledger_tui.prices import get_pricehist_version, has_pricehist


def _fmt_size(n: int) -> str:
    """Format a file size in bytes to a human-readable string.

    Args:
        n: Size in bytes.

    Returns:
        A string like '12.4 KB' or '1.2 MB'.
    """
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


class InfoPane(Widget):
    """Widget showing journal metadata and project information."""

    CAN_FOCUS = True

    BINDINGS: list[Binding] = []

    def __init__(self, journal_file: Path, **kwargs) -> None:
        """Initialize the info pane.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__(**kwargs)
        self.journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Create the info pane layout with two columns."""
        with Horizontal(id="info-columns"):
            # Left column: Journal + Configuration
            with Vertical(classes="info-column"):
                with Vertical(classes="info-section"):
                    yield Static("Journal", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Path", classes="info-label")
                        yield Static("", id="info-path")
                    with Horizontal(classes="info-row"):
                        yield Static("Size", classes="info-label")
                        yield Static("", id="info-size")
                    with Horizontal(classes="info-row"):
                        yield Static("Transactions", classes="info-label")
                        yield Static("", id="info-txn-count")
                    with Horizontal(classes="info-row"):
                        yield Static("Accounts", classes="info-label")
                        yield Static("", id="info-acct-count")
                    with Horizontal(classes="info-row"):
                        yield Static("Commodities", classes="info-label")
                        yield Static("", id="info-commodity")

                with Vertical(classes="info-section"):
                    yield Static("Configuration", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Config", classes="info-label")
                        yield Static("", id="info-config-path")
                    with Horizontal(classes="info-row"):
                        yield Static("Theme", classes="info-label")
                        yield Static("", id="info-theme")

            # Right column: About + hledger
            with Vertical(classes="info-column"):
                with Vertical(classes="info-section"):
                    yield Static("About", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Name", classes="info-label")
                        yield Static("", id="info-name")
                    with Horizontal(classes="info-row"):
                        yield Static("Version", classes="info-label")
                        yield Static("", id="info-version")
                    with Horizontal(classes="info-row"):
                        yield Static("Author", classes="info-label")
                        yield Static("", id="info-author")
                    with Horizontal(classes="info-row"):
                        yield Static("License", classes="info-label")
                        yield Static("", id="info-license")
                    with Horizontal(classes="info-row"):
                        yield Static("Repository", classes="info-label")
                        yield Static("", id="info-repo")

                with Vertical(classes="info-section"):
                    yield Static("hledger", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Version", classes="info-label")
                        yield Static("", id="info-hledger-version")

                with Vertical(classes="info-section"):
                    yield Static("pricehist", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Version", classes="info-label")
                        yield Static("", id="info-pricehist-version")

    def on_mount(self) -> None:
        """Load project metadata and start fetching journal stats."""
        self._apply_project_metadata()
        self._apply_config_info()
        self._load_journal_data()
        self._load_hledger_info()

    def _apply_project_metadata(self) -> None:
        """Read project metadata from package info and display it."""
        try:
            meta = importlib.metadata.metadata("hledger-tui")
            name = meta.get("Name", "hledger-tui")
            version = meta.get("Version", "?")
            author = meta.get("Author", "")
            if not author:
                author_email = meta.get("Author-email", "")
                if author_email:
                    # Extract name from "Name <email>" format
                    author = author_email.split("<")[0].strip()
            license_name = meta.get("License-Expression", meta.get("License", "?"))
            repo = ""
            urls = meta.get_all("Project-URL") or []
            for url_entry in urls:
                if "repository" in url_entry.lower() or "homepage" in url_entry.lower():
                    repo = url_entry.split(",", 1)[-1].strip()
                    break
        except importlib.metadata.PackageNotFoundError:
            name = "hledger-tui"
            version = "?"
            author = ""
            license_name = "?"
            repo = ""

        # Fallback for repo URL when metadata doesn't include it
        if not repo:
            repo = "https://github.com/thesmokinator/hledger-tui"

        self.query_one("#info-name", Static).update(name)
        self.query_one("#info-version", Static).update(version)
        if author:
            self.query_one("#info-author", Static).update(author)
        self.query_one("#info-license", Static).update(str(license_name))
        self.query_one("#info-repo", Static).update(repo)

    def _apply_config_info(self) -> None:
        """Display configuration file path and current theme."""
        self.query_one("#info-config-path", Static).update(str(_CONFIG_PATH))
        self.query_one("#info-theme", Static).update(self.app.theme)

    def apply_theme(self, theme: str) -> None:
        """Update the displayed theme name after a theme change."""
        self.query_one("#info-theme", Static).update(theme)

    @work(thread=True, exclusive=True, group="info-journal")
    def _load_journal_data(self) -> None:
        """Load journal stats and file size in a background thread."""
        try:
            stats = load_journal_stats(self.journal_file)
        except HledgerError:
            stats = None

        try:
            size_bytes = Path(self.journal_file).stat().st_size
            size_str = _fmt_size(size_bytes)
        except OSError:
            size_str = "?"

        self.app.call_from_thread(
            self._apply_journal_data, stats, size_str
        )

    def _apply_journal_data(self, stats, size_str: str) -> None:
        """Apply loaded journal data to the UI."""
        self.query_one("#info-path", Static).update(str(self.journal_file))
        self.query_one("#info-size", Static).update(size_str)

        if stats is not None:
            self.query_one("#info-txn-count", Static).update(
                str(stats.transaction_count)
            )
            self.query_one("#info-acct-count", Static).update(
                str(stats.account_count)
            )
            commodity_str = (
                ", ".join(stats.commodities) if stats.commodities else "\u2014"
            )
            self.query_one("#info-commodity", Static).update(commodity_str)

    @work(thread=True, exclusive=True, group="info-hledger")
    def _load_hledger_info(self) -> None:
        """Load hledger and pricehist versions in a background thread."""
        hledger_version = get_hledger_version()
        pricehist_version = get_pricehist_version() if has_pricehist() else "Not installed"

        self.app.call_from_thread(
            self._apply_hledger_info, hledger_version, pricehist_version
        )

    def _apply_hledger_info(
        self, hledger_version: str, pricehist_version: str
    ) -> None:
        """Apply hledger and pricehist info to the UI."""
        self.query_one("#info-hledger-version", Static).update(hledger_version)
        self.query_one("#info-pricehist-version", Static).update(pricehist_version)
