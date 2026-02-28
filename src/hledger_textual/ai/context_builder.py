"""Prompt assembler for AI chat.

Gathers structured hledger data and composes system/user prompts
that stay within the model's token budget.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from hledger_textual.hledger import (
    HledgerError,
    load_period_summary,
    load_register_compact,
)

_SYSTEM_PROMPT = """\
You are a helpful personal finance assistant embedded in hledger-textual, \
a terminal UI for the hledger accounting tool.

You have access to the user's full journal (every transaction with date, \
description, accounts, and amounts). Use it to answer specific questions \
about individual transactions, spending patterns, or totals.

Rules:
- NEVER perform arithmetic, additions, subtractions, or compute totals yourself. \
You WILL get them wrong. All numbers are provided by hledger and are authoritative. \
If the user asks for a sum or total that is not already in the data, say \
"I can only report numbers from hledger, I cannot compute totals myself."
- Interpret, explain, and summarise the data you are given.
- IMPORTANT: You MUST reply in the SAME language the user writes in. \
If the user writes in Italian, reply in Italian. \
If the user writes in English, reply in English. Match their language exactly.
- Be concise — the response is displayed in a small terminal window.
- When referencing accounts, use their full hledger names.
"""

# Rough token budget for the user prompt context block.
_MAX_CONTEXT_CHARS = 16_000  # ~5.3K tokens at ~3 chars/token


class ContextBuilder:
    """Assembles system and user prompts from hledger data.

    Args:
        journal_file: Path to the hledger journal file.
    """

    def __init__(self, journal_file: Path) -> None:
        self._journal_file = journal_file

    def build_chat_context(self, user_query: str) -> tuple[str, str]:
        """Build ``(system_prompt, user_prompt)`` for the LLM.

        The user prompt includes a context block with the full condensed
        journal (one line per transaction) and the current month's summary,
        followed by the user's question.

        Args:
            user_query: The question typed by the user.

        Returns:
            A ``(system, user)`` tuple of prompt strings.
        """
        period = datetime.date.today().strftime("%Y-%m")
        context_parts: list[str] = []

        # Condensed journal transactions
        try:
            journal_dump = load_register_compact(self._journal_file)
            if journal_dump:
                context_parts.append(
                    f"Journal transactions:\n{journal_dump}"
                )
        except HledgerError:
            pass

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

        context_block = "\n\n".join(context_parts)

        # Truncate if context exceeds the budget
        if len(context_block) > _MAX_CONTEXT_CHARS:
            context_block = context_block[:_MAX_CONTEXT_CHARS] + "\n[truncated]"

        system_with_data = (
            f"{_SYSTEM_PROMPT}\n\n"
            f"Here is the user's current financial data:\n\n"
            f"{context_block}"
        )

        return system_with_data, user_query
