"""Parse a rulebook by sending each page's image to a vision model, which writes it as Markdown."""

import asyncio
import logging
import re
from pathlib import Path

from app.config import Settings
from app.ingestion.pdf_info import render_page
from app.llm.base import ImagePart, LLMProvider

logger = logging.getLogger(__name__)

# The contract for each page's Markdown, the same on every call. It's under OpenAI's 1,024-token
# minimum for prompt caching, so each page pays for it in full (about 450 tokens).
_INSTRUCTIONS = """\
You transcribe one page of a board game rulebook into Markdown. Follow these rules:

1. Copy the text verbatim: the same words, numbers and order. Never summarise, paraphrase,
correct or add text.
2. Use Markdown headings (#, ##, ###) only for real section titles, with levels that follow the
rulebook's structure, not just font size. Never turn part of a sentence into a heading.
3. Write captions, references such as "Illustration A" and the titles of boxes or callouts (such
as "Example" or "Important") as bold text, not as headings.
4. Write sidebars and boxed notes as blockquotes, in the section they belong to.
5. Read in the order a person would: each column top to bottom, columns left to right. Join a
sentence that a picture or a column break splits. The page may start or end in the middle of a
sentence: copy that part as it is, without completing it or leaving it out.
6. Write tables as Markdown tables.
7. Write out text inside pictures when it matters for play, such as a legend, a chart of odds, or
the components and how many there are (keep counts such as "x9"), as a list or table under a
bold label. Skip decorative text (logos, artwork lettering), card text that only illustrates a
rule, and labels that only name what a picture shows.
8. Leave out page numbers and running headers or footers.
9. Write an icon that stands for a game term (a resource, a card type, an action) as that term in
square brackets, such as [wood]. Leave out decorative icons and symbols.
10. Output only the Markdown, with no code fences and no comments."""


class TruncatedPageError(Exception):
    """Raised when a page's Markdown reached the output-token cap before it was finished."""


# A code fence around a whole reply, which rule 10 forbids but a model sometimes writes anyway.
_FENCED = re.compile(r"```[\w-]*\n(.*?)\n?```", re.DOTALL)


def _without_fence(text: str) -> str:
    fenced = _FENCED.fullmatch(text)
    return fenced[1].strip() if fenced else text


async def parse_pdf_to_markdown(
    path: Path, page_count: int, llm: LLMProvider, settings: Settings
) -> str:
    """Write a PDF as Markdown, one model call per page, each page after a `<!-- page N -->` line.

    Pages are sent one at a time, so a failure stops before the remaining pages are paid for.
    """
    blocks: list[str] = []
    input_tokens = output_tokens = 0
    for page in range(1, page_count + 1):
        png = await asyncio.to_thread(render_page, path, page, settings.parser_image_px)
        completion = await llm.complete(
            settings.parser_model,
            _INSTRUCTIONS,
            [ImagePart(png)],
            settings.parser_max_output_tokens,
            settings.parser_reasoning_effort,
        )
        if not completion.complete:
            raise TruncatedPageError(
                f"page {page}'s Markdown was cut off at {settings.parser_max_output_tokens} "
                "output tokens"
            )

        input_tokens += completion.usage.input_tokens
        output_tokens += completion.usage.output_tokens
        logger.info(
            "parsed page %d of %d: %d input and %d output tokens so far",
            page,
            page_count,
            input_tokens,
            output_tokens,
        )
        blocks.append(f"<!-- page {page} -->")
        if text := _without_fence(completion.text.strip()):
            blocks.append(text)

    return "\n\n".join(blocks) + "\n"
