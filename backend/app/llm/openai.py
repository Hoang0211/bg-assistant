"""The LLM provider for OpenAI's Responses API."""

import base64

from openai import AsyncOpenAI
from openai.types.responses import Response, ResponseInputContentParam, ResponseInputParam
from pydantic import BaseModel, ValidationError

from app.llm.base import Completion, ImagePart, Part, ReasoningEffort, StructuredCompletion, Usage


def _content(parts: list[Part]) -> list[ResponseInputContentParam]:
    content: list[ResponseInputContentParam] = []
    for part in parts:
        if isinstance(part, ImagePart):
            url = "data:image/png;base64," + base64.b64encode(part.png).decode()
            content.append({"type": "input_image", "image_url": url, "detail": "high"})
        else:
            content.append({"type": "input_text", "text": part})
    return content


def _input(parts: list[Part]) -> ResponseInputParam:
    return [{"role": "user", "content": _content(parts)}]


def _usage(response: Response) -> Usage:
    usage = response.usage
    assert usage is not None  # the Responses API always reports usage on a finished response
    return Usage(
        input_tokens=usage.input_tokens,
        cached_tokens=usage.input_tokens_details.cached_tokens,
        output_tokens=usage.output_tokens,
        reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
    )


class OpenAIProvider:
    """Sends each request to OpenAI's Responses API through the given client."""

    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def complete(
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> Completion:
        response = await self._client.responses.create(
            model=model,
            instructions=instructions,
            input=_input(parts),
            reasoning={"effort": reasoning_effort},
            max_output_tokens=max_output_tokens,
        )
        return Completion(
            text=response.output_text,
            complete=response.status == "completed",
            usage=_usage(response),
        )

    async def complete_structured[T: BaseModel](
        self,
        model: str,
        instructions: str,
        parts: list[Part],
        schema: type[T],
        max_output_tokens: int,
        reasoning_effort: ReasoningEffort,
    ) -> StructuredCompletion[T]:
        try:
            response = await self._client.responses.parse(
                model=model,
                instructions=instructions,
                input=_input(parts),
                reasoning={"effort": reasoning_effort},
                max_output_tokens=max_output_tokens,
                text_format=schema,
            )
        except ValidationError:
            # A reply cut off mid-object can't be parsed, and the SDK raises before handing back
            # the response, so its usage is lost; it's rare, and logged by the caller.
            return StructuredCompletion(value=None, complete=False, usage=Usage(0, 0, 0, 0))
        return StructuredCompletion(
            value=response.output_parsed,  # None for a refusal
            complete=response.status == "completed",
            usage=_usage(response),
        )
