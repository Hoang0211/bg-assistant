from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai import AsyncOpenAI
from pydantic import BaseModel, SecretStr, ValidationError

from app.config import Settings
from app.llm.base import (
    Completion,
    ImagePart,
    Part,
    StructuredCompletion,
    Usage,
    create_llm_provider,
)
from app.llm.fake import Call, FakeLLMProvider
from app.llm.openai import OpenAIProvider


class _Reply(BaseModel):
    answer: str


class _StubResponses:
    """Stands in for the OpenAI client's responses: records each request, returns one response.

    With `error`, a structured request raises it instead, as the SDK does for a reply cut off
    mid-object.
    """

    def __init__(self, response: SimpleNamespace, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.requests: list[dict[str, Any]] = []

    async def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return self.response

    async def parse(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _response(text: str, status: str, parsed: BaseModel | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        output_text=text,
        output_parsed=parsed,
        status=status,
        usage=SimpleNamespace(
            input_tokens=3000,
            input_tokens_details=SimpleNamespace(cached_tokens=1000),
            output_tokens=700,
            output_tokens_details=SimpleNamespace(reasoning_tokens=40),
        ),
    )


def _openai_provider(
    response: SimpleNamespace, error: Exception | None = None
) -> tuple[OpenAIProvider, _StubResponses]:
    responses = _StubResponses(response, error)
    return OpenAIProvider(cast(AsyncOpenAI, SimpleNamespace(responses=responses))), responses


def test_create_llm_provider_returns_the_fake_one_when_set() -> None:
    assert isinstance(create_llm_provider(Settings(llm_provider="fake")), FakeLLMProvider)


def test_create_llm_provider_returns_openai_with_a_key() -> None:
    settings = Settings(llm_provider="openai", openai_api_key=SecretStr("sk-test"))

    assert isinstance(create_llm_provider(settings), OpenAIProvider)


def test_create_llm_provider_gives_the_openai_client_the_timeout_and_retries() -> None:
    settings = Settings(
        llm_provider="openai",
        openai_api_key=SecretStr("sk-test"),
        llm_timeout_seconds=30,
        llm_max_retries=5,
    )

    provider = create_llm_provider(settings)

    assert isinstance(provider, OpenAIProvider)
    assert (provider._client.max_retries, provider._client.timeout) == (5, 30)


def test_create_llm_provider_refuses_openai_without_a_key() -> None:
    settings = Settings(llm_provider="openai", openai_api_key=SecretStr(""))

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        create_llm_provider(settings)


async def test_fake_llm_provider_returns_the_replies_in_order_and_records_each_call() -> None:
    provider = FakeLLMProvider(["first", "second"])
    image = ImagePart(b"png")

    first = await provider.complete("model", "Copy the page.", [image, "Page 1."], 100, "low")
    second = await provider.complete("model", "Copy the page.", ["Page 2."], 100, "low")

    assert [first.text, second.text] == ["first", "second"]
    assert provider.calls == [
        Call("model", "Copy the page.", [image, "Page 1."], 100, "low"),
        Call("model", "Copy the page.", ["Page 2."], 100, "low"),
    ]


async def test_fake_llm_provider_returns_a_scripted_completion_as_it_is() -> None:
    cut_off = Completion("# Setup", complete=False, usage=Usage(3000, 0, 4000, 0))

    assert await FakeLLMProvider([cut_off]).complete("model", "", [], 4000, "low") == cut_off


async def test_fake_llm_provider_raises_when_no_reply_is_left() -> None:
    with pytest.raises(RuntimeError, match="no scripted reply"):
        await FakeLLMProvider([]).complete("model", "", [], 100, "low")


async def test_fake_llm_provider_refuses_an_object_as_a_text_reply() -> None:
    with pytest.raises(TypeError, match="isn't text"):
        await FakeLLMProvider([_Reply(answer="5")]).complete("model", "", [], 100, "low")


async def test_fake_llm_provider_returns_a_scripted_object_and_records_its_schema() -> None:
    provider = FakeLLMProvider([_Reply(answer="5")])

    completion = await provider.complete_structured("model", "Grade.", ["Q"], _Reply, 50, "none")

    assert completion == StructuredCompletion(_Reply(answer="5"), True, Usage(0, 0, 0, 0))
    assert provider.calls == [Call("model", "Grade.", ["Q"], 50, "none", _Reply)]


async def test_fake_llm_provider_returns_a_scripted_structured_completion_as_it_is() -> None:
    cut_off = StructuredCompletion[_Reply](None, complete=False, usage=Usage(40, 0, 50, 50))

    provider = FakeLLMProvider([cut_off])

    assert await provider.complete_structured("model", "", [], _Reply, 50, "low") == cut_off


async def test_fake_llm_provider_refuses_a_reply_of_another_schema() -> None:
    with pytest.raises(TypeError, match="isn't a _Reply"):
        await FakeLLMProvider(["5"]).complete_structured("model", "", [], _Reply, 50, "low")


async def test_openai_provider_sends_the_parts_in_order_with_the_limits() -> None:
    provider, responses = _openai_provider(_response("# Setup", "completed"))
    parts: list[Part] = ["Before.", ImagePart(b"png"), "After."]

    await provider.complete("gpt-test", "Copy the page.", parts, 4000, "low")

    assert responses.requests == [
        {
            "model": "gpt-test",
            "instructions": "Copy the page.",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Before."},
                        {
                            "type": "input_image",
                            "image_url": "data:image/png;base64,cG5n",  # b"png" in base64
                            "detail": "high",
                        },
                        {"type": "input_text", "text": "After."},
                    ],
                }
            ],
            "reasoning": {"effort": "low"},
            "max_output_tokens": 4000,
        }
    ]


@pytest.mark.parametrize(("status", "complete"), [("completed", True), ("incomplete", False)])
async def test_openai_provider_returns_the_text_status_and_usage(
    status: str, complete: bool
) -> None:
    provider, _ = _openai_provider(_response("# Setup", status))

    completion = await provider.complete("gpt-test", "", [], 4000, "low")

    assert completion == Completion("# Setup", complete, Usage(3000, 1000, 700, 40))


async def test_openai_provider_asks_for_a_structured_reply_in_the_schema() -> None:
    provider, responses = _openai_provider(_response("", "completed", _Reply(answer="5")))

    await provider.complete_structured("gpt-test", "Grade.", ["Q"], _Reply, 800, "low")

    assert responses.requests == [
        {
            "model": "gpt-test",
            "instructions": "Grade.",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": "Q"}]}],
            "reasoning": {"effort": "low"},
            "max_output_tokens": 800,
            "text_format": _Reply,
        }
    ]


@pytest.mark.parametrize("parsed", [_Reply(answer="5"), None], ids=["parsed", "refused"])
async def test_openai_provider_returns_the_parsed_object_and_usage(parsed: _Reply | None) -> None:
    provider, _ = _openai_provider(_response("", "completed", parsed))

    completion = await provider.complete_structured("gpt-test", "", [], _Reply, 800, "low")

    assert completion == StructuredCompletion(parsed, True, Usage(3000, 1000, 700, 40))


async def test_openai_provider_returns_no_object_for_a_reply_cut_off_mid_object() -> None:
    try:
        _Reply.model_validate_json('{"answer": "5')
    except ValidationError as error:
        cut_off = error
    provider, _ = _openai_provider(_response("", "incomplete"), cut_off)

    completion = await provider.complete_structured("gpt-test", "", [], _Reply, 800, "low")

    assert completion == StructuredCompletion(None, False, Usage(0, 0, 0, 0))
