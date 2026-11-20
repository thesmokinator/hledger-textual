"""Unit tests for the application entry point (85% push)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestTextualVersionGuard:
    """main() refuses to start on an unsupported Textual version."""

    def test_unsupported_version_exits_with_actionable_message(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Textual 7.x aborts with the required and installed versions."""
        from hledger_textual import __main__ as main_module

        monkeypatch.setattr("textual.__version__", "7.4.0")

        with pytest.raises(SystemExit) as exc_info:
            main_module._check_textual_version()

        assert exc_info.value.code == 1
        stderr = capsys.readouterr().err
        assert "Textual >= 8.0" in stderr
        assert "7.4.0" in stderr
        assert "upgrade" in stderr.lower()

    def test_supported_version_does_not_exit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Textual 8.x passes the guard silently."""
        from hledger_textual import __main__ as main_module

        monkeypatch.setattr("textual.__version__", "8.2.8")
        main_module._check_textual_version()



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
