"""Tests for the Ollama client wrapper."""

from __future__ import annotations

import pytest

from hledger_textual.ai.errors import OllamaError
from hledger_textual.ai.ollama_client import OllamaClient


class TestHealthCheck:
    """Tests for OllamaClient.health_check."""

    def test_returns_true_when_ollama_responds(self, monkeypatch):
        """health_check returns True when client.list() succeeds."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")
        monkeypatch.setattr(client._client, "list", lambda: {"models": []})
        assert client.health_check() is True

    def test_returns_false_on_connection_error(self, monkeypatch):
        """health_check returns False when client.list() raises."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        def _fail():
            raise ConnectionError("refused")

        monkeypatch.setattr(client._client, "list", _fail)
        assert client.health_check() is False


class TestListModels:
    """Tests for OllamaClient.list_models."""

    def test_returns_model_names(self, monkeypatch):
        """list_models returns installed model names."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        class _Model:
            def __init__(self, name):
                self.model = name

        class _Response:
            models = [_Model("phi4-mini"), _Model("llama3")]

        monkeypatch.setattr(client._client, "list", lambda: _Response())
        assert client.list_models() == ["phi4-mini", "llama3"]

    def test_returns_empty_list_on_error(self, monkeypatch):
        """list_models returns empty list on connection error."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        def _fail():
            raise ConnectionError("refused")

        monkeypatch.setattr(client._client, "list", _fail)
        assert client.list_models() == []


class TestStreamChat:
    """Tests for OllamaClient.stream_chat."""

    def test_yields_tokens(self, monkeypatch):
        """stream_chat yields content tokens from the model."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        chunks = [
            {"message": {"content": "Hello"}},
            {"message": {"content": " world"}},
            {"message": {"content": "!"}},
        ]

        def _fake_chat(model, messages, stream):
            assert model == "phi4-mini"
            assert stream is True
            return iter(chunks)

        monkeypatch.setattr(client._client, "chat", _fake_chat)

        tokens = list(client.stream_chat("Hi", "You are helpful."))
        assert tokens == ["Hello", " world", "!"]

    def test_skips_empty_content(self, monkeypatch):
        """stream_chat skips chunks with empty content."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        chunks = [
            {"message": {"content": "A"}},
            {"message": {"content": ""}},
            {"message": {}},
            {"message": {"content": "B"}},
        ]

        def _fake_chat(model, messages, stream):
            return iter(chunks)

        monkeypatch.setattr(client._client, "chat", _fake_chat)

        tokens = list(client.stream_chat("Hi", "sys"))
        assert tokens == ["A", "B"]

    def test_raises_ollama_error_on_response_error(self, monkeypatch):
        """stream_chat wraps ResponseError in OllamaError."""
        from ollama import ResponseError

        client = OllamaClient("http://localhost:11434", "phi4-mini")

        def _fail(model, messages, stream):
            raise ResponseError("model not found")

        monkeypatch.setattr(client._client, "chat", _fail)

        with pytest.raises(OllamaError, match="model not found"):
            list(client.stream_chat("Hi", "sys"))

    def test_raises_ollama_error_on_connection_failure(self, monkeypatch):
        """stream_chat wraps generic exceptions in OllamaError."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")

        def _fail(model, messages, stream):
            raise ConnectionError("refused")

        monkeypatch.setattr(client._client, "chat", _fail)

        with pytest.raises(OllamaError, match="connection error"):
            list(client.stream_chat("Hi", "sys"))

    def test_messages_structure(self, monkeypatch):
        """stream_chat sends system and user messages in correct order."""
        client = OllamaClient("http://localhost:11434", "phi4-mini")
        captured_messages = []

        def _fake_chat(model, messages, stream):
            captured_messages.extend(messages)
            return iter([])

        monkeypatch.setattr(client._client, "chat", _fake_chat)
        list(client.stream_chat("my question", "system instructions"))

        assert len(captured_messages) == 2
        assert captured_messages[0]["role"] == "system"
        assert captured_messages[0]["content"] == "system instructions"
        assert captured_messages[1]["role"] == "user"
        assert captured_messages[1]["content"] == "my question"
