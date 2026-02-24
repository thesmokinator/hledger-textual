"""Entry point for hledger-tui."""

from hledger_tui.app import HledgerTuiApp
from hledger_tui.config import parse_args, resolve_journal_file


def main() -> None:
    """Run the hledger-tui application."""
    args = parse_args()
    journal_file = resolve_journal_file(cli_file=args.file)
    app = HledgerTuiApp(journal_file=journal_file)
    app.run()


if __name__ == "__main__":
    main()
