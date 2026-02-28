"""AI chat modal screen.

Provides a conversation-style Q&A interface: the user types questions,
and responses stream in token-by-token from Ollama. Both questions and
answers remain visible in a scrollable conversation history.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

if TYPE_CHECKING:
    from hledger_textual.ai.context_builder import ContextBuilder
    from hledger_textual.ai.ollama_client import OllamaClient


class AiChatModal(ModalScreen[None]):
    """Modal screen for AI-assisted financial Q&A.

    Args:
        ollama_client: A configured :class:`OllamaClient` instance.
        context_builder: A configured :class:`ContextBuilder` instance.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        ollama_client: OllamaClient,
        context_builder: ContextBuilder,
    ) -> None:
        super().__init__()
        self._ollama = ollama_client
        self._ctx_builder = context_builder
        self._current_response: Static | None = None
        self._history: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        with Vertical(id="ai-dialog"):
            yield Label("AI Chat", id="ai-title")
            yield VerticalScroll(id="ai-scroll")
            yield Input(placeholder="Ask a question...", id="ai-input")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#ai-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the input field — append question and start streaming."""
        query = event.value.strip()
        if not query:
            return
        event.input.value = ""

        scroll = self.query_one("#ai-scroll", VerticalScroll)

        question = Static(f"> {query}", classes="ai-question")
        scroll.mount(question)

        response = Static("Thinking...", classes="ai-answer")
        scroll.mount(response)
        self._current_response = response

        scroll.scroll_end(animate=False)
        self._run_query(query)

    @work(thread=True, exclusive=True, group="ai-chat")
    def _run_query(self, query: str) -> None:
        """Build context and stream the LLM response."""
        from hledger_textual.ai.errors import OllamaError

        try:
            system, user = self._ctx_builder.build_chat_context(query)
            response_text = ""
            for token in self._ollama.stream_chat(user, system, self._history):
                response_text += token
                text = response_text
                self.app.call_from_thread(self._current_response.update, text)
                self.app.call_from_thread(
                    self.query_one("#ai-scroll", VerticalScroll).scroll_end,
                    animate=False,
                )
            self._history.append({"role": "user", "content": user})
            self._history.append({"role": "assistant", "content": response_text})
        except OllamaError as exc:
            self.app.call_from_thread(
                self._current_response.update,
                f"Error: {exc}",
            )
        except Exception as exc:
            self.app.call_from_thread(
                self._current_response.update,
                f"Unexpected error: {exc}",
            )

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)
