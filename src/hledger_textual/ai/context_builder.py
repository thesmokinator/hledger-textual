"""Prompt assembler for AI chat.

Gathers structured hledger data and composes system/user prompts
that stay within the model's token budget.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from hledger_textual.hledger import (
    HledgerError,
    load_accounts,
    load_expense_breakdown,
    load_period_summary,
)

_SYSTEM_PROMPT = """\
You are a helpful personal finance assistant embedded in hledger-textual, \
a terminal UI for the hledger accounting tool.

Rules:
- NEVER perform arithmetic or compute totals yourself. \
All numbers are provided by hledger and are authoritative.
- Interpret, explain, and summarise the data you are given.
- Answer in the same language the user writes in.
- Be concise — the response is displayed in a small terminal window.
- When referencing accounts, use their full hledger names.
"""

# Rough token budget for the user prompt context block.
_MAX_CONTEXT_CHARS = 12_000  # ~4K tokens at ~3 chars/token


class ContextBuilder:
    """Assembles system and user prompts from hledger data.

    Args:
        journal_file: Path to the hledger journal file.
    """

    def __init__(self, journal_file: Path) -> None:
        self._journal_file = journal_file

    def build_chat_context(self, user_query: str) -> tuple[str, str]:
        """Build ``(system_prompt, user_prompt)`` for the LLM.

        The user prompt includes a context block with the current month's
        summary, account list, and expense breakdown, followed by the
        user's question.

        Args:
            user_query: The question typed by the user.

        Returns:
            A ``(system, user)`` tuple of prompt strings.
        """
        period = datetime.date.today().strftime("%Y-%m")
        context_parts: list[str] = []

        # Period summary (income / expenses / net)
        try:
            summary = load_period_summary(self._journal_file, period)
            context_parts.append(
                f"Current month ({period}) summary:\n"
                f"  Income:   {summary.commodity}{summary.income}\n"
                f"  Expenses: {summary.commodity}{summary.expenses}\n"
                f"  Net:      {summary.commodity}{summary.income - summary.expenses}"
            )
        except HledgerError:
            pass

        # Account list
        try:
            accounts = load_accounts(self._journal_file)
            acct_block = "\n".join(f"  {a}" for a in accounts)
            context_parts.append(f"Accounts:\n{acct_block}")
        except HledgerError:
            pass

        # Expense breakdown
        try:
            breakdown = load_expense_breakdown(self._journal_file, period)
            if breakdown:
                lines = [
                    f"  {acct}: {com}{qty}" for acct, qty, com in breakdown
                ]
                context_parts.append(
                    f"Expense breakdown ({period}):\n" + "\n".join(lines)
                )
        except HledgerError:
            pass

        context_block = "\n\n".join(context_parts)

        # Truncate if context exceeds the budget
        if len(context_block) > _MAX_CONTEXT_CHARS:
            context_block = context_block[:_MAX_CONTEXT_CHARS] + "\n[truncated]"

        user_prompt = (
            f"Here is my current financial data:\n\n"
            f"{context_block}\n\n"
            f"My question: {user_query}"
        )

        return _SYSTEM_PROMPT, user_prompt
