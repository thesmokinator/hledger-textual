"""Tests for the AI context builder."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from hledger_textual.ai.context_builder import ContextBuilder, _MAX_CONTEXT_CHARS
from hledger_textual.models import PeriodSummary


def _stub_summary(monkeypatch):
    """Stub load_period_summary with a basic summary."""
    monkeypatch.setattr(
        "hledger_textual.ai.context_builder.load_period_summary",
        lambda f, p: PeriodSummary(
            income=Decimal("1000"), expenses=Decimal("600"),
            commodity="EUR", investments=Decimal("0"),
        ),
    )


def _stub_register(monkeypatch, text=""):
    """Stub load_register_compact with the given text."""
    monkeypatch.setattr(
        "hledger_textual.ai.context_builder.load_register_compact",
        lambda f: text,
    )


class TestBuildChatContext:
    """Tests for ContextBuilder.build_chat_context."""

    def test_returns_system_and_user_tuple(self, monkeypatch):
        """build_chat_context returns a (system, user) string tuple."""
        _stub_summary(monkeypatch)
        _stub_register(monkeypatch, "2026-01-15 Grocery | expenses:food €40.80")

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, user = builder.build_chat_context("How am I doing?")

        assert isinstance(system, str)
        assert isinstance(user, str)

    def test_system_prompt_is_english(self, monkeypatch):
        """The system prompt is always in English."""
        _stub_summary(monkeypatch)
        _stub_register(monkeypatch)

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("test")

        assert "finance" in system.lower()
        assert "hledger" in system.lower()

    def test_system_prompt_mentions_journal(self, monkeypatch):
        """The system prompt tells the model it has the full journal."""
        _stub_summary(monkeypatch)
        _stub_register(monkeypatch)

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("test")

        assert "journal" in system.lower()

    def test_user_query_returned_as_is(self, monkeypatch):
        """The user prompt is the raw query (context is in system prompt)."""
        _stub_summary(monkeypatch)
        _stub_register(monkeypatch)

        builder = ContextBuilder(Path("/tmp/test.journal"))
        _, user = builder.build_chat_context("Where is my money going?")

        assert user == "Where is my money going?"

    def test_journal_transactions_in_system_prompt(self, monkeypatch):
        """Journal transactions appear in the system prompt."""
        _stub_summary(monkeypatch)
        journal_text = (
            "2026-01-15 Grocery shopping | expenses:food:groceries €40.80\n"
            "2026-01-16 Salary | assets:bank:checking €3000.00"
        )
        _stub_register(monkeypatch, journal_text)

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("Summary?")

        assert "Grocery shopping" in system
        assert "expenses:food:groceries" in system
        assert "€40.80" in system
        assert "Salary" in system

    def test_period_summary_in_system_prompt(self, monkeypatch):
        """Period summary data appears in the system prompt."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("2500"), expenses=Decimal("1800"),
                commodity="EUR", investments=Decimal("0"),
            ),
        )
        _stub_register(monkeypatch, "2026-01-15 Test | expenses:test €10")

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("Summary?")

        assert "2500" in system
        assert "1800" in system

    def test_context_truncation(self, monkeypatch):
        """Context is truncated when it exceeds the token budget."""
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: PeriodSummary(
                income=Decimal("100"), expenses=Decimal("50"),
                commodity="EUR", investments=Decimal("0"),
            ),
        )
        # Create a huge journal dump to exceed the budget
        huge_journal = "\n".join(
            f"2026-01-{i:02d} Transaction {i} | expenses:cat{i} €{i}.00"
            for i in range(1, 500)
        )
        _stub_register(monkeypatch, huge_journal)

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, _ = builder.build_chat_context("test")

        assert "[truncated]" in system

    def test_graceful_on_hledger_errors(self, monkeypatch):
        """build_chat_context still works when hledger calls fail."""
        from hledger_textual.hledger import HledgerError

        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_register_compact",
            lambda f: (_ for _ in ()).throw(HledgerError("fail")),
        )
        monkeypatch.setattr(
            "hledger_textual.ai.context_builder.load_period_summary",
            lambda f, p: (_ for _ in ()).throw(HledgerError("fail")),
        )

        builder = ContextBuilder(Path("/tmp/test.journal"))
        system, user = builder.build_chat_context("test")

        # Should still return valid prompts
        assert isinstance(system, str)
        assert user == "test"
