"""Info pane widget showing journal metadata and project information."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from hledger_textual.config import _CONFIG_PATH
from hledger_textual.git import git_branch, git_status_summary, is_git_repo
from hledger_textual.hledger import HledgerError, get_hledger_version, load_journal_stats
from hledger_textual.prices import get_pricehist_version, has_pricehist


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

                with Vertical(classes="info-section", id="info-git-section"):
                    yield Static("Git", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Branch", classes="info-label")
                        yield Static("", id="info-git-branch")
                    with Horizontal(classes="info-row"):
                        yield Static("Status", classes="info-label")
                        yield Static("", id="info-git-status")

                with Vertical(classes="info-section", id="info-ai-section"):
                    yield Static("AI", classes="info-section-title")
                    with Horizontal(classes="info-row"):
                        yield Static("Enabled", classes="info-label")
                        yield Static("", id="info-ai-enabled")
                    with Horizontal(classes="info-row"):
                        yield Static("Model", classes="info-label")
                        yield Static("", id="info-ai-model")
                    with Horizontal(classes="info-row"):
                        yield Static("Endpoint", classes="info-label")
                        yield Static("", id="info-ai-endpoint")
                    with Horizontal(classes="info-row"):
                        yield Static("Status", classes="info-label")
                        yield Static("", id="info-ai-status")

    def on_mount(self) -> None:
        """Load project metadata and start fetching journal stats."""
        self.query_one("#info-git-section").styles.display = "none"
        self.query_one("#info-ai-section").styles.display = "none"
        self._apply_project_metadata()
        self._apply_config_info()
        self._load_journal_data()
        self._load_hledger_info()
        self._load_git_info()
        self._load_ai_info()

    def _apply_project_metadata(self) -> None:
        """Read project metadata from package info and display it."""
        try:
            meta = importlib.metadata.metadata("hledger-textual")
            name = meta.get("Name", "hledger-textual")
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
            name = "hledger-textual"
            version = "?"
            author = ""
            license_name = "?"
            repo = ""

        # Fallback for repo URL when metadata doesn't include it
        if not repo:
            repo = "https://github.com/thesmokinator/hledger-textual"

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

    @work(thread=True, exclusive=True, group="info-git")
    def _load_git_info(self) -> None:
        """Load git repo info in a background thread."""
        if not is_git_repo(self.journal_file):
            return

        branch = git_branch(self.journal_file)
        status = git_status_summary(self.journal_file)
        self.app.call_from_thread(self._apply_git_info, branch, status)

    def _apply_git_info(self, branch: str, status: str) -> None:
        """Show the git section and populate branch/status labels."""
        self.query_one("#info-git-section").styles.display = "block"
        self.query_one("#info-git-branch", Static).update(branch)
        self.query_one("#info-git-status", Static).update(status)

    def refresh_git_status(self) -> None:
        """Reload git info (called after a sync operation)."""
        self._load_git_info()

    @work(thread=True, exclusive=True, group="info-ai")
    def _load_ai_info(self) -> None:
        """Load AI configuration and Ollama status in a background thread."""
        from hledger_textual.config import load_ai_config

        ai_cfg = load_ai_config()
        if not ai_cfg["enable"]:
            return

        from hledger_textual.ai.ollama_client import OllamaClient

        client = OllamaClient(ai_cfg["endpoint"], ai_cfg["model"])
        reachable = client.health_check()
        if reachable:
            models = client.list_models()
            model_installed = ai_cfg["model"] in models
        else:
            model_installed = False

        if not reachable:
            status = "Ollama not reachable"
        elif not model_installed:
            status = "Model not installed"
        else:
            status = "Ready"

        self.app.call_from_thread(
            self._apply_ai_info, ai_cfg, status
        )

    def _apply_ai_info(self, ai_cfg: dict, status: str) -> None:
        """Show the AI section and populate its labels."""
        self.query_one("#info-ai-section").styles.display = "block"
        self.query_one("#info-ai-enabled", Static).update("Yes")
        self.query_one("#info-ai-model", Static).update(ai_cfg["model"])
        self.query_one("#info-ai-endpoint", Static).update(ai_cfg["endpoint"])
        self.query_one("#info-ai-status", Static).update(status)
