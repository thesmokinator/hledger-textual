"""Combined help and about screen with tabbed Shortcuts / About sections."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static, TabPane, TabbedContent

from hledger_textual.hledger import HledgerError, get_hledger_version, load_journal_stats


def _row(key: str, desc: str) -> str:
    """Format a single shortcut row with fixed-width key column."""
    return f"  {key:<14}{desc}"


def _info_row(label: str, value: str) -> str:
    """Format a key-value row with a dim label for the about section."""
    return f"  [dim]{label:<14}[/dim]{value}"


def _build_help_text() -> str:
    """Build the full help text with aligned columns."""
    sections = [
        (
            "Global",
            [
                ("1-6", "Switch tab"),
                ("x", "Export (CSV/PDF)"),
                ("s", "Sync (if enabled)"),
                ("?", "This help"),
                ("q", "Quit"),
            ],
        ),
        (
            "Transactions",
            [
                ("a", "Add transaction"),
                ("e / Enter", "Edit transaction"),
                ("d", "Delete transaction"),
                ("c", "Clone transaction"),
                ("m", "Move to another date"),
                ("i", "Import from CSV"),
                ("*", "Toggle cleared"),
                ("!", "Toggle pending"),
                ("Left / Right", "Navigate months"),
                ("t", "Jump to today"),
                ("/", "Search"),
                ("f", "Saved filters"),
                ("ctrl+s", "Save current filter"),
                ("r", "Refresh"),
            ],
        ),
        (
            "Recurring",
            [
                ("a", "Add rule"),
                ("e / Enter", "Edit rule"),
                ("d", "Delete rule"),
                ("g", "Generate transactions"),
                ("r", "Reload"),
            ],
        ),
        (
            "Budget",
            [
                ("a", "Add rule"),
                ("e", "Edit rule"),
                ("d", "Delete rule"),
                ("Left / Right", "Navigate months"),
                ("t", "Jump to today"),
                ("/", "Search"),
            ],
        ),
        (
            "Accounts",
            [
                ("Enter", "Drill down"),
                ("/", "Search"),
                ("r", "Reload"),
            ],
        ),
        (
            "Reports",
            [
                ("c", "Toggle chart"),
                ("i", "Investment view"),
                ("S", "Sort by amount"),
                ("r", "Reload"),
            ],
        ),
    ]
    parts: list[str] = []
    for title, shortcuts in sections:
        parts.append(f"[b]{title}[/b]")
        for key, desc in shortcuts:
            parts.append(_row(key, desc))
        parts.append("")
    return "\n".join(parts).rstrip()


_HELP_TEXT = _build_help_text()


def _short_path(p: Path) -> str:
    """Shorten a path by replacing the home directory with ~."""
    try:
        return str(Path("~") / p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def _fmt_size(n: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


class HelpScreen(ModalScreen[None]):
    """Modal with two tabs: Shortcuts and About."""

    BINDINGS = [
        Binding("escape", "dismiss_help", "Close"),
        Binding("question_mark", "dismiss_help", "Close"),
    ]

    def __init__(self, journal_file: Path | None = None) -> None:
        """Initialize the help screen.

        Args:
            journal_file: Path to the journal file (for about info).
        """
        super().__init__()
        self.journal_file = journal_file

    def compose(self) -> ComposeResult:
        """Create the tabbed help dialog."""
        with Vertical(id="help-dialog"):
            yield Static("Help", id="help-title")
            with TabbedContent(id="help-tabs"):
                with TabPane("Shortcuts", id="help-tab-shortcuts"):
                    with VerticalScroll(id="help-shortcuts-scroll"):
                        yield Static(_HELP_TEXT, id="help-content")
                with TabPane("About", id="help-tab-about"):
                    with VerticalScroll(id="help-about-scroll"):
                        yield Static(
                            "[dim]Loading...[/dim]", id="help-about-section"
                        )
            yield Static(
                "Press [b]Esc[/b] or [b]?[/b] to close", id="help-footer"
            )

    def on_mount(self) -> None:
        """Load about info if journal file is available."""
        if self.journal_file is not None:
            self._load_about_info()

    @work(thread=True, exclusive=True, group="help-about")
    def _load_about_info(self) -> None:
        """Load journal and app metadata in a background thread."""
        import importlib.metadata

        from hledger_textual.git import git_branch, git_status_summary, is_git_repo
        from hledger_textual.prices import get_pricehist_version, has_pricehist

        lines: list[str] = []

        # App version
        try:
            meta = importlib.metadata.metadata("hledger-textual")
            version = meta.get("Version", "?")
        except importlib.metadata.PackageNotFoundError:
            version = "?"
        lines.append(_info_row("Version", version))

        # hledger version
        hledger_version = get_hledger_version()
        lines.append(_info_row("hledger", hledger_version))

        # pricehist
        ph_version = get_pricehist_version() if has_pricehist() else "Not installed"
        lines.append(_info_row("pricehist", ph_version))

        lines.append("")

        # Journal info
        assert self.journal_file is not None
        short = _short_path(self.journal_file)
        lines.append(_info_row("Journal", short))

        try:
            size_str = _fmt_size(self.journal_file.stat().st_size)
            lines.append(_info_row("Size", size_str))
        except OSError:
            pass

        try:
            stats = load_journal_stats(self.journal_file)
            lines.append(_info_row("Transactions", str(stats.transaction_count)))
            lines.append(_info_row("Accounts", str(stats.account_count)))
            if stats.commodities:
                lines.append(_info_row("Commodities", ", ".join(stats.commodities)))
        except HledgerError:
            pass

        # Git info
        if is_git_repo(self.journal_file):
            branch = git_branch(self.journal_file)
            status = git_status_summary(self.journal_file)
            lines.append("")
            lines.append(_info_row("Git", f"{branch} \u00b7 {status}"))

        self.app.call_from_thread(
            self.query_one("#help-about-section", Static).update,
            "\n".join(lines),
        )

    def action_dismiss_help(self) -> None:
        """Close the help screen."""
        self.dismiss(None)
