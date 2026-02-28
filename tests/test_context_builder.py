"""Tests for the AI context builder."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from hledger_textual.ai.context_builder import ContextBuilder, _MAX_CONTEXT_CHARS
from hledger_textual.models import PeriodSummary


class TestBuildChatContext:
    """Tests for ContextBuilder.build_chat_context."""

    def test_returns_system_and_user_tuple(self, monkeypatch):
        """build_chat_context returns a (system, user) string tuple."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("1000"), expenses=Decimal("600"),
                commodity="EUR", investments=Decimal("0"),
            ),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: ["assets:bank", "expenses:food"],
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: [("expenses:food", Decimal("300"), "EUR")],
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, user = builder.build_chat_context("How am I doing?")

        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_english(self, monkeypatch):
        """The system prompt is always in English."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("0"), expenses=Decimal("0"),
                commodity="", investments=Decimal("0"),
            ),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: [],
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: [],
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("test")

        assert "finance" in system.lower()
        assert "hledger" in system.lower()

    def test_user_query_included_in_prompt(self, monkeypatch):
        """The user's question appears in the user prompt."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("0"), expenses=Decimal("0"),
                commodity="", investments=Decimal("0"),
            ),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: [],
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: [],
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        _, user = builder.build_chat_context("Where is my money going?")

        assert "Where is my money going?" in user

    def test_hledger_data_injected(self, monkeypatch):
        """Period summary and account data appear in the user prompt."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("2500"), expenses=Decimal("1800"),
                commodity="EUR", investments=Decimal("0"),
            ),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: ["assets:bank:checking", "expenses:groceries"],
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: [
                ("expenses:groceries", Decimal("500"), "EUR"),
                ("expenses:rent", Decimal("1000"), "EUR"),
            ],
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        _, user = builder.build_chat_context("Summary?")

        assert "2500" in user
        assert "1800" in user
        assert "assets:bank:checking" in user
        assert "expenses:groceries" in user
        assert "expenses:rent" in user

    def test_context_truncation(self, monkeypatch):
        """Context is truncated when it exceeds the token budget."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("100"), expenses=Decimal("50"),
                commodity="EUR", investments=Decimal("0"),
            ),
        )
        # Create a huge account list to exceed the budget
        huge_accounts = [f"account:very:long:name:{i}" for i in range(2000)]
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: huge_accounts,
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: [],
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        _, user = builder.build_chat_context("test")

        assert "[truncated]" in user

    def test_graceful_on_hledger_errors(self, monkeypatch):
        """build_chat_context still works when hledger calls fail."""
        from hledger_textual.hledger import HledgerError

        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: (_ for _ in ()).throw(HledgerError("fail")),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_accounts",
            lambda f: (_ for _ in ()).throw(HledgerError("fail")),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_expense_breakdown",
            lambda f, p: (_ for _ in ()).throw(HledgerError("fail")),
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, user = builder.build_chat_context("test")

        # Should still return valid prompts
        assert isinstance(system, str)
        assert "test" in user
