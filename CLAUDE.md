# Board Game Assistant

A local-only RAG app: upload board game rulebooks, then ask rules questions with page citations or get recommendations from your library. Next.js frontend, FastAPI backend, Postgres + pgvector, OpenAI, LangGraph.

The design (stack and reasons, data model, flows, chat graph, RAG pipeline, testing strategy, milestones) is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Read the relevant section before starting a milestone, and update it in the same change when a design decision changes.

## Structure

- `backend/`: FastAPI app (`app/`), Alembic migrations, pytest tests. Python 3.12 managed by uv; run backend commands from this folder.
- `frontend/`: Next.js app; all code under `src/` (import with `@/`). Stories and tests sit next to their component; MSW handlers in `src/mocks/` are shared by Storybook, Vitest and dev.
- `justfile` (root): every development command. `docker-compose.yml`: db, backend, frontend.

## Commands

Run `just` to list everything. The main ones:

- `just dev`: Postgres in Docker plus both dev servers with reload. `just db` starts only Postgres.
- `just up` / `just down`: the whole app in containers / remove the containers (data is kept in the `pgdata` volume).
- `just lint`, `just format`, `just test`, `just e2e`: also available per side, e.g. `just test-backend`.
- `just migrate`: apply Alembic migrations.
- `just gen-types`: regenerate `frontend/openapi.json` and `frontend/src/api/schema.d.ts` from the backend. Run it after any API change; CI's contract job fails if they're stale.

## Conventions

- Tests are written with each feature. A milestone is done only when its tests pass, CI is green and backend coverage stays at or above 80%. A bug gets a regression test first.
- Tests never call real services: pytest forces `LLM_PROVIDER=fake`, clears `OPENAI_API_KEY` and blocks the network except localhost (see `[tool.pytest.ini_options]` in `backend/pyproject.toml`). Tests that need real OpenAI are marked `live` and only run with `just test-live`.
- Model names and tunables live in `backend/app/config.py`; `.env` holds only secrets and switches.
- Prompts are append-only: static system prompt and tools first, history never trimmed or rewritten (for OpenAI prompt caching).
- Chunk text is prefixed with its section path only, never the game name.
- The frontend calls the backend only through the typed client in `frontend/src/api/client.ts`.
- New engine commands (`test-live`, `add-game`, `reindex`, `eval`, `chat`) are added to the `justfile` in the milestone that builds them.
- Commits follow Conventional Commits. Update the Progress section below at the end of every milestone, in that milestone's commit.

## Gotchas

- Windows + async psycopg needs the selector event loop: uvicorn runs with `--loop asyncio:SelectorEventLoop` (`just dev-backend`), and `backend/alembic/env.py` passes `loop_factory`. Containers and CI are Linux and don't need it.
- `NEXT_PUBLIC_` variables are inlined at build time; changing `NEXT_PUBLIC_API_URL` for the container means rebuilding the frontend image (a build arg in `docker-compose.yml`).
- The justfile uses PowerShell 5.1 on Windows (no `&&`) and `sh` on Linux: keep recipe lines to one plain command each, and use `[working-directory]` instead of `cd`.
- `astral-sh/setup-uv` publishes no floating major tag; pin an exact version in `.github/workflows/ci.yml`.
- Compose needs v2.24+ (`env_file` with `required: false`).

## Progress

**Current:** milestone 2 (games data and API).

**Done:**
- Milestone 1, scaffold: backend health check with DB status, first migration (pgvector, pg_trgm), test guards and coverage; frontend health page with generated types, Storybook (MSW, a11y, Vitest), Vitest unit tests, Playwright smoke test; Dockerfiles and compose; justfile; pre-commit; CI with backend, frontend, contract and e2e jobs.

**Open notes:**
- Milestone 2: configure pytest-asyncio to use the selector event loop on Windows before the first real-DB test; add testcontainers and real-DB tests for `database_is_reachable` in `backend/app/db/session.py`.
- Milestone 3: create `backend/app/tracing.py` with the first LLM call; add `just test-live`.
- Milestone 4: add the Hugging Face and Docling model cache to the CI backend and e2e jobs.
- Milestone 7: the health status becomes a banner shown only on problems, with an adaptive polling interval and a request timeout; add a server-side API URL (`http://backend:8000` in compose) once Server Components call the API.
- Milestone 8: e2e tests start writing data, so local `just e2e` should run against a throwaway stack (own compose project, no volume) instead of the dev database; otherwise junk accumulates and the `sha256` duplicate check fails on re-runs.
- Phase B: add `error.tsx` boundaries; decide whether to enable `cacheComponents`.
