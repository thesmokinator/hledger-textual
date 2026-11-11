"""About modal screen showing journal metadata and project information."""

from __future__ import annotations

import importlib.metadata
import webbrowser
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from hledger_textual.fileutil import short_path
from hledger_textual.git import git_branch, git_status_summary, is_git_repo
from hledger_textual.hledger import HledgerError, get_hledger_version, load_journal_stats
from hledger_textual.prices import get_pricehist_version, has_pricehist
from hledger_textual.updates import get_latest_version, is_newer


def _fmt_size(n: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def _row(label: str, value: str) -> str:
    """Format a key-value row with a fixed-width dim label."""
    return f"  [dim]{label:<14}[/dim]{value}"


def _get_project_metadata() -> tuple[str, str, str, str]:
    """Read project metadata from package info.

    Returns:
        Tuple of (version, author, license, repo_url).
    """
    try:
        meta = importlib.metadata.metadata("hledger-textual")
        version = meta.get("Version", "?")
        author = meta.get("Author", "")
        if not author:
            author_email = meta.get("Author-email", "")
            if author_email:
                author = author_email.split("<")[0].strip()
        license_name = meta.get("License-Expression", meta.get("License", "?"))
        repo = ""
        urls = meta.get_all("Project-URL") or []
        for url_entry in urls:
            if "repository" in url_entry.lower() or "homepage" in url_entry.lower():
                repo = url_entry.split(",", 1)[-1].strip()
                break
    except importlib.metadata.PackageNotFoundError:
        version = "?"
        author = ""
        license_name = "?"
        repo = ""

    if not repo:
        repo = "https://github.com/thesmokinator/hledger-textual"

    return version, author, str(license_name), repo


class AboutModal(ModalScreen[None]):
    """Compact modal showing journal metadata, version info, and git status.

    All data is loaded fresh each time the modal opens.
    """

    BINDINGS = [
        Binding("escape", "dismiss_about", "Close"),
        Binding("question_mark", "dismiss_about", "Close"),
    ]

    def __init__(self, journal_file: Path) -> None:
        """Initialize the about modal.

        Args:
            journal_file: Path to the hledger journal file.
        """
        super().__init__()
        self.journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Create the compact about modal layout."""
        loading = "[dim]\u2026[/dim]"
        journal_placeholder = "\n".join([
            _row("Journal", loading),
            _row("Size", loading),
            _row("Transactions", loading),
            _row("Accounts", loading),
            _row("Commodities", loading),
        ])
        tools_placeholder = "\n".join([
            _row("hledger", loading),
            _row("pricehist", loading),
        ])
        with VerticalScroll(id="about-dialog"):
            yield Static("hledger-textual", id="about-title")
            yield Static("", id="about-app")
            yield Static(journal_placeholder, id="about-journal")
            yield Static(tools_placeholder, id="about-tools")
            yield Static("", id="about-git")
            yield Static(
                "Press [b]Esc[/b] or [b]?[/b] to close", id="about-footer"
            )

    def on_mount(self) -> None:
        """Load all data fresh each time the modal opens."""
        self._apply_project_metadata()
        self._load_journal_data()
        self._load_hledger_info()
        self._load_git_info()

    def _build_app_lines(self, version: str, version_status: str) -> list[str]:
        """Build the app info lines with given version status text."""
        _, author, license_name, repo = _get_project_metadata()

        repo_short = repo
        if "github.com/" in repo:
            repo_short = repo.split("github.com/", 1)[1]

        lines = [_row("Version", f"{version} {version_status}")]
        if author:
            lines.append(_row("Author", author))
        lines.append(_row("License", license_name))
        lines.append(
            _row(
                "GitHub",
                f"[@click=screen.open_url('{repo}')]{repo_short}[/]",
            )
        )
        return lines

    def _apply_project_metadata(self) -> None:
        """Read project metadata from package info and display it."""
        version, *_ = _get_project_metadata()

        lines = self._build_app_lines(version, "[dim](checking\u2026)[/dim]")
        self.query_one("#about-app", Static).update("\n".join(lines))

        self._load_update_check(version)

    @work(thread=True, exclusive=True, group="about-update-check")
    def _load_update_check(self, current: str) -> None:
        """Check PyPI for the latest version."""
        latest = get_latest_version()
        self.app.call_from_thread(self._apply_update_check, current, latest)

    def _apply_update_check(self, current: str, latest: str | None) -> None:
        """Refresh the version line with update status."""
        if latest is None:
            status = "[dim](check failed)[/dim]"
        elif is_newer(latest, current):
            status = f"[bold yellow]({latest} available)[/bold yellow]"
        else:
            status = "[dim](up to date)[/dim]"

        lines = self._build_app_lines(current, status)
        self.query_one("#about-app", Static).update("\n".join(lines))

    @work(thread=True, exclusive=True, group="about-journal")
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

        self.app.call_from_thread(self._apply_journal_data, stats, size_str)

    def _apply_journal_data(self, stats, size_str: str) -> None:
        """Apply loaded journal data to the UI."""
        short = short_path(self.journal_file)
        lines = [_row("Journal", short)]
        lines.append(_row("Size", size_str))

        if stats is not None:
            lines.append(_row("Transactions", str(stats.transaction_count)))
            lines.append(_row("Accounts", str(stats.account_count)))
            if stats.commodities:
                lines.append(_row("Commodities", ", ".join(stats.commodities)))

        self.query_one("#about-journal", Static).update("\n".join(lines))

    @work(thread=True, exclusive=True, group="about-hledger")
    def _load_hledger_info(self) -> None:
        """Load hledger and pricehist versions in a background thread."""
        hledger_version = get_hledger_version()
        pricehist_version = (
            get_pricehist_version() if has_pricehist() else "Not installed"
        )
        self.app.call_from_thread(
            self._apply_hledger_info, hledger_version, pricehist_version
        )

    def _apply_hledger_info(
        self, hledger_version: str, pricehist_version: str
    ) -> None:
        """Apply hledger and pricehist info to the UI."""
        lines = [
            _row("hledger", hledger_version),
            _row("pricehist", pricehist_version),
        ]
        self.query_one("#about-tools", Static).update("\n".join(lines))

    @work(thread=True, exclusive=True, group="about-git")
    def _load_git_info(self) -> None:
        """Load git repo info in a background thread."""
        if not is_git_repo(self.journal_file):
            return

        branch = git_branch(self.journal_file)
        status = git_status_summary(self.journal_file)
        self.app.call_from_thread(self._apply_git_info, branch, status)

    def _apply_git_info(self, branch: str, status: str) -> None:
        """Show the git section."""
        text = _row("Git", f"{branch} \u00b7 {status}")
        self.query_one("#about-git", Static).update(text)

    def action_open_url(self, url: str) -> None:
        """Open a URL in the default browser."""
        webbrowser.open(url)

    def action_dismiss_about(self) -> None:
        """Close the about modal."""
        self.dismiss(None)
