"""Ollama LLM client wrapper.

All methods are synchronous and intended to be called from
``@work(thread=True)`` workers so they don't block the event loop.
"""

from __future__ import annotations

from typing import Iterator

from ollama import Client, ResponseError

from hledger_textual.ai.errors import OllamaError


class OllamaClient:
    """Thin wrapper around the ``ollama`` Python SDK.

    Args:
        endpoint: Ollama HTTP endpoint (e.g. ``http://localhost:11434``).
        model: Model name to use for chat completions (e.g. ``phi4-mini``).
    """

    def __init__(self, endpoint: str, model: str, *, think: bool = False) -> None:
        self._client = Client(host=endpoint)
        self._model = model
        self._think = think

    def health_check(self) -> bool:
        """Return ``True`` if Ollama is reachable, ``False`` otherwise."""
        try:
            self._client.list()
            return True
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """Return installed model names, or empty list on error.

        Each model is included both with its full tag (e.g. ``phi4-mini:latest``)
        and without (``phi4-mini``), so callers can match either form.
        """
        try:
            response = self._client.list()
            names: set[str] = set()
            for m in response.models:
                names.add(m.model)
                base = m.model.split(":")[0]
                if base != m.model:
                    names.add(base)
            return sorted(names)
        except Exception:
            return []

    def stream_chat(
        self,
        prompt: str,
        system: str,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Stream a chat completion, yielding content tokens.

        Args:
            prompt: The user message.
            system: The system message providing context.
            history: Optional list of previous ``{"role": ..., "content": ...}``
                messages to maintain conversation context.

        Yields:
            Content delta strings as they arrive from the model.

        Raises:
            OllamaError: On connection or model errors.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        try:
            stream = self._client.chat(
                model=self._model,
                messages=messages,
                stream=True,
                think=self._think,
            )
            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
        except ResponseError as exc:
            raise OllamaError(str(exc)) from exc
        except Exception as exc:
            raise OllamaError(f"Ollama connection error: {exc}") from exc
