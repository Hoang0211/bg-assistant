# Board Game Assistant

A local-only RAG app: add board games with their rulebook PDFs, then ask rules questions with page citations or get recommendations from your library. Next.js frontend, FastAPI backend, Postgres + pgvector, OpenAI, LangGraph.

The design (stack and reasons, data model, flows, chat graph, RAG pipeline, testing strategy, milestones) is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Read the relevant section before starting a milestone, and update it in the same change when a design decision changes.

## Structure

- `backend/`: FastAPI app (`app/`), Alembic migrations, pytest tests. Python 3.12 managed by uv; run backend commands from this folder.
- `frontend/`: Next.js app; all code under `src/` (import with `@/`). Stories and tests sit next to their component; MSW handlers in `src/mocks/` are shared by Storybook, Vitest and dev.
- `justfile` (root): every development command. `docker-compose.yml`: db, backend, frontend.

## Commands

Run `just` to list everything. The main ones:

- `just dev`: Postgres in Docker plus both dev servers with reload. `just db` starts only Postgres.
- `just up` / `just down`: the whole app in containers / remove the containers (the database and the downloaded models are kept in volumes).
- `just lint`, `just format`, `just test`, `just e2e`: also available per side, e.g. `just test-backend`.
- `just migrate`: apply Alembic migrations. After a model change, run `uv run alembic revision --autogenerate -m "..."` against a migrated dev database and check the file; a test (`alembic check`) fails until the migration exists.
- `just gen-types`: regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` from the backend. Run it after any API change; CI's contract job fails if they're stale.

## Conventions

- Tests are written with each feature. A milestone is done only when its tests pass, CI is green and backend coverage stays at or above 80%. A bug gets a regression test first.
- Tests never call real services: pytest forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and blocks the network except localhost (see `[tool.pytest.ini_options]` in `backend/pyproject.toml`). Tests that need real OpenAI are marked `live` and only run with `just test-live`.
- Database tests live in `backend/tests/integration/` and use the `db_session` fixture (or `api_client` for HTTP), whose changes are rolled back after each test. They need Docker running: testcontainers starts a throwaway pgvector container, never the dev database.
- Services raise the error kinds in `backend/app/errors.py` (subclass `NotFoundError`, `RuleViolationError` or `TooLargeError`), never `HTTPException`, so the CLI can reuse them; `backend/app/api/error_handlers.py` maps each kind to one status code.
- Routes in each `backend/app/api/` file, and their API tests, are grouped by URL in the order `/docs` shows them, and within a URL go GET, POST, PATCH, DELETE. Within each route's tests, success comes first, then errors by status code.
- In each module, a private helper (`_name`) sits right above the first function that uses it; entry points (`main`, `_main`) go last.
- Model names and tunables live in `backend/app/config.py`; `.env` holds only secrets and switches.
- Prompts are append-only: static system prompt and tools first, history never trimmed or rewritten (for OpenAI prompt caching).
- Chunk text is prefixed with its section path only, never the game name.
- sentence-transformers and PyTorch take seconds to import, so keep them off the app's startup path: shared types live in modules that import no heavy library, code that needs the embedder gets it passed in (created in the lifespan or the CLI), and `BgeEmbedder.__init__`, the one place that loads it, imports it inside the function. A test checks that importing `app.main` loads neither.
- The frontend calls the backend only through the typed client in `frontend/src/api/client.ts`.
- New engine commands (`test-live`, `reindex`, `eval-ingest`, `eval`, `eval-text`, `eval-answers`, `chat`) are added to the `justfile` in the milestone that builds them.
- `main` is protected: every change goes through a pull request from a feature branch (e.g. `feat/games-api`), needs all four CI checks green, and is squash-merged. Pull request titles follow Conventional Commits, because they become the commit messages on `main`.
- Update the Progress section below in the pull request that finishes each milestone.

## Gotchas

- Windows + async psycopg needs the selector event loop: uvicorn runs with `--loop asyncio:SelectorEventLoop` (`just dev-backend`), and `backend/alembic/env.py` passes `loop_factory`. Containers and CI are Linux and don't need it.
- `NEXT_PUBLIC_` variables are inlined at build time; changing `NEXT_PUBLIC_API_URL` for the container means rebuilding the frontend image (a build arg in `docker-compose.yml`).
- The justfile uses PowerShell 5.1 on Windows (no `&&`) and `sh` on Linux: keep recipe lines to one plain command each, and use `[working-directory]` instead of `cd`.
- `astral-sh/setup-uv` publishes no floating major tag; pin an exact version in `.github/workflows/ci.yml`.
- Compose needs v2.24+ (`env_file` with `required: false`).
- Async sessions can't lazy-load: reading an expired attribute raises `MissingGreenlet`. `Base` in `backend/app/db/models.py` sets `eager_defaults=True` so database-computed values (like `updated_at`) come back with `RETURNING`; load relationships explicitly.
- pytest runs with `HF_HUB_OFFLINE=1`, so the embedding model must already be downloaded: run `just download-models` once. Otherwise the embedder and ingestion tests fail because the model isn't found.

## Progress

**Current:** milestone 6 (chat graph).

**Done:**
- Milestone 1, scaffold: backend health check with DB status, first migration (pgvector, pg_trgm), test guards and coverage; frontend health page with generated types, Storybook (MSW, a11y, Vitest), Vitest unit tests, Playwright smoke test; Dockerfiles and compose; justfile; pre-commit; CI with backend, frontend, contract and e2e jobs.
- Milestone 2, games data and API: `Game` and `Rulebook` models with CHECK constraints and their migrations; a games service with the expansion rules; `/api/games` CRUD with name, player, genre and base-game filters; error kinds mapped to 404 and 422; real-database tests with testcontainers and per-test rollback, for models, service and API.
- Milestone 3, rulebooks API: rulebooks managed apart from games (several per game, or none); PDF uploads checked for size (413), duplicates across the library by `sha256` (422 with `duplicate_of`) and readability with PyMuPDF, which also reads the page count; files stored as `{sha256}.pdf`, written before the row and removed after a delete commits; list, rename, move and delete; the file download with range requests for the PDF viewer; service and API tests.
- Milestone 4, ingestion: the Docling parse in a child process (retried up to `parse_attempts`, stopped after `parse_timeout_seconds`), with OCR only on pages under `ocr_min_page_chars`; the rulebook-aware chunker (heading splits, small-section merges, long-section splits with overlap, paragraphs joined across page breaks, tables, glossaries, dropped credits); section-path prefixes; the BGE embedder, loaded on the first job; the parse report on each rulebook; a background worker with an in-memory queue that re-queues unfinished rulebooks on startup; one transaction per rulebook, so a failure keeps the old chunks; `just reindex`; progress logs; `just download-models` and the model caches in compose and CI; tests for every chunker rule, single-column, two-column and scanned fixtures run end to end, and a guard that app startup loads no heavy library.
- Milestone 5a, retrieval and evaluation: hybrid search (vector search, full-text search matching any of the question's words, Reciprocal Rank Fusion) scoped to a game's family, with current game names from a join; a BGE cross-encoder reranker behind `search()`, on trial until 5b; the eval database (`just eval-ingest`, built from `eval/library.json` and the git-ignored PDFs); 30 golden questions; Recall@5, MRR and nDCG@5 for hybrid and reranked search side by side (`just eval`), with committed reports; small sections merge only within a page; `traverse_pictures=True` and other candidate counts tried and left out; tests for the search, the reranker, the metrics, the report and the chunker rule.
- Milestone 5b, LLM parser: an `LLMProvider` (OpenAI's Responses API and a fake, with structured outputs) and `just test-live`; a page parser that writes each page as Markdown from its image (`gpt-6.1-terra`), stored on the rulebook and reused unless `--reparse`, with the OpenAI provider created on first use so the app starts without a key; a Markdown reader into the same elements (heading paths from levels, bold lines as captions kept with their table); `just eval-text` (word recall and precision against the text layer) and `just eval-answers` (answers graded by `gpt-6.1-sol`); a comparison with Docling, each parser in its own eval database, under a rule set before the answer check: the LLM parser stayed (29 against 28 answers found, 24 each answered correctly, picture text read), and Docling (with its child process, OCR settings and the `docling` and `torchvision` dependencies) and the reranker were removed, so search is hybrid search alone; tests for the parser contract, the reader, the provider created on first use, the reports and the judge.

**Open notes:**
- Milestone 6: pass the search settings into `hybrid_search` instead of reading `get_settings()`, so the eval report can't describe settings the search didn't use. The HNSW index (`ix_chunks_embedding`) isn't used by any query: `vector_search`'s `Chunk.id` tiebreaker keeps it exact, which a test guards. Keep the index only if recommendations search without a game filter; otherwise drop it. LangSmith tracing (`tracing.py`, the `langsmith` SDK) moved here from 5b: there's no LangSmith account yet, and the agent's graph is where tracing pays off. In the answer check, pepper-01's answer said "the excerpts don't cover this" with the right chunk ranked 2nd: check that chat's answer prompt isn't too strict.
- Milestone 7: the health status becomes a banner shown only on problems, with an adaptive polling interval and a request timeout; add a server-side API URL (`http://backend:8000` in compose) once Server Components call the API.
- Milestone 8: the forms validate with zod before sending, so the server's 422s are a backstop. They come in two shapes: FastAPI's list of `{loc, msg, type}` for body, query and path validation (merged PATCH errors have no `"body"` in `loc`), and `{"detail": "message"}` for rule violations, which the UI must show.
- Milestone 8: e2e tests start writing data, so local `just e2e` should run against a throwaway stack (own compose project, no volume) instead of the dev database; otherwise junk accumulates and the `sha256` duplicate check fails on re-runs.
- Milestone 8: once e2e uploads rulebooks, the e2e job needs the embedding model: restore the same CI cache and mount it into the backend container's `/root/.cache/huggingface` (a compose override), or every run downloads about 0.5 GB. Uploads are also parsed by the model, so the e2e stack needs `LLM_PROVIDER=fake` with a scripted page reply, or every upload fails to ingest.
- Milestone 8: the PDF viewer needs CORS `expose_headers` for `Accept-Ranges` and `Content-Range`, or pdf.js downloads the whole file instead of using range requests.
- Phase B: add `error.tsx` boundaries; decide whether to enable `cacheComponents`.
- Phase C: publish the static Storybook to GitHub Pages (a deploy job in CI) as a live demo link; it only uses MSW mock data.
