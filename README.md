# Board Game Assistant

[![CI](https://github.com/Hoang0211/bg-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/Hoang0211/bg-assistant/actions/workflows/ci.yml)

Ask questions about your board games' rules and get answers with page citations from the rulebooks you upload. A local-only, full-stack RAG app.

> **Status:** early development. The scaffold (tooling, tests, containers and CI) is in place; the features below are being built. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the design and the milestones.

## Features (planned)

- **Add a game from its rulebook:** upload a PDF, and the form fills itself in: name, players, play time, age, genres. It detects expansions and links them to their base game, and fills missing details from the web.
- **Manage your library:** list, view, edit and delete games.
- **Rules chat:** answers come from the rulebook with clickable page citations. The assistant asks which game or expansion you mean when that's unclear, and offers a clearly labelled web search when the rulebook doesn't cover a question.
- **Recommendations:** "a co-op game for 5 players under an hour" picks from your own library.

## Tech stack

- **Frontend:** Next.js (App Router), TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, Storybook
- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async), Alembic, LangGraph
- **Data and ML:** PostgreSQL with pgvector and pg_trgm, BAAI bge embeddings and reranker, Docling, OpenAI, LangSmith
- **Quality:** pytest, Vitest, React Testing Library, MSW, Playwright, Ruff, mypy, ESLint, Prettier, pre-commit, GitHub Actions

## Getting started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Compose v2.24 or newer): runs Postgres, or the whole app
- [uv](https://docs.astral.sh/uv/): installs Python 3.12 and the backend's packages
- [Node.js](https://nodejs.org/) 24: runs the Next.js frontend and its tooling
- [just](https://just.systems/): runs the project's commands

### Set up

```sh
git clone https://github.com/Hoang0211/bg-assistant.git
cd bg-assistant
```

Install the dependencies:

```sh
cd backend
uv sync
cd ../frontend
npm ci
cd ..
```

Optionally, install the Git hooks that format and lint each commit:

```sh
uv tool install pre-commit
pre-commit install
```

Environment files are optional for now; the defaults work locally. See `backend/.env.example` and `frontend/.env.example`.

### Run

| Command | What it does |
|---|---|
| `just dev` | Starts Postgres in Docker, plus the backend and frontend dev servers with hot reload |
| `just up` | Builds and runs the whole app in containers |
| `just down` | Stops and removes the containers (the database data is kept) |

Run `just migrate` once after the first start, to set up the database. `just up` runs migrations automatically.

Then open http://localhost:3000. The API docs are at http://localhost:8000/docs.

## Development

| Command | What it does |
|---|---|
| `just lint` | Ruff, mypy, ESLint, Prettier and TypeScript checks |
| `just format` | Formats the backend and frontend code |
| `just test` | Backend tests with coverage, frontend unit tests and Storybook story tests |
| `just e2e` | Playwright end-to-end tests |
| `just storybook` | Storybook at http://localhost:6006 |
| `just gen-types` | Regenerates the frontend's API types from the backend |

Run `just` to list every command.
