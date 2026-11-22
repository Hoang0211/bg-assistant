"""An LLM provider for tests: scripted replies, no API key, no network."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from pydantic import BaseModel

from app.llm.base import Completion, Part, ReasoningEffort, StructuredCompletion, Usage

# A scripted reply: a finished completion's text or object, or a whole completion as it is.
Reply = str | Completion | BaseModel | StructuredCompletion[Any]


@dataclass(frozen=True)
class Call:
    model: str
    instructions: str
    parts: list[Part]
    max_output_tokens: int
    reasoning_effort: ReasoningEffort
    schema: type[BaseModel] | None = None  # set for a structured call


class FakeLLMProvider:
    """Returns the scripted replies in order and records each call, so tests can check them.

    `complete` takes text or a Completion; `complete_structured` takes an object of the schema
    asked for, or a StructuredCompletion. Each is returned as a finished reply, or as it is.
    """

    def __init__(self, replies: Sequence[Reply]) -> None:
        self._replies = list(replies)
        self.calls: list[Call] = []

    def _next(self) -> Reply:
        if not self._replies:
            raise RuntimeError("FakeLLMProvider has no scripted reply left for this call")
        return self._replies.pop(0)

    async def complete(
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> Completion:
        self.calls.append(Call(model, instructions, parts, max_output_tokens, reasoning_effort))
        reply = self._next()
        if isinstance(reply, Completion):
            return reply
        if not isinstance(reply, str):
            raise TypeError(f"the scripted reply for complete() isn't text: {reply!r}")
        return Completion(text=reply, complete=True, usage=Usage(0, 0, 0, 0))

    async def complete_structured[T: BaseModel](
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> StructuredCompletion[T]:
        self.calls.append(
            Call(model, instructions, parts, max_output_tokens, reasoning_effort, schema)
        )
        reply = self._next()
        if isinstance(reply, StructuredCompletion):
            return cast(StructuredCompletion[T], reply)
        if not isinstance(reply, schema):
            raise TypeError(f"the scripted reply isn't a {schema.__name__}: {reply!r}")
        return StructuredCompletion(value=reply, complete=True, usage=Usage(0, 0, 0, 0))
