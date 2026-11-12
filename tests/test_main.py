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


class TestMainGuard:
    """The __main__ guard delegates to main() (85% push)."""

    def test_module_main_guard_calls_main(self, tmp_path, monkeypatch):
        """Executing the module as __main__ runs the app once."""
        import runpy
        import sys

        from hledger_textual.app import HledgerTuiApp

        journal = tmp_path / "test.journal"
        journal.write_text("", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["hledger-textual", "-f", str(journal)])
        with patch.object(HledgerTuiApp, "run") as run_mock:
            runpy.run_module(
                "hledger_textual.__main__", run_name="__main__", alter_sys=True
            )
        run_mock.assert_called_once_with()
