# Architecture

Board Game Assistant is a local-only web app that answers questions about the rules of your board games, using the rulebooks you upload. This document describes its design: what it does, how it's built, and why. It changes when a design decision changes; progress is tracked in `CLAUDE.md`, not here.

## What it does

1. **Add a game.** Upload a rulebook PDF. The system reads it and fills in the game's details (name, description, player count, play time, age, genres, publisher, year), detects whether the game is an expansion of another game, and fills details the rulebook doesn't mention from a web search. You review the form and save.
2. **Manage games.** List, view, edit and delete the games in your library.
3. **Chat.** Ask for recommendations from your library ("a co-op game for 5 players under an hour"), answered with a database query. Or ask rules questions ("can I trade on someone else's turn?"), answered from the rulebook with page citations. When the game or expansion isn't clear, the assistant asks before answering. When the rulebook doesn't cover a question, it offers to search the web, and labels those answers as web results.

There is no authentication: it's a single-user app that runs on one machine.

## Tech stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript | Server Components render the game list and detail pages; Server Actions handle create, edit and delete with `revalidatePath`; Client Components handle upload, polling and chat |
| UI | Tailwind CSS v4 + shadcn/ui (Base UI, Lucide icons, Geist font) | Accessible components that live in the repo and can be edited |
| Component workshop | Storybook (`@storybook/nextjs-vite`) with the MSW, a11y and Vitest addons | Every UI state (loading, error, low-confidence fields, streaming, clarification) can be built and tested in isolation |
| Client data | TanStack Query (Client Components only) | Draft upload, ingestion status polling, conversation history |
| Forms | react-hook-form + zod | The editable form that the PDF fills in |
| PDF viewer | react-pdf, loaded with `next/dynamic` and `ssr: false` | Clicking a citation opens the rulebook at that page |
| Chat streaming | The browser connects directly to FastAPI's Server-Sent Events (CORS allows `localhost:3000`) | Avoids Next.js rewrites buffering the stream |
| API types | `openapi-typescript` generated from FastAPI's OpenAPI schema, called through `openapi-fetch` | End-to-end type safety; CI fails if the committed types are out of date |
| Backend | Python 3.12 (pinned with uv) + FastAPI + Pydantic v2 | 3.12 is supported by every ML dependency; uv installs it and locks every package |
| Database | PostgreSQL 16 + pgvector + pg_trgm (Docker) | One store for relational data, vectors, full-text search and fuzzy name matching |
| ORM / migrations | SQLAlchemy 2.0 (async, psycopg 3) + Alembic | psycopg 3 is also the driver the LangGraph checkpointer uses, so there's one Postgres driver. The checkpointer creates its own tables with `.setup()` at startup, outside Alembic |
| PDF parsing | Docling for ingestion; PyMuPDF for the fast upload autofill | Rulebooks vary a lot in fonts, columns, sidebars and tables. Docling finds structure from the page layout, gives the correct reading order and tables, drops headers and footers, and runs OCR on scanned pages, locally on the GPU. PyMuPDF reads the first pages in under a second |
| Embeddings | `BAAI/bge-base-en-v1.5` via sentence-transformers (768 dimensions; GPU, or CPU as a fallback) | Free, local and offline. Its 512-token input limit caps chunks at about 450 tokens (counted with the BGE tokenizer). Queries get the BGE query prefix and chunks don't; vectors are normalised and compared by cosine similarity |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | Better precision for rules lookups |
| LLM | OpenAI (official `openai` SDK) behind a small `LLMProvider` interface with two implementations, `openai` and `fake` | Structured outputs with Pydantic models, function calling and streaming. Two model names are defaults in `config.py`: `chat_model` (rules agent, recommendation answers) and `fast_model` (router, metadata and filter extraction). `.env` holds only secrets and switches. The fake provider keeps tests and CI deterministic, with no API key |
| Web search | OpenAI's built-in web search tool (Responses API), exposed as `LLMProvider.web_search(query) → {answer, sources[]}` | Fills missing metadata at upload, and answers rules questions the rulebook doesn't cover (only after the user agrees). No extra vendor or key. `web_search_enabled` in `config.py` turns both off |
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
│  │  ├─ cli.py           add-game, chat and reindex commands for using the engine from a terminal
│  │  ├─ tracing.py       LangSmith setup: wrapped OpenAI client, run metadata helpers
│  │  ├─ api/             health.py, games.py, rulebooks.py, chat.py, deps.py
│  │  ├─ db/              session.py, models.py
│  │  ├─ schemas/         Pydantic request and response models
│  │  ├─ llm/             base.py (LLMProvider protocol), openai.py, fake.py
│  │  ├─ ingestion/       quick_text.py (PyMuPDF), layout_parser.py (Docling → typed elements),
│  │  │                   chunker.py, embedder.py, quality.py (parse report), pipeline.py, jobs.py
│  │  ├─ extraction/      metadata.py (PDF → GameDraft), web_fill.py (web search → missing fields)
│  │  ├─ retrieval/       hybrid.py (vector + full-text, RRF), reranker.py
│  │  └─ chat/            state.py, graph.py, prompts.py, streaming.py (graph stream → SSE events)
│  │                      nodes/ router.py, recommend.py, rules_agent.py, tools.py, clarify.py,
│  │                             reply.py, web_answer.py
│  ├─ eval/               golden datasets, run_eval.py, reports/
│  ├─ data/uploads/       uploaded rulebook PDFs (gitignored; mounted into the backend container)
│  └─ tests/              unit/, integration/, fixtures/ (small sample PDFs)
├─ frontend/
│  ├─ src/                all frontend code (the @/ import alias points here)
│  │  ├─ app/             routes: games/, games/[id]/, games/[id]/edit/, games/new/, chat/, chat/[conversationId]/
│  │  ├─ components/ui/   shadcn components
│  │  ├─ features/        health/, games/, upload/, chat/ (stories and tests next to each component)
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

- **Game:** id, name, description, min/max players, min age, min/max play time (minutes), genres[], publisher, year, `is_expansion`, `base_game_id` (the expansion's base game; null for base games and for expansions whose base game isn't in the library), timestamps. A base game can't have a `base_game_id`, an expansion's base game must itself be a base game (one level only), and a game that has expansions can't become an expansion. Deleting a base game unlinks its expansions (`ON DELETE SET NULL`) instead of deleting them.
- **Rulebook:** id, game_id, filename, storage_path, page_count, `sha256` (unique; catches duplicate uploads), `status` (`uploaded` → `processing` → `ready` / `failed`), error, `parse_report` JSON (chunk count, pages with little text or mostly images).
- **Chunk:** id, rulebook_id, game_id, `section_path` ("Setup > Market"), `chunk_type` (`section` / `table` / `glossary` / `faq`), page_start, page_end, content (prefixed with its section path, never the game name, so renaming a game needs no re-embedding), `tsv` (tsvector, GIN index), `embedding vector(768)` (HNSW index).
- **Conversation:** id (also LangGraph's `thread_id`), title (the first message cut to about 60 characters, no LLM call; renamable), created_at, updated_at. Used to list chats in the sidebar.
- **Conversation state** is not one of our tables: the LangGraph checkpointer stores messages, citations, the resolved game and expansions, and any pending interrupt.

Modelling expansions as child games lets chat scope retrieval to a base game plus any chosen subset of its expansions.

## Flow 1: Add a game

1. **Draft.** `POST /api/rulebooks/draft` (multipart PDF).
   - The backend hashes the PDF. If the `sha256` matches a stored rulebook, it returns `{duplicate_of: {game_id, name}}` immediately, with no parsing and no LLM call.
   - Otherwise it stores the file under `backend/data/uploads/`, reads the plain text of the first ~6 pages with PyMuPDF, and sends that text and the table of contents to the LLM with a strict `GameDraft` schema.
   - It returns `{draft_id, fields, confidence per field, base_game_candidates}`.
2. **Expansion detection.** `GameDraft` includes `is_expansion` (with confidence), `base_game_name` and `evidence` (the sentence that shows it, e.g. "Requires the Catan base game to play"). When it's an expansion, the backend fuzzy-matches `base_game_name` against the library's base games with pg_trgm and returns the top candidates. The form then shows one of:
   - one clear match, preselected with the evidence sentence underneath
   - several close matches to choose from
   - a warning that the base game isn't in the library yet (add it first, or save the expansion unlinked and link it later)
   - nothing, when it isn't an expansion (it can still be set by hand)
3. **Web fill.** When fields are empty or low-confidence, the frontend calls `POST /api/rulebooks/draft/{draft_id}/web-fill` automatically, and the form stays usable while it runs.
   - One web search, extracted into the same `GameDraft` schema.
   - It only fills empty or low-confidence fields, never values from the PDF or typed by the user. When expansion detection was unsure, the same search checks that too.
   - One dismissible alert above the form names the filled fields and lists the source links. With `web_search_enabled` off, the alert says which fields are still empty.
4. **Save and ingest.** `POST /api/games {draft_id, ...fields}` creates the game and starts the background ingestion job:
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
5. **Status.** The UI polls `GET /api/rulebooks/{id}/status` and shows a progress badge. When ingestion finishes, the game page shows any parse warnings.

## Flow 2: Manage games

- `GET /api/games` (search and filter); `GET/PATCH/DELETE /api/games/{id}`. Deleting cascades to rulebooks and chunks and removes the stored file.
- `POST /api/games/{id}/rulebooks` adds or replaces a rulebook and re-ingests it.
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

- **`find_games(query)`:** pg_trgm fuzzy matching; returns candidate base games and their expansions.
- **`search_rules(game_id, expansion_ids[], query)`:** hybrid retrieval scoped to the selected game and expansions:
  1. vector search: top 30 by cosine similarity (with the BGE query prefix, HNSW index)
  2. keyword search: top 30 by Postgres full-text rank (`websearch_to_tsquery`)
  3. Reciprocal Rank Fusion (k = 60), keep the top 20
  4. rerank with `bge-reranker-base`, send the top 5 to the LLM, each shown as `[<Game name> (base game | expansion) › <section path>, p. X–Y]` followed by its text; the name comes from a join, so it's always current

  All four counts are settings in `config.py`, so the evaluation can compare values.
- **`ask_user(question, options[])`:** the `clarify` node calls `interrupt({question, options})`. The state is checkpointed, so a waiting question survives a backend restart. The UI shows the options as chips; `/resume` writes `game_id` and `expansion_ids` into the state and returns the answer to the agent. `clarify` does nothing before `interrupt()`, because LangGraph reruns the node from the start on resume.
- **`offer_web_search(query)`:** only after `search_rules` came back weak (top rerank score below a threshold in `config.py`) and the agent has said the rulebook doesn't cover the question. `confirm_web` interrupts with "Search the web" / "No thanks". On yes, `web_answer` calls `LLMProvider.web_search` and writes an answer labelled "From the web, not your rulebook", with a `web_sources` event and never mixed with page citations. The prompt prefers official sources (publisher FAQ or errata, designer answers) and says when sources disagree. Not offered when `web_search_enabled` is off.

**Agent rules:** ask first when the game is unknown or ambiguous, or when the answer could depend on expansions. The resolved scope stays in the state, so follow-ups don't ask again. Answers use only retrieved chunks and cite them as `[p. 12]`; citations open the PDF viewer at that page. When an expansion rule overrides a base rule, the answer says so. When the rulebook doesn't cover the question, the agent says so instead of guessing.

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
- **Integration tests:** a testcontainers pgvector database; the API through httpx `AsyncClient` (including message → interrupt → resume with the Postgres checkpointer, duplicate uploads, reindex transactions and `/web-fill`); ingestion and retrieval on small fixture PDFs with different layouts (single column, two columns with sidebars, a scanned page).
- **Guard against real LLM calls:** pytest's environment forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and turns LangSmith off; `pytest-socket` blocks all network access except localhost. A test that reaches for OpenAI fails instead of spending credit.
- **Live tests:** a few tests marked `live`, one per real call type, check that OpenAI accepts the strict schemas and tool definitions. They're skipped by default and run with `just test-live`.
- **Real models only where needed:** unit tests use a `FakeEmbedder` and no reranker; only the ingestion and retrieval integration tests load the BGE models and Docling.

**Frontend**
- Vitest + React Testing Library + MSW for components and the API client.
- A Storybook story for every component state; story tests run interaction and a11y checks (violations fail the test), sharing MSW handlers with the unit tests.

**End-to-end**
- Playwright against the app with the fake LLM, so it's deterministic and needs no API key: the game CRUD flow, a chat that asks for clarification and then cites a page, a recommendation request, and an out-of-scope question answered from the web.

## Development and delivery

- **Two ways to run:** day-to-day development runs the backend and frontend on the host with hot reload (`just dev`), with only Postgres in Docker. `just up` runs all three as containers, which is what CI's e2e job uses.
- **Images:**
  - The backend image installs locked dependencies in a cached layer, then copies the code; at start it runs `alembic upgrade head`, then `exec uvicorn`.
  - The frontend image is a two-stage build of Next.js's standalone output. `NEXT_PUBLIC_API_URL` is a build argument, because it's inlined into the browser bundle at build time.
- **Compose:** `depends_on` with healthchecks orders startup (db → backend → frontend); the backend's healthcheck calls `/api/health`, so it's unhealthy whenever the database is unreachable.
- **just** is the single entry point for every command, locally and in CI.
- **pre-commit** runs Ruff, Prettier and ESLint as local hooks, using the exact tool versions in the lock files, plus YAML and large-file checks.
- **CI (`ci.yml`)** runs four jobs on every pull request and every push to `main`:
  1. **backend:** `uv sync --locked`, Ruff, mypy, migrations on a fresh pgvector service container, pytest with coverage
  2. **frontend:** `npm ci`, ESLint, Prettier, tsc, Vitest (unit and story tests), the Next.js build and the Storybook build
  3. **contract:** regenerate the OpenAPI schema and TypeScript types and fail if they differ from the committed ones
  4. **e2e:** start the app in containers, run Playwright, and on failure print container logs and upload traces

  From milestone 4, the backend and e2e jobs restore a cache of the Hugging Face and Docling models.

## Milestones

**Phase 0: Scaffold**
1. The monorepo, tooling and CI, working end to end before any features: the backend with `/api/health` and the first migration, the frontend health page using the generated types, Storybook, Vitest, Playwright, Docker Compose, `just`, pre-commit, CI and these docs.

**Phase A: Engine (backend only)**

2. **Games data and API:** models and migrations (expansion rules, unique `sha256`) and `/api/games`. Tests: the testcontainers fixture with per-test rollback, CRUD, expansion validation, cascading deletes, `sha256` uniqueness.
3. **Upload and autofill:** quick PDF text, `LLMProvider` (OpenAI and fake) with `web_search`, LangSmith tracing, metadata extraction with expansion detection, base game matching, the duplicate check, `/draft` and `/web-fill`. Tests: scripted fake outputs, candidate matching, web fill only touching empty fields, duplicates without an LLM call, live tests.
4. **Ingestion:** the Docling parser, the chunker, prefixes, the embedder, the parse report, the background job and status endpoint, rulebook replacement, `just reindex` and `just add-game`. Tests: every chunker rule, the fake embedder, the three layout fixtures, parse report flags, transactional reindex, job status.
5. **Retrieval and evaluation:** hybrid search, RRF, the reranker, the golden dataset and retrieval metrics; tune the chunker and candidate counts. Tests: RRF, scoping to the chosen game, reranker ordering, current game names.
6. **Chat graph:** state, the graph with the Postgres checkpointer, router, recommendation nodes, the agent loop, both interrupts, `web_answer`, the chat API with SSE, the routing and answer evals, and `just chat`. Tests: graph tests, filter relaxation, SSE mapping, API interrupt and resume, separate conversation state, live tests.

**Engine checkpoint:** `just test`, `just eval` and real conversations with `just chat`, checked in LangSmith. After this the API is fixed, so the frontend is built against a stable contract.

**Phase B: Frontend**

7. **App shell and API layer:** layout and navigation, regenerated types, server and browser fetch clients, TanStack Query, and MSW handlers for every endpoint.
8. **Games pages:** list, detail, edit and delete; the upload and review form (autofill, expansion picker, duplicate notice, web-fill alert); ingestion status. Tests: stories, form tests, Playwright CRUD.
9. **Chat UI:** the SSE client, streaming, route badge, clarification chips, scope selector, citations that open the PDF viewer, recommendation cards, labelled web answers, and the conversation sidebar. Tests: stories, stream rendering, Playwright chat flows.

**Phase C: Hardening**

10. Error and empty states, coverage gaps, flaky-test cleanup, and the README (architecture diagram, demo GIF, eval table). Stretch goals: re-parse flagged pages with a vision model; offer to link unlinked expansions when their base game is added.
