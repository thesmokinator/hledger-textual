"""AI chat modal screen.

Provides a simple single-turn Q&A interface: the user types a question,
the response streams in token-by-token from Ollama.
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

    def compose(self) -> ComposeResult:
        """Create the modal layout."""
        with Vertical(id="ai-dialog"):
            yield Label("AI Chat", id="ai-title")
            with VerticalScroll(id="ai-scroll"):
                yield Static("", id="ai-response")
            yield Input(placeholder="Ask a question...", id="ai-input")

    def on_mount(self) -> None:
        """Focus the input on mount."""
        self.query_one("#ai-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in the input field — start streaming response."""
        query = event.value.strip()
        if not query:
            return
        event.input.value = ""
        self.query_one("#ai-response", Static).update("Thinking...")
        self._run_query(query)

    @work(thread=True, exclusive=True, group="ai-chat")
    def _run_query(self, query: str) -> None:
        """Build context and stream the LLM response."""
        from hledger_textual.ai.errors import OllamaError

        try:
            system, user = self._ctx_builder.build_chat_context(query)
            response_text = ""
            for token in self._ollama.stream_chat(user, system):
                response_text += token
                text = response_text
                self.app.call_from_thread(
                    self.query_one("#ai-response", Static).update, text
                )
        except OllamaError as exc:
            self.app.call_from_thread(
                self.query_one("#ai-response", Static).update,
                f"Error: {exc}",
            )
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#ai-response", Static).update,
                f"Unexpected error: {exc}",
            )

    def action_cancel(self) -> None:
        """Dismiss the modal."""
        self.dismiss(None)
