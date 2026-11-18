"""An LLM provider for tests: scripted replies, no API key, no network."""

from dataclasses import dataclass

from app.llm.base import Completion, Part, ReasoningEffort, Usage


@dataclass(frozen=True)
class Call:
    model: str
    instructions: str
    parts: list[Part]
    max_output_tokens: int
    reasoning_effort: ReasoningEffort


class FakeLLMProvider:
    """Returns the scripted replies in order and records each call, so tests can check them."""

    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls: list[Call] = []

    async def complete(
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> Completion:
        self.calls.append(Call(model, instructions, parts, max_output_tokens, reasoning_effort))
        if not self._replies:
            raise RuntimeError("FakeLLMProvider has no scripted reply left for this call")
        return Completion(text=self._replies.pop(0), complete=True, usage=Usage(0, 0, 0, 0))
