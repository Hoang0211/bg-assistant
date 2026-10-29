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
| PDF parsing | Docling for ingestion; PyMuPDF to check uploads | Rulebooks vary a lot in fonts, columns, sidebars and tables. Docling finds structure from the page layout, gives the correct reading order and tables, drops headers and footers, and runs OCR on scanned pages, locally on the GPU. PyMuPDF opens an upload in milliseconds to check it's a readable PDF and read its page count |
| Embeddings | `BAAI/bge-base-en-v1.5` via sentence-transformers (768 dimensions; GPU, or CPU as a fallback) | Free, local and offline. Its 512-token input limit caps chunks at about 450 tokens (counted with the BGE tokenizer). Queries get the BGE query prefix and chunks don't; vectors are normalised and compared by cosine similarity |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | Better precision for rules lookups |
| LLM | OpenAI (official `openai` SDK) behind a small `LLMProvider` interface with two implementations, `openai` and `fake` | Structured outputs with Pydantic models, function calling and streaming. Two model names are defaults in `config.py`: `chat_model` (rules agent, recommendation answers) and `fast_model` (router, filter extraction). `.env` holds only secrets and switches. The fake provider keeps tests and CI deterministic, with no API key |
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
│  │  ├─ cli.py           add-rulebook, chat and reindex commands for using the engine from a terminal
│  │  ├─ tracing.py       LangSmith setup: wrapped OpenAI client, run metadata helpers
│  │  ├─ errors.py        error kinds the services raise (NotFoundError, RuleViolationError, TooLargeError), free of HTTP
│  │  ├─ api/             health.py, games.py, rulebooks.py, chat.py, deps.py,
│  │  │                   error_handlers.py (maps each error kind to one status: 404, 413, 422)
│  │  ├─ db/              session.py, models.py
│  │  ├─ schemas/         Pydantic request and response models
│  │  ├─ services/        games.py (game CRUD and the expansion rules), rulebooks.py (rulebook CRUD
│  │  │                   and file storage); the API routes call these
│  │  ├─ llm/             base.py (LLMProvider protocol), openai.py, fake.py
│  │  ├─ ingestion/       pdf_info.py (PyMuPDF: readable check, page count),
│  │  │                   layout_parser.py (Docling → typed elements), chunker.py, embedder.py,
│  │  │                   quality.py (parse report), pipeline.py, jobs.py
│  │  ├─ retrieval/       hybrid.py (vector + full-text, RRF), reranker.py
│  │  └─ chat/            state.py, graph.py, prompts.py, streaming.py (graph stream → SSE events)
│  │                      nodes/ router.py, recommend.py, rules_agent.py, tools.py, clarify.py,
│  │                             reply.py, web_answer.py
│  ├─ eval/               golden datasets, run_eval.py, reports/
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
└─ .github/workflows/     ci.yml, eval.yml
```

## Data model

- **Game:** id, name, description, min/max players, min age, min/max play time (minutes), genres[], publisher, year, `is_expansion`, `base_game_id` (the expansion's base game; null for base games and for expansions whose base game isn't in the library), timestamps. A base game can't have a `base_game_id`, an expansion's base game must itself be a base game (one level only), and a game that has expansions can't become an expansion. Rules about a single row (the ranges, a base game with no `base_game_id`) are CHECK constraints; rules that look at another game are checked in `services/games.py`, because a CHECK can only see its own row. Deleting a base game unlinks its expansions (`ON DELETE SET NULL`) instead of deleting them.
- **Rulebook:** id, `game_id` (required: every rulebook belongs to a game, while a game can have several rulebooks or none), `filename` (the uploaded name, shown in the UI and renamable), `storage_path` (the file's name inside `upload_dir`: `{sha256}.pdf`), page_count, `sha256` (unique across the library; catches duplicate uploads), `status` (`uploaded` → `processing` → `ready` / `failed`), error, `parse_report` JSON (chunk count, pages with little text or mostly images), timestamps. Deleting a game deletes its rulebooks (`ON DELETE CASCADE`).
- **Chunk:** id, rulebook_id, game_id (copied from its rulebook so retrieval can filter by game directly; moving the rulebook updates it), `section_path` ("Setup > Market"), `chunk_type` (`section` / `table` / `glossary` / `faq`), page_start, page_end, content (prefixed with its section path, never the game name, so renaming a game needs no re-embedding), `tsv` (tsvector, GIN index), `embedding vector(768)` (HNSW index).
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
   5. starts the background ingestion job (below)

   The file is only stored here. FastAPI's `UploadFile` spools the upload to a temporary file while it arrives; the route then reads it into memory to hash and check it, which is fine at `max_upload_mb` for a local app.
4. **When something fails.**
   - Creating the game fails: nothing is saved, and the form keeps your fields and files.
   - A rulebook fails: the game and the other rulebooks are already saved. Each file shows its reason: duplicate ("already in your library (Catan)"), unreadable or too large offer **Remove**; a network or server error offers **Retry**. "Go to game" leaves; missing rulebooks can be added from the game's page later.
   - A duplicate of the same game counts as saved: it means an earlier request succeeded but its response was lost.
5. **Ingest.** The background job, per rulebook:
   - **Parse:** Docling turns each page into typed elements (heading, paragraph, list, table, caption, sidebar) in reading order with page numbers, drops headers and footers, and runs OCR on scanned pages.
   - **Chunk (rulebook-aware):**
     - Split at every heading. Merge sections under ~80 tokens into the next one; split long ones at paragraph or list breaks, targeting ~350 tokens with a hard limit of ~450 and a small overlap.
     - Sidebars and "Example" boxes attach to the section on the same page.
     - Tables stay whole as Markdown, or split by rows with the header repeated.
     - Glossary, FAQ and quick-reference pages: one chunk per term or question.
     - Credits, table of contents and index pages are dropped.
     - With no usable headings, fall back to paragraph and size splitting.
   - **Prefix:** each chunk starts with its section path only (e.g. `Turn Order › Trading`). The game name is added when chunks are put into a prompt.
   - **Embed and store:** embed with bge-base, write the chunks, save the parse report.
6. **Status.** The UI polls `GET /api/rulebooks/{id}/status` and shows a progress badge. When ingestion finishes, the game page shows any parse warnings.

## Flow 2: Manage games and rulebooks

**Games**
- `GET /api/games` with optional filters, all of which must match: `q` (part of the name, any case), `players` (games known to support that many; unknown counts are excluded), `genres` (any of those given) and `base_game_id` (that game's expansions). `GET/PATCH/DELETE /api/games/{id}`.
- Editing a game never touches its rulebooks: chunks don't contain the game name, so nothing is re-embedded.
- Deleting a game deletes its rulebooks and their chunks (cascade), commits, then removes their files.
- A game without rulebooks is allowed. Recommendations work from its fields; for rules questions, the agent says the game has no rulebook yet instead of searching.

**Rulebooks**
- `POST /api/games/{id}/rulebooks` adds one (Flow 1). `GET /api/games/{id}/rulebooks` lists a game's; `GET /api/rulebooks` lists all of them, with each one's game name and status.
- `PATCH /api/rulebooks/{id} {filename?, game_id?}` renames it (display only) or moves it to another game. A move updates its chunks' `game_id` in the same transaction; nothing is re-parsed or re-embedded.
- `DELETE /api/rulebooks/{id}` deletes the row and its chunks, commits, then removes the file. Files and rows can't share a transaction, so this order means a failure can only leave an orphan file, never a row pointing at a missing one. A file that can't be removed (for example, open in another program on Windows) is logged and left behind, and the delete still succeeds.
- `GET /api/rulebooks/{id}/file` returns a `FileResponse`, which streams the file from disk in small pieces and answers HTTP range requests with `206 Partial Content`, so pdf.js loads only the pages it shows. CORS exposes `Accept-Ranges` and `Content-Range` so pdf.js can read them (without them it falls back to downloading the whole file), and PDF responses are never gzipped, which would break ranges.

**Frontend:** each game's page has a Rulebooks section (open in the viewer, rename, delete, add); the `/rulebooks` page lists every rulebook in the library with the same actions plus moving to another game.

**Ingestion and reindexing**
- Ingestion runs once per rulebook; chat only embeds the question. The embedding and reranker models load once at backend startup.
- `just reindex [--game <id>]` re-runs parse → chunk → embed from the stored PDFs, for one game or all, after a chunker or embedding change. Each rulebook's chunks are replaced in one transaction, so a failure keeps the old chunks.

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
  1. vector search: top 30 by cosine similarity (with the BGE query prefix, HNSW index)
  2. keyword search: top 30 by Postgres full-text rank (`websearch_to_tsquery`)
  3. Reciprocal Rank Fusion (k = 60), keep the top 20
  4. rerank with `bge-reranker-base`, send the top 5 to the LLM, each shown as `[<Game name> (base game | expansion) › <section path>, p. X–Y]` followed by its text; the name comes from a join, so it's always current

  All four counts are settings in `config.py`, so the evaluation can compare values.
- **`ask_user(question, options[])`:** the `clarify` node calls `interrupt({question, options})`. The state is checkpointed, so a waiting question survives a backend restart. The UI shows the options as chips; `/resume` writes `game_id` and `expansion_ids` into the state and returns the answer to the agent. `clarify` does nothing before `interrupt()`, because LangGraph reruns the node from the start on resume.
- **`offer_web_search(query)`:** only after `search_rules` came back weak (top rerank score below a threshold in `config.py`) and the agent has said the rulebook doesn't cover the question. `confirm_web` interrupts with "Search the web" / "No thanks". On yes, `web_answer` calls `LLMProvider.web_search` and writes an answer labelled "From the web, not your rulebook", with a `web_sources` event and never mixed with page citations. The prompt prefers official sources (publisher FAQ or errata, designer answers) and says when sources disagree. Not offered when `web_search_enabled` is off.

**Agent rules:** ask first when the game is unknown or ambiguous, or when the answer could depend on expansions. The resolved scope stays in the state, so follow-ups don't ask again. Answers use only retrieved chunks and cite them as `[p. 12]`; citations open the PDF viewer at that page. When an expansion rule overrides a base rule, the answer says so. When the rulebook doesn't cover the question, the agent says so instead of guessing. When the chosen game has no ready rulebook, it says so instead of searching.

## LLM cost and prompts

- Prompts are laid out for OpenAI's automatic prompt caching: the system prompt and tool definitions come first and never change between calls, and the conversation is append-only. History is never trimmed or rewritten, so the full context is kept and every resent part is billed at the cached-input rate.
- Real cost per trace is checked in LangSmith, and a spending limit is set in the OpenAI dashboard.
- LangSmith runs are tagged with the route, game ID and conversation ID (used as LangSmith's thread), so each chat message is one trace tree.

## Evaluation

- `backend/eval/` holds a golden dataset of about 30–50 questions with expected pages, from 2–3 freely available rulebooks.
- **Retrieval (no LLM, free):** Recall@k, MRR and nDCG, comparing vector-only, full-text-only, hybrid, and hybrid + reranker.
- **Answers (LLM-as-judge):** faithfulness, correctness and citation accuracy, plus clarification behaviour (asks when it should, stays quiet when it shouldn't) and a few out-of-scope questions (declines, then offers web search only for those).
- **Routing:** about 40 labelled messages, including tricky ones; accuracy and a confusion matrix.
- Results go into a Markdown report, and the README shows the results table.
- `eval.yml` runs the retrieval eval nightly and on demand. The routing and answer evals spend OpenAI credit, so they run on demand only, and are skipped when the `OPENAI_API_KEY` secret isn't set. Locally, `just eval` runs retrieval only and `just eval --all` runs all three.

## Testing strategy

Tests are written with each feature, not at the end. A milestone is done only when its tests pass, CI is green and coverage is at least 80%. A bug gets a regression test before its fix.

**Backend**
- **Unit tests:** the chunker on hand-built element lists, prefixes, RRF, prompt building, schema validation, `GameFilter` → SQL with relaxation, the expansion rules, and graph tests with `InMemorySaver` and `FakeLLMProvider` (each route, the step limit, interrupt and resume, scope changes, and web search yes, no and turned off).
- **Integration tests:** a testcontainers pgvector database; the API through httpx `AsyncClient` (including message → interrupt → resume with the Postgres checkpointer; rulebook uploads, where every rejection leaves no row and no file; moving and deleting rulebooks; range requests on the file; reindex transactions); ingestion and retrieval on small fixture PDFs with different layouts (single column, two columns with sidebars, a scanned page).
- **Guard against real LLM calls:** pytest's environment forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and turns LangSmith off; `pytest-socket` blocks all network access except localhost. A test that reaches for OpenAI fails instead of spending credit.
- **Live tests:** a few tests marked `live`, one per real call type, check that OpenAI accepts the strict schemas and tool definitions. They're skipped by default and run with `just test-live`.
- **Real models only where needed:** unit tests use a `FakeEmbedder` and no reranker; only the ingestion and retrieval integration tests load the BGE models and Docling.

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

  From milestone 4, the backend and e2e jobs restore a cache of the Hugging Face and Docling models.

## Milestones

**Phase 0: Scaffold**
1. The monorepo, tooling and CI, working end to end before any features: the backend with `/api/health` and the first migration, the frontend health page using the generated types, Storybook, Vitest, Playwright, Docker Compose, `just`, pre-commit, CI and these docs.

**Phase A: Engine (backend only)**

2. **Games data and API:** models and migrations (expansion rules, unique `sha256`) and `/api/games`. Tests: the testcontainers fixture with per-test rollback, CRUD, expansion validation, cascading deletes, `sha256` uniqueness.
3. **Rulebooks API:** adding a rulebook to a game (size limit, PyMuPDF check and page count, the duplicate check, file storage), listing all and per game, rename and move, delete with its file, serving the file with range requests, and deleting a game's files with the game. No LLM yet. Tests: every rejection leaving no row and no file, a failed commit removing the written file, duplicates across games, rename and move, delete removing the file, a range request returning 206, game deletion removing files.
4. **Ingestion:** the Docling parser, the chunker, prefixes, the embedder, the parse report, the background job and status endpoint, moving a rulebook updating its chunks, `just reindex` and `just add-rulebook`. Tests: every chunker rule, the fake embedder, the three layout fixtures, parse report flags, transactional reindex, job status, a move updating chunks.
5. **Retrieval and evaluation:** hybrid search, RRF, the reranker, the golden dataset and retrieval metrics; tune the chunker and candidate counts. Tests: RRF, scoping to the chosen game, reranker ordering, current game names.
6. **Chat graph:** `LLMProvider` (OpenAI and fake) with `web_search`, LangSmith tracing from this first LLM call on, `just test-live`, state, the graph with the Postgres checkpointer, router, recommendation nodes, the agent loop, both interrupts, `web_answer`, the chat API with SSE, the routing and answer evals, and `just chat`. Tests: graph tests, filter relaxation, SSE mapping, API interrupt and resume, separate conversation state, live tests.

**Engine checkpoint:** `just test`, `just eval` and real conversations with `just chat`, checked in LangSmith. After this the API is fixed, so the frontend is built against a stable contract.

**Phase B: Frontend**

7. **App shell and API layer:** layout and navigation, regenerated types, server and browser fetch clients, TanStack Query, and MSW handlers for every endpoint.
8. **Games and rulebooks pages:** game list, detail (with its Rulebooks section), edit and delete; the Add game form with several PDFs and a result per file; the `/rulebooks` page; the PDF viewer; ingestion status. Tests: stories, form tests (mixed upload results, retry, a same-game duplicate counting as saved), Playwright flows.
9. **Chat UI:** the SSE client, streaming, route badge, clarification chips, scope selector, citations that open the PDF viewer, recommendation cards, labelled web answers, and the conversation sidebar. Tests: stories, stream rendering, Playwright chat flows.

**Phase C: Hardening**

10. Error and empty states, coverage gaps, flaky-test cleanup, and the README (architecture diagram, demo GIF, eval table). Stretch goals: re-parse flagged pages with a vision model; offer to link unlinked expansions when their base game is added.
