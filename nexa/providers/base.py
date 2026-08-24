"""Provider abstraction. All provider-specific code lives behind this."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class ChatRequest:
    model: str
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ChatResponse:
    content: str
    model: str
    finish_reason: str | None = None
    usage: Usage | None = None


@dataclass
class ModelInfo:
    id: str
    owned_by: str = "provider"
    context_window: int | None = None


class AIProvider(abc.ABC):
    """Contract every AI provider must satisfy."""

    name: str = "abstract"

    @abc.abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse: ...

    @abc.abstractmethod
    def stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        """Yield OpenAI-compatible chunk dicts; final chunk may carry usage."""
        ...

    @abc.abstractmethod
    async def list_models(self) -> list[ModelInfo]: ...

    @abc.abstractmethod
    async def health(self) -> bool: ...
