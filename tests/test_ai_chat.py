"""Tests for the AI chat modal screen."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Static

from hledger_textual.screens.ai_chat import AiChatModal


class _FakeOllamaClient:
    """Test double for OllamaClient that doesn't import ollama SDK."""

    def __init__(self, tokens=None, error=None):
        self._tokens = tokens or []
        self._error = error

    def health_check(self) -> bool:
        return True

    def stream_chat(self, prompt, system):
        if self._error:
            raise self._error
        yield from self._tokens


def _make_error():
    """Create an OllamaError lazily to avoid importing ollama at module level."""
    from hledger_textual.ai.errors import OllamaError

    return OllamaError("model not found")


class _FakeContextBuilder:
    """Test double for ContextBuilder that doesn't call hledger."""

    def build_chat_context(self, user_query):
        return ("system prompt", f"context data\n\nMy question: {user_query}")


class TestAiChatModal:
    """Tests for the AiChatModal screen."""

    async def test_modal_mounts_without_error(self):
        """Modal mounts and shows the input widget."""
        client = _FakeOllamaClient()
        context = _FakeContextBuilder()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(AiChatModal(client, context))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#ai-input", Input)
            assert inp is not None

    async def test_escape_dismisses_modal(self):
        """Pressing Escape dismisses the modal."""
        client = _FakeOllamaClient()
        context = _FakeContextBuilder()
        dismissed = []

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(
                    AiChatModal(client, context),
                    callback=lambda r: dismissed.append(r),
                )

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert dismissed == [None]

    async def test_empty_input_does_not_trigger_query(self):
        """Submitting an empty input does nothing."""
        client = _FakeOllamaClient()
        context = _FakeContextBuilder()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(AiChatModal(client, context))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            response = app.screen.query_one("#ai-response", Static)
            assert str(response.renderable) == ""

    async def test_input_submission_clears_input(self):
        """Typing a question and pressing Enter clears the input field."""
        client = _FakeOllamaClient(tokens=["ok"])
        context = _FakeContextBuilder()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(AiChatModal(client, context))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#ai-input", Input)
            inp.value = "How am I doing?"
            await pilot.press("enter")
            await pilot.pause()
            assert inp.value == ""

    async def test_streaming_response_updates_static(self):
        """Streamed tokens appear in the response widget."""
        client = _FakeOllamaClient(tokens=["You", " look", " good!"])
        context = _FakeContextBuilder()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(AiChatModal(client, context))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#ai-input")
            inp.value = "How am I doing?"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            response = app.screen.query_one("#ai-response", Static)
            assert "You look good!" in str(response.renderable)

    async def test_error_handling_when_ollama_fails(self):
        """OllamaError during streaming shows error in the response area."""
        client = _FakeOllamaClient(error=_make_error())
        context = _FakeContextBuilder()

        class TestApp(App):
            def compose(self) -> ComposeResult:
                yield Static("base")

            def on_mount(self) -> None:
                self.push_screen(AiChatModal(client, context))

        app = TestApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            inp = app.screen.query_one("#ai-input")
            inp.value = "test"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            response = app.screen.query_one("#ai-response", Static)
            assert "Error" in str(response.renderable)
