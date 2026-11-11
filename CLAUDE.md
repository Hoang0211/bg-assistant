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
- `just migrate`: apply Alembic migrations.
- `just gen-types`: regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` from the backend. Run it after any API change; CI's contract job fails if they're stale.

## Conventions

- Tests are written with each feature. A milestone is done only when its tests pass, CI is green and backend coverage stays at or above 80%. A bug gets a regression test first.
- Tests never call real services: pytest forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and blocks the network except localhost (see `[tool.pytest.ini_options]` in `backend/pyproject.toml`). Tests that need real OpenAI are marked `live` and only run with `just test-live`.
- Database tests live in `backend/tests/integration/` and use the `db_session` fixture (or `api_client` for HTTP), whose changes are rolled back after each test. They need Docker running: testcontainers starts a throwaway pgvector container, never the dev database.
- Services raise the error kinds in `backend/app/errors.py` (subclass `NotFoundError`, `RuleViolationError` or `TooLargeError`), never `HTTPException`, so the CLI can reuse them; `backend/app/api/error_handlers.py` maps each kind to one status code.
- Routes in each `backend/app/api/` file, and their API tests, are grouped by URL in the order `/docs` shows them, and within a URL go GET, POST, PATCH, DELETE. Within each route's tests, success comes first, then errors by status code.
- Model names and tunables live in `backend/app/config.py`; `.env` holds only secrets and switches.
- Prompts are append-only: static system prompt and tools first, history never trimmed or rewritten (for OpenAI prompt caching).
- Chunk text is prefixed with its section path only, never the game name.
- Docling and sentence-transformers take seconds to import, so keep them off the app's startup path: shared types live in modules that import no heavy library, code that needs the parser or embedder gets it passed in (created in the lifespan or the CLI), and the two places that load them, `parse_process._main` and `BgeEmbedder.__init__`, import them inside the function. A test checks that importing `app.main` loads neither.
- The frontend calls the backend only through the typed client in `frontend/src/api/client.ts`.
- New engine commands (`test-live`, `reindex`, `eval`, `chat`) are added to the `justfile` in the milestone that builds them.
- `main` is protected: every change goes through a pull request from a feature branch (e.g. `feat/games-api`), needs all four CI checks green, and is squash-merged. Pull request titles follow Conventional Commits, because they become the commit messages on `main`.
- Update the Progress section below in the pull request that finishes each milestone.

## Gotchas

- Windows + async psycopg needs the selector event loop: uvicorn runs with `--loop asyncio:SelectorEventLoop` (`just dev-backend`), and `backend/alembic/env.py` passes `loop_factory`. Containers and CI are Linux and don't need it.
- `NEXT_PUBLIC_` variables are inlined at build time; changing `NEXT_PUBLIC_API_URL` for the container means rebuilding the frontend image (a build arg in `docker-compose.yml`).
- The justfile uses PowerShell 5.1 on Windows (no `&&`) and `sh` on Linux: keep recipe lines to one plain command each, and use `[working-directory]` instead of `cd`.
- `astral-sh/setup-uv` publishes no floating major tag; pin an exact version in `.github/workflows/ci.yml`.
- Compose needs v2.24+ (`env_file` with `required: false`).
- Async sessions can't lazy-load: reading an expired attribute raises `MissingGreenlet`. `Base` in `backend/app/db/models.py` sets `eager_defaults=True` so database-computed values (like `updated_at`) come back with `RETURNING`; load relationships explicitly.
- pytest runs with `HF_HUB_OFFLINE=1`, so the models must already be downloaded: run `just download-models` once. Otherwise the parser and embedder tests fail because the model isn't found.
- Docling's OCR crashed at random on Windows with native heap corruption (`0xc0000374`, 9 of 33 runs) while the parse ran inside the API process, and `try/except` can't catch that. It hasn't happened in 99 runs since, with each parse in its own process as the app now does it, on the same library versions. The parse child is still retried up to `parse_attempts` times, in case it comes back.

## Progress

**Current:** milestone 5a (retrieval and evaluation).

**Done:**
- Milestone 1, scaffold: backend health check with DB status, first migration (pgvector, pg_trgm), test guards and coverage; frontend health page with generated types, Storybook (MSW, a11y, Vitest), Vitest unit tests, Playwright smoke test; Dockerfiles and compose; justfile; pre-commit; CI with backend, frontend, contract and e2e jobs.
- Milestone 2, games data and API: `Game` and `Rulebook` models with CHECK constraints and their migrations; a games service with the expansion rules; `/api/games` CRUD with name, player, genre and base-game filters; error kinds mapped to 404 and 422; real-database tests with testcontainers and per-test rollback, for models, service and API.
- Milestone 3, rulebooks API: rulebooks managed apart from games (several per game, or none); PDF uploads checked for size (413), duplicates across the library by `sha256` (422 with `duplicate_of`) and readability with PyMuPDF, which also reads the page count; files stored as `{sha256}.pdf`, written before the row and removed after a delete commits; list, rename, move and delete; the file download with range requests for the PDF viewer; service and API tests.
- Milestone 4, ingestion: the Docling parse in a child process (retried up to `parse_attempts`), with OCR only on pages under `ocr_min_page_chars`; the rulebook-aware chunker (heading splits, small-section merges, long-section splits with overlap, paragraphs joined across page breaks, tables, glossaries, dropped credits); section-path prefixes; the BGE embedder, loaded on the first job; the parse report on each rulebook; a background worker with an in-memory queue that re-queues unfinished rulebooks on startup; one transaction per rulebook, so a failure keeps the old chunks; `just reindex`; progress logs; `just download-models` and the model caches in compose and CI; tests for every chunker rule, single-column, two-column and scanned fixtures run end to end, and a guard that app startup loads no heavy library.

**Open notes:**
- Milestone 5a: write the golden questions before looking at any results, and include what the Docling parse got wrong on real rulebooks (checked 2026-11-11): text inside pictures is dropped (Catan p. 3's dice odds and beginner text, Extra Salt p. 4's colour legend); a small first section is merged under the next one's heading (Power Grid's "Goal" inside "Preparation"); short terms printed as headings are merged into neighbouring chunks (Catan's almanac); callout headings lose their context ("Important", "Example", "Step 2"); "Illustration Q" splits a sentence; Extra Salt pp. 2 and 4 hide copies of the previous page's text under shapes; merging across a page break makes citations broad (Extra Salt's chunk covers pp. 1–2). The first chunker change: never merge small sections across a page break. Also try `traverse_pictures=True` as a Docling variant: it keeps the text inside pictures, but also decorative text from illustrations.
- Milestone 5b: create `backend/app/tracing.py` with the first LLM call (the page parser); add `just test-live`.
- Milestone 7: the health status becomes a banner shown only on problems, with an adaptive polling interval and a request timeout; add a server-side API URL (`http://backend:8000` in compose) once Server Components call the API.
- Milestone 8: the forms validate with zod before sending, so the server's 422s are a backstop. They come in two shapes: FastAPI's list of `{loc, msg, type}` for body, query and path validation (merged PATCH errors have no `"body"` in `loc`), and `{"detail": "message"}` for rule violations, which the UI must show.
- Milestone 8: e2e tests start writing data, so local `just e2e` should run against a throwaway stack (own compose project, no volume) instead of the dev database; otherwise junk accumulates and the `sha256` duplicate check fails on re-runs.
- Milestone 8: once e2e uploads rulebooks, the e2e job needs the models: restore the same CI cache and mount it into the backend container's `/root/.cache/huggingface` (a compose override), or every run downloads about 1 GB.
- Milestone 8: the PDF viewer needs CORS `expose_headers` for `Accept-Ranges` and `Content-Range`, or pdf.js downloads the whole file instead of using range requests.
- Phase B: add `error.tsx` boundaries; decide whether to enable `cacheComponents`.
- Phase C: publish the static Storybook to GitHub Pages (a deploy job in CI) as a live demo link; it only uses MSW mock data.
