# Architecture

Board Game Assistant is a local-only web app that answers questions about the rules of your board games, using the rulebooks you upload. This document describes its design: what it does, how it's built, and why. It changes when a design decision changes; progress is tracked in `CLAUDE.md`, not here.

## What it does

1. **Add a game.** Fill in the game's details (name, description, player count, play time, age, genres, publisher, year, and whether it's an expansion of another game) and attach one or more rulebook PDFs. Each rulebook is parsed and indexed in the background.
2. **Manage games and rulebooks.** List, view, edit and delete the games in your library. A game can have several rulebooks (for example a rulebook and a reference guide), or none yet. Rulebooks are added, renamed, moved to another game and deleted on their own, and editing a game never touches its rulebooks.
3. **Chat.** Ask for recommendations from your library ("a co-op game for 5 players under an hour"), answered with a database query. Or ask rules questions ("can I trade on someone else's turn?"), answered from the rulebook with page citations. When the game or expansion isn't clear, the assistant asks before answering. When the rulebook doesn't cover a question, it offers to search the web, and labels those answers as web results.

There is no authentication: it's a single-user app that runs on one machine.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript | Server Components render the game list and detail pages; Server Actions handle create, edit and delete with `revalidatePath`; Client Components handle upload, polling and chat |
| UI | Tailwind CSS v4 + shadcn/ui (Base UI, Lucide icons, Geist font) | Accessible components that live in the repo and can be edited |
| Component workshop | Storybook (`@storybook/nextjs-vite`) with the MSW, a11y and Vitest addons | Every UI state (loading, error, upload results, streaming, clarification) can be built and tested in isolation |
| Client data | TanStack Query (Client Components only) | Rulebook uploads, ingestion status polling, conversation history |
| Forms | react-hook-form + zod | The game form, validated before it's sent |
| PDF viewer | react-pdf, loaded with `next/dynamic` and `ssr: false` | Shows the whole rulebook, and a citation opens it at that page. pdf.js fetches the file with HTTP range requests, so a page shows without downloading the whole PDF first |
| Chat streaming | The browser connects directly to FastAPI's Server-Sent Events (CORS allows `localhost:3000`) | Avoids Next.js rewrites buffering the stream |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI schema, called through `openapi-fetch` | End-to-end type safety; CI fails if the committed types are out of date |
| Backend | Python 3.12 (pinned with uv) + FastAPI + Pydantic v2 | 3.12 is supported by every ML dependency; uv installs it and locks every package |
| Database | PostgreSQL 16 + pgvector + pg_trgm (Docker) | One store for relational data, vectors, full-text search and fuzzy name matching |
| ORM / migrations | SQLAlchemy 2.0 (async, psycopg 3) + Alembic | psycopg 3 is also the driver the LangGraph checkpointer uses, so there's one Postgres driver. The checkpointer creates its own tables with `.setup()` at startup, outside Alembic |
| PDF parsing | A vision model (`parser_model`) writes each page as Markdown for ingestion; PyMuPDF checks uploads and renders pages | Rulebooks vary a lot in fonts, columns, sidebars and tables, and print rules inside pictures (odds charts, legends). A vision model reads a page as a person does: reading order, real heading levels, tables, and the text in pictures, for about $0.006 a page, once per rulebook, since the Markdown is stored. Docling, a local layout model, was the first parser; milestone 5b compared the two and kept this one. PyMuPDF opens an upload in milliseconds to check it's a readable PDF, reads its page count, and renders each page as an image for the model |
| Embeddings | `BAAI/bge-base-en-v1.5` via sentence-transformers (768 dimensions; GPU, or CPU as a fallback) | Free, local and offline. Its 512-token input limit caps chunks at about 450 tokens (counted with the BGE tokenizer). Queries get the BGE query prefix and chunks don't; vectors are normalised and compared by cosine similarity |
| LLM | OpenAI (official `openai` SDK) behind a small `LLMProvider` interface with two implementations, `openai` and `fake` | Structured outputs with Pydantic models, function calling and streaming. Model names are defaults in `config.py`: `chat_model` (rules agent, recommendation answers, the eval's answers), `fast_model` (router, filter extraction) and `judge_model` (`gpt-6.1-sol`, grading the eval's answers). The page parser's model, `parser_model`, is `gpt-6.1-terra`: in a 5-page trial (2026-11-17) it matched `gpt-6.1-sol` at half the price. `.env` holds only secrets and switches. The fake provider keeps tests and CI deterministic, with no API key |
| Web search | OpenAI's built-in web search tool (Responses API), exposed as `LLMProvider.web_search(query) → {answer, sources[]}` | Answers rules questions the rulebook doesn't cover, only after the user agrees. No extra vendor or key. `web_search_enabled` in `config.py` turns it off |
| Chat orchestration | LangGraph `StateGraph` + `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`) | The graph holds the router, both paths and the agent loop. The checkpointer saves each conversation's state in Postgres (`thread_id` = conversation ID). `interrupt()` pauses for clarification questions and `Command(resume=…)` continues. Nodes call our `LLMProvider` instead of LangChain model wrappers, so the fake provider drives the tests |
| Streaming | SSE fed by `graph.astream(stream_mode=["updates", "custom"])` | Tokens are emitted from our provider through `get_stream_writer()` (LangGraph's `"messages"` mode only works with LangChain chat models). Node updates become the structured events |
| Background jobs | An in-process asyncio worker, with job status in the database | Enough for a local app; no Redis |
| Observability | LangSmith (the `langsmith` SDK, without LangChain) | LangGraph traces every graph run and node; `wrap_openai` adds each LLM call; `@traceable` covers retrieval stages and ingestion. Optional: on only when `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are set |
| Tooling | Ruff, mypy (strict); ESLint, Prettier; pre-commit; `just` | |
| Testing | pytest (+ testcontainers, httpx); Vitest + React Testing Library + MSW; Storybook interaction and a11y tests; Playwright | |
| Delivery | Docker Compose; GitHub Actions | |

## Repository layout

```
bg-assistant/
├─ backend/
│  ├─ pyproject.toml, uv.lock, alembic/, Dockerfile
│  ├─ app/
│  │  ├─ main.py, config.py (pydantic-settings), export_openapi.py
│  │  ├─ cli.py           reindex, eval-ingest, eval and chat commands for using the engine from a terminal
│  │  ├─ tracing.py       LangSmith setup: wrapped OpenAI client, run metadata helpers
│  │  ├─ errors.py        error kinds the services raise (NotFoundError, RuleViolationError, TooLargeError), free of HTTP
│  │  ├─ api/             health.py, games.py, rulebooks.py, chat.py, deps.py,
│  │  │                   error_handlers.py (maps each error kind to one status: 404, 413, 422)
│  │  ├─ db/              session.py, models.py
│  │  ├─ schemas/         Pydantic request and response models
│  │  ├─ services/        games.py (game CRUD and the expansion rules), rulebooks.py (rulebook CRUD
│  │  │                   and file storage); the API routes call these
│  │  ├─ llm/             base.py (LLMProvider protocol), openai.py, fake.py
│  │  ├─ ingestion/       pdf_info.py (PyMuPDF: readable check, page count, page images, text
│  │  │                   layer), llm_parser.py (page images → Markdown), markdown_elements.py
│  │  │                   (Markdown → typed elements), parsers.py (the LLM parser, and a fake
│  │  │                   for tests), chunker.py, embedder.py, quality.py (parse report),
│  │  │                   pipeline.py, jobs.py
│  │  ├─ retrieval/       hybrid.py (vector + full-text, RRF: the search chat and the eval use)
│  │  ├─ evaluation/      library.py, database.py (the eval database), questions.py, metrics.py,
│  │  │                   retrieval.py (scores each question), report.py, text_overlap.py
│  │  │                   (text kept per page), answers.py (the answer check)
│  │  └─ chat/            state.py, graph.py, prompts.py, streaming.py (graph stream → SSE events)
│  │                      nodes/ router.py, recommend.py, rules_agent.py, tools.py, clarify.py,
│  │                             reply.py, web_answer.py
│  ├─ eval/               golden_questions.json, library.json, reports/
│  ├─ data/uploads/       uploaded rulebook PDFs (gitignored; mounted into the backend container)
│  └─ tests/              unit/, integration/, fixtures/ (small sample PDFs)
├─ frontend/
│  ├─ src/                all frontend code (the @/ import alias points here)
│  │  ├─ app/             routes: games/, games/[id]/, games/[id]/edit/, games/new/, rulebooks/, chat/,
│  │  │                   chat/[conversationId]/
│  │  ├─ components/ui/   shadcn components
│  │  ├─ features/        health/, games/, rulebooks/, chat/ (stories and tests next to each component)
│  │  ├─ api/             generated types (schema.d.ts) and fetch clients
│  │  └─ mocks/           MSW handlers shared by Storybook, Vitest and dev
│  ├─ e2e/                Playwright tests
│  ├─ .storybook/         main.ts, preview.tsx
│  └─ package.json, next.config.ts, playwright.config.ts, vitest.config.mts, Dockerfile
├─ docs/                  ARCHITECTURE.md, diagrams and screenshots
├─ docker-compose.yml     db (pgvector), backend, frontend
├─ justfile               every development command
├─ .pre-commit-config.yaml
└─ .github/workflows/     ci.yml
```

## Data model

- **Game:** id, name, description, min/max players, min age, min/max play time (minutes), genres[], publisher, year, `is_expansion`, `base_game_id` (the expansion's base game; null for base games and for expansions whose base game isn't in the library), timestamps. A base game can't have a `base_game_id`, an expansion's base game must itself be a base game (one level only), and a game that has expansions can't become an expansion. Rules about a single row (the ranges, a base game with no `base_game_id`) are CHECK constraints; rules that look at another game are checked in `services/games.py`, because a CHECK can only see its own row. Deleting a base game unlinks its expansions (`ON DELETE SET NULL`) instead of deleting them.
- **Rulebook:** id, `game_id` (required: every rulebook belongs to a game, while a game can have several rulebooks or none), `filename` (the uploaded name, shown in the UI and renamable), `storage_path` (the file's name inside `upload_dir`: `{sha256}.pdf`), page_count, `sha256` (unique across the library; catches duplicate uploads), `status` (`uploaded` → `processing` → `ready` / `failed`), error, `parse_report` JSON (chunk count, pages where no text was kept), `markdown` (the parser's Markdown; null until the rulebook is first parsed, and kept so a reindex doesn't pay for the model again), timestamps. Deleting a game deletes its rulebooks (`ON DELETE CASCADE`).
- **Chunk:** id, rulebook_id, game_id (copied from its rulebook so retrieval can filter by game directly), `section_path` (the heading path from the Markdown's heading levels, e.g. "Card Details › Duo cards"), `chunk_type` (`section` / `table` / `glossary`), page_start, page_end (`page_start >= 1`, `page_end >= page_start`), content (prefixed with its section path, never the game name, so renaming a game needs no re-embedding), `tsv` (a generated tsvector of `content` with English stemming, GIN index), `embedding vector(768)` (HNSW index, cosine), created_at. Chunks are never edited: reindex deletes and rewrites them. `(rulebook_id, game_id)` is one foreign key to `rulebooks(id, game_id)` (which needs a unique constraint on that pair) with `ON UPDATE CASCADE` and `ON DELETE CASCADE`: a chunk's game can't differ from its rulebook's, moving a rulebook moves its chunks in the database, and deleting a rulebook or its game deletes them. Both ids are indexed: Postgres doesn't index the referencing side of a foreign key, and replacing, moving or deleting a rulebook's chunks looks them up by `rulebook_id`.
- **Conversation:** id (also LangGraph's `thread_id`), title (the first message cut to about 60 characters, no LLM call; renamable), created_at, updated_at. Used to list chats in the sidebar.
- **Conversation state** is not one of our tables: the LangGraph checkpointer stores messages, citations, the resolved game and expansions, and any pending interrupt.

Modelling expansions as child games lets chat scope retrieval to a base game plus any chosen subset of its expansions.

## Flow 1: Add a game and its rulebooks

Games and rulebooks are separate operations: a game is created from its fields alone, and each rulebook is added to an existing game. The "Add game" page combines the two.

1. **The form.** You type the game's details; an "Expansion of…" picker lists the library's base games. A file picker accepts several PDFs. Before anything is sent, zod checks the fields, and each file must be a PDF under `max_upload_mb` (a setting in `config.py`).
2. **Save.** `POST /api/games` (JSON) creates the game and returns its `id`. Then the frontend sends one `POST /api/games/{id}/rulebooks` per file, in parallel, and shows each file's progress and result. One request per file means a bad file never blocks the good ones.
3. **Adding a rulebook** (the same endpoint is used by "Add rulebook" on a game's page). The backend:
   1. rejects files over `max_upload_mb` (413)
   2. hashes the file; if the `sha256` matches a stored rulebook, it returns 422 with `duplicate_of: {rulebook_id, game_id, name}`
   3. opens it with PyMuPDF; an unreadable file is a 422. The page count is read here.
   4. writes the file to `upload_dir` as `{sha256}.pdf`, then inserts the `Rulebook` (status `uploaded`; a filename over 255 characters is cut to fit, since it's only a display name) and commits; if the commit fails, it deletes the file. The file is written first because the opposite failure, a row pointing at a missing file, is worse; a leftover file is harmless, since the same PDF always gets the same name.
   5. queues the rulebook for the background ingestion worker (below)

   The file is only stored here. FastAPI's `UploadFile` spools the upload to a temporary file while it arrives; the route then reads it into memory to hash and check it, which is fine at `max_upload_mb` for a local app.
4. **When something fails.**
   - Creating the game fails: nothing is saved, and the form keeps your fields and files.
   - A rulebook fails: the game and the other rulebooks are already saved. Each file shows its reason: duplicate ("already in your library (Catan)"), unreadable or too large offer **Remove**; a network or server error offers **Retry**. "Go to game" leaves; missing rulebooks can be added from the game's page later.
   - A duplicate of the same game counts as saved: it means an earlier request succeeded but its response was lost.
5. **Ingest.** One background worker, started with the app, ingests queued rulebooks one at a time: parsing and embedding are CPU-heavy, and two jobs at once would double the memory. The queue is in memory (an `asyncio.Queue` of rulebook ids), so on startup the worker re-queues every rulebook still `uploaded` or `processing`; a job stopped by a restart starts again from the beginning. It first marks the rulebook `processing`, then, per rulebook:
   - **Parse:** PyMuPDF renders each page as an image, and a vision model (`parser_model`) writes it as Markdown following a fixed contract: verbatim text, real heading levels, captions and box titles in bold, sidebars as blockquotes, tables as tables, text in pictures written out when it matters for play, icons that stand for game terms as `[term]`, and no page numbers, running headers or hidden copies. Our code removes a code fence the model may wrap a whole reply in, and adds a `<!-- page N -->` marker before each page. Scanned pages need no OCR step, since every page is read from its image.
     - **Into elements:** the Markdown is read into typed elements (heading, paragraph, list item, table, caption) in reading order with page numbers. A heading's text is its path from the heading levels, a page that doesn't start with a heading continues the previous page's section, a line that's all bold (a caption or box title) is a caption, and table rows start and end a block even with no blank line around them.
     - **Stored and reused:** the Markdown is saved on the rulebook in its own commit as soon as the parse ends, so a later failure doesn't lose what it cost, and the next parse of that rulebook reuses it with no model call.
     - **No key needed to start:** the OpenAI provider is created on the first parse that calls the model, so the app starts without `OPENAI_API_KEY`, and only a rulebook that needs the model fails without one.
   - **Chunk (rulebook-aware):**
     - Split at every heading. Merge sections under ~20 tokens (the headings are the rulebook's real section titles, so only scraps are merged) into the previous one (into the next one only when there's no previous one), but only when the two share a page, so a heading with almost nothing under it joins its neighbour without stretching a chunk's page citation onto another page; split long ones at paragraph or list breaks, targeting ~350 tokens with a hard limit of ~450. A chunk's last element is repeated at the start of the next chunk if it's at most ~50 tokens, and otherwise there's no overlap. A paragraph still over the limit is split at sentence ends, and a sentence still over it by token count, because the embedder silently cuts off anything past 512 tokens.
     - A paragraph cut by a page break comes out as two items. When a text item doesn't end with `.`, `!`, `?` or `:` and the next item is text at the top of the next page that starts with a lowercase letter or a digit, the two are joined into one paragraph, so a split never lands mid-sentence. A capital, or Markdown such as `**Example:**`, `> Note` or `[wood]`, starts something new.
     - Sidebars and "Example" boxes come out as blockquotes or bold-titled paragraphs in the section they're printed in, so they join the rule they illustrate.
     - Each table is its own chunk, starting with its heading and the caption right above it on the same page, if there is one, and isn't merged with text; the text around it stays together in a section chunk. A table over the limit is split between rows with the heading, caption and header row repeated, and a single row still over it is cut between words.
     - Four or more `Term: definition` lines in a row count as a glossary, and each entry gets its own chunk, starting with its heading, so a search for one term finds that term alone. The term must start with a capital, be at most 40 characters and contain no sentence-ending punctuation. Text around the run stays in a section chunk. Entries aren't merged when small, and one over the limit is split the same way as a long section. FAQs and quick-reference pages have no rule of their own, because few rulebooks have them, so their text stays in section chunks.
     - Sections about who made the game are dropped before anything else is pulled out: each heading that is a credits, acknowledgements or playtesters title, a company name ending in "Inc." or a web address drops everything up to the next heading, its subsections too, since any part of a heading's path counts. The whole heading must match, so a rules section like "Earning Credits" stays. Contents and index pages aren't dropped by name: in the rulebooks tried, "Contents" listed the components or sat empty above real rules, and an "Index" heading came right before a rules summary. An empty heading is skipped anyway.
     - With no headings, the whole text is one section with an empty path, so the long-section splitter cuts it at paragraph breaks into ~350-token chunks; no separate fallback is needed.
   - **Prefix:** each chunk starts with its section path only (e.g. `Trading`). The game name is added when chunks are put into a prompt.
   - **Embed and store:** embed with bge-base, then, in one transaction, lock the rulebook's row (`SELECT … FOR UPDATE`), replace its chunks, save the parse report and set `ready`. The rulebook's game is read under the lock, not before the parse, because a move during the parse changes it; the lock then makes a move, or a second ingestion of the same rulebook, wait until the chunks are saved. A rulebook deleted during the parse is skipped. Any error rolls back, keeping the old chunks, and saves `failed` with the message; so does a failure to load the embedding model, which the next job tries again. A failed rulebook isn't retried automatically; `just reindex` runs it again.
6. **Status.** There's no separate status endpoint: each rulebook in `GET /api/games/{id}/rulebooks` carries its `status`, `error` and parse report, so one request covers every upload on the page. The UI polls that list every few seconds while any rulebook is `uploaded` or `processing`, shows a badge per rulebook, and stops when all are `ready` or `failed`. A ready rulebook shows its parse warnings.

## Flow 2: Manage games and rulebooks

**Games**
- `GET /api/games` with optional filters, all of which must match: `q` (part of the name, any case), `players` (games known to support that many; unknown counts are excluded), `genres` (any of those given) and `base_game_id` (that game's expansions). `GET/PATCH/DELETE /api/games/{id}`.
- Editing a game never touches its rulebooks: chunks don't contain the game name, so nothing is re-embedded.
- Deleting a game deletes its rulebooks and their chunks (cascade), commits, then removes their files.
- A game without rulebooks is allowed. Recommendations work from its fields; for rules questions, the agent says the game has no rulebook yet instead of searching.

**Rulebooks**
- `POST /api/games/{id}/rulebooks` adds one (Flow 1). `GET /api/games/{id}/rulebooks` lists a game's; `GET /api/rulebooks` lists all of them, with each one's game name and status.
- `PATCH /api/rulebooks/{id} {filename?, game_id?}` renames it (display only) or moves it to another game. A move updates its chunks' `game_id` in the same statement, through the foreign key's `ON UPDATE CASCADE`, so the service needs no extra code; nothing is re-parsed or re-embedded.
- `DELETE /api/rulebooks/{id}` deletes the row and its chunks, commits, then removes the file. Files and rows can't share a transaction, so this order means a failure can only leave an orphan file, never a row pointing at a missing one. A file that can't be removed (for example, open in another program on Windows) is logged and left behind, and the delete still succeeds.
- `GET /api/rulebooks/{id}/file` returns a `FileResponse`, which streams the file from disk in small pieces and answers HTTP range requests with `206 Partial Content`, so pdf.js loads only the pages it shows. CORS exposes `Accept-Ranges` and `Content-Range` so pdf.js can read them (without them it falls back to downloading the whole file), and PDF responses are never gzipped, which would break ranges.

**Frontend:** each game's page has a Rulebooks section (open in the viewer, rename, delete, add); the `/rulebooks` page lists every rulebook in the library with the same actions plus moving to another game.

**Ingestion and reindexing**
- Ingestion runs once per rulebook; chat only embeds the question. Each model loads once per backend process. The embedding model, and the libraries it needs, load on the first ingestion job rather than at startup, so `--reload` in `just dev` doesn't wait about 10 s for them. Milestone 6 decides whether chat shares that instance or loads it at startup, so the first question doesn't wait.
- `just reindex [--game <id>]` re-runs parse → chunk → embed from the stored PDFs, for one game or all, after a chunker or embedding change. Each rulebook's chunks are replaced in one transaction, so a failure keeps the old chunks. It prints each rulebook's result and exits with code 1 if any failed. A rulebook deleted while it runs is reported as skipped and left out of the total. A rulebook's stored Markdown is chunked again with no model call; `--reparse` ignores it, so the model reads the pages again (and is paid).

## Flow 3: Chat

A LangGraph graph with a router, then either recommendations (SQL) or rules answers (RAG).

```
START → router ─┬─ recommendation → extract_filters → query_games ─(no criteria)→ clarify ⟲
                │                                        └→ write_recommendation → END
                ├─ rules_question → rules_agent ⇄ tools (find_games, search_rules)
                │                        ├─(ask_user)→ clarify (interrupt) → rules_agent
                │                        └─(offer_web_search)→ confirm_web (interrupt) ─(yes)→ web_answer → END
                │                                                                    └─(no)→ END
                └─ other → reply → END
```

**State (`ChatState`):** `messages` (with the `add_messages` reducer), `route`, `game_id`, `expansion_ids`, `filters`, `citations`, `recommendations`, `web_sources`.

**API:**
- `POST /api/chat {game_id?, expansion_ids?}` creates a conversation. A given game is written into the graph state straight away, so the agent doesn't ask which game.
- `POST /api/chat/{id}/messages {text}` runs the graph and streams SSE events: `route`, `token`, `tool_call`, `clarification`, `citations`, `recommendations`, `web_sources`, `done`. On an interrupt the stream sends `clarification` (question and options) and closes.
- `POST /api/chat/{id}/resume {answer}` continues with `Command(resume=answer)` and streams the same events.
- `GET /api/chat/{id}` loads history and any open question from `graph.aget_state()`.
- `PATCH /api/chat/{id}/scope` sets the game and expansions by hand (`graph.aupdate_state()`).
- `GET /api/chat` lists conversations, newest first; `PATCH /api/chat/{id} {title}` renames; `DELETE /api/chat/{id}` deletes the row and its saved state (`checkpointer.adelete_thread`).
- The UI only creates a conversation when the first message is sent, so empty chats never appear in the sidebar.

**Router.** One `fast_model` call with structured output reads the new message and the last few turns and returns `recommendation`, `rules_question` or `other` (a short direct reply, no tools). The `route` event drives a badge in the UI.

### Recommendation path (no RAG)

1. The LLM extracts a `GameFilter`: `players`, `genres[]`, `max_play_time`, `min_age`, `include_expansions` (default false) and free-text `mood` keywords.
2. `recommend.py` turns the filter into one SQLAlchemy query: player count within min/max, genre array overlap, play time limit (which end of the min/max range to compare is decided in milestone 6), mood keywords via pg_trgm and full-text search over descriptions, ranked by how many criteria match.
3. With no match, filters are relaxed one at a time (play time, then genre) and the answer says which. With no criteria at all, the `clarify` node asks, with quick options.
4. The LLM explains each pick using only the returned rows, so it never invents games. A `recommendations` event sends game cards that link to each game.

### Rules path (agentic RAG)

The `rules_agent` node calls `chat_model` with four tools. Conditional edges send `find_games` and `search_rules` to the `tools` node, `ask_user` to `clarify` and `offer_web_search` to `confirm_web`; no tool calls ends the turn. `recursion_limit` caps the loop at about 5 tool rounds.

- **`find_games(query)`:** pg_trgm fuzzy matching; returns candidate base games and their expansions, and whether each has a ready rulebook.
- **`search_rules(game_id, expansion_ids[], query)`:** hybrid retrieval scoped to the selected game and expansions:
  1. vector search: top 30 by cosine similarity (with the BGE query prefix), exact within the chosen games: sorting ties by chunk id keeps Postgres off the HNSW index, which would apply the game filter after its nearest neighbours and could return too few
  2. keyword search: top 30 by Postgres full-text rank among chunks with any of the question's words (`websearch_to_tsquery` with `or` between the words, ranked by `ts_rank`); requiring every word matched chunks for only 5 of the 30 golden questions
  3. Reciprocal Rank Fusion (k = 60), then send the top 5 to the LLM, each shown as `[<Game name> (base game | expansion) › <section path>, p. X–Y]` followed by its text; the name comes from a join, so it's always current. A cross-encoder reranker was tried in 5a and 5b and never beat this order, so there's none.

  The counts are settings in `config.py`, so the evaluation can compare values.
- **`ask_user(question, options[])`:** the `clarify` node calls `interrupt({question, options})`. The state is checkpointed, so a waiting question survives a backend restart. The UI shows the options as chips; `/resume` writes `game_id` and `expansion_ids` into the state and returns the answer to the agent. `clarify` does nothing before `interrupt()`, because LangGraph reruns the node from the start on resume.
- **`offer_web_search(query)`:** only after the agent has found that `search_rules`' excerpts don't cover the question and has said so; Reciprocal Rank Fusion's ranks aren't scores that a threshold could judge. `confirm_web` interrupts with "Search the web" / "No thanks". On yes, `web_answer` calls `LLMProvider.web_search` and writes an answer labelled "From the web, not your rulebook", with a `web_sources` event and never mixed with page citations. The prompt prefers official sources (publisher FAQ or errata, designer answers) and says when sources disagree. Not offered when `web_search_enabled` is off.

**Agent rules:** ask first when the game is unknown or ambiguous, or when the answer could depend on expansions. The resolved scope stays in the state, so follow-ups don't ask again. Answers use only retrieved chunks and cite them as `[p. 12]`; citations open the PDF viewer at that page. When an expansion rule overrides a base rule, the answer says so. When the rulebook doesn't cover the question, the agent says so instead of guessing. When the chosen game has no ready rulebook, it says so instead of searching.

## LLM cost and prompts

- Prompts are laid out for OpenAI's automatic prompt caching: the system prompt and tool definitions come first and never change between calls, and the conversation is append-only. History is never trimmed or rewritten, so the full context is kept and every resent part is billed at the cached-input rate.
- Real cost per trace is checked in LangSmith, and a spending limit is set in the OpenAI dashboard.
- LangSmith runs are tagged with the route, game ID and conversation ID (used as LangSmith's thread), so each chat message is one trace tree.

## Evaluation

- **Golden questions:** `backend/eval/golden_questions.json` holds 30 questions from 7 rulebooks across 5 games (Sea Salt & Paper with its Extra Salt and Extra Pepper expansions, Rebel Princess, Splendor, Catan, Power Grid), written from the PDFs before looking at any retrieval results. Each lists where its answer is printed (rulebook file and pages), a short answer, and tags for what makes it hard (text in pictures, OCR, tables, callouts, short sections, answers that change with an expansion). The PDFs aren't committed: they live in the git-ignored `backend/data/rulebooks/`, and the questions only point at pages.
- **Eval database:** the eval runs against its own database, `bg_assistant_eval` in the same Postgres, never the dev library, so adding or deleting games in the app can't change a score. `just eval-ingest` rebuilds it through the normal ingestion pipeline, from the PDFs and `backend/eval/library.json` (each game, which games are its expansions, and its rulebook file). Run it after a parser or chunker change. The rebuild replaces every game, but each rulebook gets back the Markdown stored for the same PDF (matched by `sha256`), so only a new or changed PDF pays for the parse; `--reparse` reads every page again, after a change to the parser's prompt or model.
- **Retrieval (no LLM, free):** Recall@k, MRR and nDCG of hybrid search, in one report (`just eval`). Each question searches its game's whole family (the base game and all its expansions), as chat would. A retrieved chunk is a hit when it comes from an expected rulebook and an expected page falls inside its `page_start`–`page_end` range; covering any expected place counts. Pages stand in for the right text, so a chunk on the right page counts even if it's about something else.
- **Retrieval tuning (5a, 2026-11-17):** on 134 chunks, hybrid search scores Recall@5 0.93 and MRR 0.87, and reranked search 0.90 and 0.83. Kept: small sections merge only within a page (narrower citations, same scores) and full-text search matches any of the question's words (hybrid MRR 0.85 → 0.87). Tried and left out: `traverse_pictures=True` (one more answer found, but hundreds of noise elements) and other candidate counts (no change). The questions still missed fail on the parse (text in pictures) or the chunking (a long section, a first section under the next heading), which 5b's parser targets.
- **Answer check:** `just eval-answers` sends each question's top 5 chunks from hybrid search to `chat_model`, which answers from them only, citing pages, and `judge_model`, a stronger model than the one answering, grades the answer against the golden `answer` with a structured reply, its reason first and then correct, partial or wrong; a reply cut off or refused counts as wrong. The judge doesn't penalise different wording, citations, correct extra detail or details the question didn't ask about, and does penalise any contradiction and a rule applied more broadly than the golden answer (a worked example's result as the general rule, an expansion's rule as the whole game's). The committed report has the verdict counts and each question's verdict; the answers quote the rulebooks, so they go to the git-ignored `backend/data/answer-checks/` for reading by hand. A run costs about $0.10. It's the only measure that sees whether a chunk's text is usable, such as a table kept as rows rather than loose numbers.
- **Parser comparison (milestone 5b):** Docling, a local layout model that was the first parser, and the LLM parser were compared, each in its own eval database, on retrieval, on how much of each page's text the parse kept, on the answer check, and on cost and time. With 30 questions, a gap of one or two is noise, so the questions where the parsers disagreed were read by hand. The rule, set before the answer check ran: the LLM parser stays unless it answers 2 or more fewer questions correctly than Docling and reading the questions where they differ shows its chunks are the cause; a tie goes to the LLM parser, which reads text in pictures and removes Docling's crash workaround and heavy dependency for about $0.006 a page, once. The loser is removed. The answer check used hybrid search only, since the reranker hadn't beaten it in any retrieval run and added about 5 s per search.
- **Parser decision (5b, 2026-11-22):** with each caption kept in its table's chunk, hybrid search finds 29 of the 30 answers in the top 5 with LLM-parsed chunks and 28 with Docling's (MRR 0.88 and 0.87); the reranker beats hybrid search on neither (Recall@5 0.93 and 0.90). The LLM parser kept 88–100% of each rulebook's text-layer words (Extra Salt's 64% is the hidden copies it's told to skip) and invented none; it leaves out card faces and credits, as its contract says. The answer check tied at 24 correct of 30 each. Of the six questions whose verdicts differ, the LLM parser's three losses were a table chunk just outside the top 5, a sentence Docling happened to merge into a neighbouring chunk, and an answer's wording; its gains include the dice odds, which only exist in its Markdown. So the LLM parser stayed, and Docling and the reranker were removed. Both parsers still miss an untitled colour legend (salt-03), the player-count table for Step 2 (powergrid-05), and pepper-01, where the right chunk was ranked 2nd but the answer said the excerpts don't cover it.
- **Text kept:** `just eval-text` compares the stored Markdown with each PDF page's text layer as lower-case words, ignoring Markdown symbols (word recall and precision, with the text layer as the reference): the share of the text layer's words it kept (low means dropped text) and the words it added (changed or invented text, or text read from a picture with no text layer). Pages under `eval_text_min_page_chars` (scanned or nearly blank, like all of Rebel Princess) have nothing to compare with and are skipped. The committed report has counts only; the least-kept pages' missing and added words are printed to the terminal, since the rulebooks' text isn't committed. A model writes the text rather than copying it, so this is how a change to the parser's prompt or model is checked for dropped or invented words.
- **Answers (LLM-as-judge, milestone 6):** faithfulness, correctness and citation accuracy, reusing the judge from 5b's answer check, plus clarification behaviour (asks when it should, stays quiet when it shouldn't; the `expansion-dependent` questions are the cases where it should ask) and a few out-of-scope questions (declines, then offers web search only for those).
- **Routing:** about 40 labelled messages, including tricky ones; accuracy and a confusion matrix.
- **Reports:** each run writes a Markdown report to `backend/eval/reports/`; the reports from before the 5b decision also cover Docling and the reranker, and `…-comparison.md` puts both parsers side by side. Reports are committed, so a pull request shows its effect on the scores, and the README shows the final table.
- **Local only:** the rulebooks can't be committed, so CI has nothing to ingest, and a score means something only next to another run. `just eval` runs retrieval; `just eval --all` adds routing and answers, which spend OpenAI credit. CI runs unit tests of the metric functions on hand-made rankings.

## Testing strategy

Tests are written with each feature, not at the end. A milestone is done only when its tests pass, CI is green and coverage is at least 80%. A bug gets a regression test before its fix.

**Backend**
- **Unit tests:** the chunker on hand-built element lists, prefixes, RRF, prompt building, schema validation, `GameFilter` → SQL with relaxation, the expansion rules, and graph tests with `InMemorySaver` and `FakeLLMProvider` (each route, the step limit, interrupt and resume, scope changes, and web search yes, no and turned off).
- **Integration tests:** a testcontainers pgvector database, with a test that the migrations match the models (`alembic check`); the API through httpx `AsyncClient` (including message → interrupt → resume with the Postgres checkpointer; rulebook uploads, where every rejection leaves no row and no file; moving and deleting rulebooks; range requests on the file; reindex transactions); ingestion end to end on a generated PDF, with the model's page Markdown scripted and the real chunker, embedder and database; the ingestion worker run directly against the test database, while the app's own worker is off in tests (`RUN_INGESTION_WORKER=false`), so starting the app never ingests the dev database's rulebooks.
- **Guard against real LLM calls:** pytest's environment forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and turns LangSmith off; `pytest-socket` blocks all network access except localhost. A test that reaches for OpenAI fails instead of spending credit.
- **Live tests:** a few tests marked `live`, one per real call type, check that OpenAI accepts the strict schemas and tool definitions. They're skipped by default and run with `just test-live`.
- **Real models only where needed:** other tests use a `FakeEmbedder` and a `FakeLLMProvider`; only the embedder and ingestion integration tests load the BGE model. A guard test checks that importing the app loads neither sentence-transformers nor PyTorch.

**Frontend**
- Vitest + React Testing Library + MSW for components and the API client.
- A Storybook story for every component state; story tests run interaction and a11y checks (violations fail the test), sharing MSW handlers with the unit tests.

**End-to-end**
- Playwright against the app with the fake LLM, so it's deterministic and needs no API key: adding a game with several PDFs (one of them a duplicate), editing and deleting it, renaming, moving and deleting a rulebook, a chat that asks for clarification and then cites a page, a recommendation request, and an out-of-scope question answered from the web.

## Development and delivery

- **Two ways to run:** day-to-day development runs the backend and frontend on the host with hot reload (`just dev`), with only Postgres in Docker. `just up` runs all three as containers, which is what CI's e2e job uses.
- **Images:**
  - The backend image installs locked dependencies in a cached layer, then copies the code; at start it runs `alembic upgrade head`, then `exec uvicorn`.
  - The frontend image is a two-stage build of Next.js's standalone output. `NEXT_PUBLIC_API_URL` is a build argument, because it's inlined into the browser bundle at build time.
- **Compose:** `depends_on` with healthchecks orders startup (db → backend → frontend); the backend's healthcheck calls `/api/health`, so it's unhealthy whenever the database is unreachable.
- **just** is the single entry point for every command, locally and in CI.
- **pre-commit** runs Ruff, Prettier and ESLint as local hooks, using the exact tool versions in the lock files, plus YAML and large-file checks.
- **CI (`ci.yml`)** runs four jobs on every pull request and every push to `main`:
  1. **backend:** `uv sync --locked`, Ruff, mypy, pytest with coverage (the integration tests start their own pgvector container with testcontainers and run the migrations in it)
  2. **frontend:** `npm ci`, ESLint, Prettier, tsc, Vitest (unit and story tests), the Next.js build and the Storybook build
  3. **contract:** regenerate the OpenAPI schema and TypeScript types and fail if they differ from the committed ones
  4. **e2e:** start the app in containers, run Playwright, and on failure print container logs and upload traces

  From milestone 4, the backend job restores a cache of the Hugging Face embedding model.

## Milestones

**Phase 0: Scaffold**
1. The monorepo, tooling and CI, working end to end before any features: the backend with `/api/health` and the first migration, the frontend health page using the generated types, Storybook, Vitest, Playwright, Docker Compose, `just`, pre-commit, CI and these docs.

**Phase A: Engine (backend only)**

2. **Games data and API:** models and migrations (expansion rules, unique `sha256`) and `/api/games`. Tests: the testcontainers fixture with per-test rollback, CRUD, expansion validation, cascading deletes, `sha256` uniqueness.
3. **Rulebooks API:** adding a rulebook to a game (size limit, PyMuPDF check and page count, the duplicate check, file storage), listing all and per game, rename and move, delete with its file, serving the file with range requests, and deleting a game's files with the game. No LLM yet. Tests: every rejection leaving no row and no file, a failed commit removing the written file, duplicates across games, rename and move, delete removing the file, a range request returning 206, game deletion removing files.
4. **Ingestion:** the Docling parser (replaced in 5b), the chunker, prefixes, the embedder, the parse report (returned with each rulebook), the background job, moving a rulebook updating its chunks, and `just reindex`. Tests: every chunker rule, the fake embedder, the three layout fixtures, parse report flags, transactional reindex, job status, a move updating chunks.

5a. **Retrieval and evaluation:** hybrid search (vector, full text matching any word, RRF) scoped to a game's family, the reranker (on trial until 5b), the eval database (`just eval-ingest`), the golden questions and retrieval metrics (`just eval`, hybrid and reranked side by side), and tuning: small sections merge only within a page; `traverse_pictures=True` and other candidate counts were tried and left out. Tests: RRF, scoping to the chosen game, reranked and unreranked search, current game names, the metric functions, the report.

5b. **LLM parser:** `LLMProvider` (OpenAI and fake) and `just test-live`. A parser sends each page image to a vision model, which writes it as Markdown following a fixed contract (verbatim text, real headings with levels, captions and box titles as bold text, informative text in pictures written out, icons that stand for game terms as `[term]`, no page numbers or hidden copies); our code adds a marker for each page. A chunker splits at the Markdown headings and never merges across a page, except to join a sentence cut by a page break; a page with no heading continues the previous page's section path. The Markdown is stored on the rulebook, so a reindex doesn't pay for it again. It was compared with Docling, each parser in its own eval database, on 5a's eval, the text kept per page (`just eval-text`) and an answer check (`just eval-answers`), under a decision rule set before the answer check ran; the LLM parser won, and Docling and the reranker, which hadn't beaten hybrid search on either parser's chunks, were removed. The PDF is still stored, for the viewer, citations and re-conversion; milestone 8 adds a view and editor for each rulebook's Markdown (saving re-ingests it). Tests: the contract on scripted fake responses, the new chunker's rules, storing and reusing the Markdown, the provider created only when the model is called, the text-kept and answer reports, the judge's structured reply, live tests.

6. **Chat graph:** add `web_search` to the `LLMProvider` and LangSmith tracing (`tracing.py`); state, the graph with the Postgres checkpointer, router, recommendation nodes, the agent loop, both interrupts, `web_answer`, the chat API with SSE, the routing and answer evals, and `just chat`. Tests: graph tests, filter relaxation, SSE mapping, API interrupt and resume, separate conversation state, live tests.

**Engine checkpoint:** `just test`, `just eval` and real conversations with `just chat`, checked in LangSmith. After this the API is fixed, so the frontend is built against a stable contract.

**Phase B: Frontend**

7. **App shell and API layer:** layout and navigation, regenerated types, server and browser fetch clients, TanStack Query, and MSW handlers for every endpoint.
8. **Games and rulebooks pages:** game list, detail (with its Rulebooks section), edit and delete; the Add game form with several PDFs and a result per file; the `/rulebooks` page; the PDF viewer; ingestion status. Tests: stories, form tests (mixed upload results, retry, a same-game duplicate counting as saved), Playwright flows.
9. **Chat UI:** the SSE client, streaming, route badge, clarification chips, scope selector, citations that open the PDF viewer, recommendation cards, labelled web answers, and the conversation sidebar. Tests: stories, stream rendering, Playwright chat flows.

**Phase C: Hardening**

10. Error and empty states, coverage gaps, flaky-test cleanup, and the README (architecture diagram, demo GIF, eval table). Stretch goals: re-parse flagged pages with a vision model; offer to link unlinked expansions when their base game is added.
