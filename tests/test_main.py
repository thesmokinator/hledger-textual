"""Unit tests for the application entry point (85% push)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


class TestMain:
    """main() wires CLI parsing, journal resolution and app startup."""

    def test_main_runs_app_with_resolved_journal(self, tmp_path: Path):
        """main parses args, resolves the journal and runs the app."""
        from hledger_textual import __main__ as main_module

        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")

        args = MagicMock()
        args.file = None
        app = MagicMock()

        with (
            patch.object(main_module, "parse_args", return_value=args),
            patch.object(
                main_module, "resolve_journal_file", return_value=journal
            ) as resolve,
            patch.object(main_module, "HledgerTuiApp", return_value=app) as app_cls,
        ):
            main_module.main()

        resolve.assert_called_once_with(cli_file=None)
        app_cls.assert_called_once_with(journal_file=journal)
        app.run.assert_called_once_with()
