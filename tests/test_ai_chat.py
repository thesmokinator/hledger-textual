"""Tests for the AI chat modal screen."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Input, Static

from hledger_textual.screens.ai_chat import AiChatModal


class _FakeOllamaClient:
    """Test double for OllamaClient that doesn't import ollama SDK."""

    def __init__(self, tokens=None, error=None):
        self._tokens = tokens or []
        self._error = error

    def health_check(self) -> bool:
        return True

    def stream_chat(self, prompt, system, history=None):
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
        """Submitting an empty input does nothing — scroll area stays empty."""
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
            scroll = app.screen.query_one("#ai-scroll", VerticalScroll)
            assert len(scroll.children) == 0

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
        """Streamed tokens appear in the answer widget."""
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
            answers = app.screen.query(".ai-answer")
            assert len(answers) == 1
            assert "You look good!" in str(answers[0].renderable)

    async def test_error_handling_when_ollama_fails(self):
        """OllamaError during streaming shows error in the answer widget."""
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
            answers = app.screen.query(".ai-answer")
            assert len(answers) == 1
            assert "Error" in str(answers[0].renderable)

    async def test_question_appears_in_conversation(self):
        """Submitting a question mounts a question widget with the text."""
        client = _FakeOllamaClient(tokens=["reply"])
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
            inp.value = "What is my balance?"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)
            questions = app.screen.query(".ai-question")
            assert len(questions) == 1
            assert "What is my balance?" in str(questions[0].renderable)

    async def test_multiple_questions_show_history(self):
        """Submitting two questions shows both Q&A pairs in history."""
        client = _FakeOllamaClient(tokens=["first answer"])
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

            # First question
            inp.value = "Question one"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

            # Second question (new client tokens via monkey-patch)
            client._tokens = ["second answer"]
            inp.value = "Question two"
            await pilot.press("enter")
            await pilot.pause(delay=0.5)

            questions = app.screen.query(".ai-question")
            answers = app.screen.query(".ai-answer")
            assert len(questions) == 2
            assert len(answers) == 2
            assert "Question one" in str(questions[0].renderable)
            assert "Question two" in str(questions[1].renderable)
            assert "first answer" in str(answers[0].renderable)
            assert "second answer" in str(answers[1].renderable)
