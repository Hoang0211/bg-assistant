"""What every LLM provider takes and returns; this module imports no SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    # Only for the annotation: config.py imports ReasoningEffort from here.
    from app.config import Settings

ReasoningEffort = Literal["none", "low", "medium", "high"]


@dataclass(frozen=True)
class ImagePart:
    png: bytes


# A request's content, in the order the model reads it.
Part = str | ImagePart


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    reasoning_tokens: int


@dataclass(frozen=True)
class Completion:
    text: str
    complete: bool  # False when the output-token cap cut the answer off
    usage: Usage


@dataclass(frozen=True)
class StructuredCompletion[T: BaseModel]:
    value: T | None  # None when the reply was cut off or refused, so it has no object to give
    complete: bool
    usage: Usage


class LLMProvider(Protocol):
    async def complete(
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> Completion: ...

    async def complete_structured[T: BaseModel](
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> StructuredCompletion[T]:
        """A reply that the API guarantees matches the schema (OpenAI's structured outputs)."""
        ...


def create_llm_provider(settings: Settings) -> LLMProvider:
    """The provider the settings choose: OpenAI, or the fake one, which tests always get."""
    if settings.llm_provider == "fake":
        from app.llm.fake import FakeLLMProvider

        return FakeLLMProvider([])

    api_key = settings.openai_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY isn't set; add it to backend/.env")
    # Imported here so only code that calls OpenAI loads its SDK.
    from openai import AsyncOpenAI

    from app.llm.openai import OpenAIProvider

    client = AsyncOpenAI(
        api_key=api_key,
        max_retries=settings.llm_max_retries,
        timeout=settings.llm_timeout_seconds,
    )
    return OpenAIProvider(client)
