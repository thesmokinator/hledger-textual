"""Unit tests for the application entry point (85% push)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hledger_textual.__main__ import _resolve_initial_period
from hledger_textual.period import year_selection


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
        args.period = None
        args.begin = None
        args.end = None
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
        app_cls.assert_called_once_with(
            journal_file=journal, initial_period=None
        )
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


class TestResolveInitialPeriod:
    """Startup period resolution from flags and config (issue #268)."""

    def _args(self, period=None, begin=None, end=None, file=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            file=file, period=period, begin=begin, end=end
        )

    def _journal(self, tmp_path: Path) -> Path:
        journal = tmp_path / "journal.journal"
        journal.write_text(
            "2024-03-10 * A\n    expenses:food  10.00\n    assets:checking\n"
        )
        return journal

    def test_period_flag(self, tmp_path: Path):
        """-p 2024 resolves to the whole year."""
        selection = _resolve_initial_period(
            self._args(period="2024"), self._journal(tmp_path)
        )
        assert selection == year_selection(2024)

    def test_begin_end_flags(self, tmp_path: Path):
        """-b/-e build an exclusive-end range."""
        selection = _resolve_initial_period(
            self._args(begin="2024-01-01", end="2024-06-30"),
            self._journal(tmp_path),
        )
        assert selection.query() == "date:2024-01-01..2024-06-29"

    def test_invalid_period_flag_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            _resolve_initial_period(
                self._args(period="banana"), self._journal(tmp_path)
            )

    def test_config_default_used_when_no_flags(
        self, tmp_path: Path, monkeypatch
    ):
        """default_period from config applies when no CLI flags are given."""
        journal = self._journal(tmp_path)
        monkeypatch.setattr(
            "hledger_textual.__main__.load_default_period", lambda: "2024"
        )
        selection = _resolve_initial_period(self._args(), journal)
        assert selection == year_selection(2024)

    def test_invalid_config_default_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "hledger_textual.__main__.load_default_period", lambda: "banana"
        )
        with pytest.raises(ValueError):
            _resolve_initial_period(self._args(), self._journal(tmp_path))

    def test_hledger_rejection_raises(self, tmp_path: Path, monkeypatch):
        """A period hledger cannot parse aborts with a clear error."""
        from hledger_textual.hledger import HledgerError

        def _fail(*args, **kwargs):
            raise HledgerError("bad period")

        monkeypatch.setattr("hledger_textual.hledger.run_hledger", _fail)
        with pytest.raises(ValueError):
            _resolve_initial_period(
                self._args(period="2024"), self._journal(tmp_path)
            )

    def test_main_exits_nonzero_on_invalid_period(
        self, tmp_path: Path, monkeypatch, capsys
    ):
        """An invalid period exits with status 1 and an actionable message."""
        from hledger_textual import __main__ as main_module

        journal = self._journal(tmp_path)
        args = self._args(period="banana")
        monkeypatch.setattr(main_module, "parse_args", lambda: args)
        monkeypatch.setattr(
            main_module, "resolve_journal_file", lambda cli_file: journal
        )
        with pytest.raises(SystemExit) as excinfo:
            main_module.main()
        assert excinfo.value.code == 1
        assert "Invalid period" in capsys.readouterr().err
