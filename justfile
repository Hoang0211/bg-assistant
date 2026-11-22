# just's default shell is sh, which Windows doesn't have; use PowerShell there instead.
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

# List the available recipes.
default:
    @just --list

# --- Running the app ---

# Start the database and both dev servers together (Ctrl+C stops the servers).
[parallel]
dev: db dev-backend dev-frontend

# Start only the database container and wait until it's healthy.
db:
    docker compose up -d --wait db

# Run the backend dev server with auto-reload.
[working-directory: 'backend']
dev-backend:
    uv run uvicorn app.main:app --reload --loop asyncio:SelectorEventLoop

# Run the frontend dev server.
[working-directory: 'frontend']
dev-frontend:
    npm run dev

# Build and start the whole app in containers.
up:
    docker compose up --build -d --wait

# Stop and remove the containers (the database data is kept).
down:
    docker compose down

# Run Storybook.
[working-directory: 'frontend']
storybook:
    npm run storybook

# --- Checks ---

# Run every lint, format and type check.
lint: lint-backend lint-frontend

[working-directory: 'backend']
lint-backend:
    uv run ruff check
    uv run ruff format --check
    uv run mypy

[working-directory: 'frontend']
lint-frontend:
    npm run lint
    npm run format:check
    npm run typecheck

# Format all code in place.
format: format-backend format-frontend

[working-directory: 'backend']
format-backend:
    uv run ruff check --fix
    uv run ruff format

[working-directory: 'frontend']
format-frontend:
    npm run format

# Run the backend and frontend tests.
test: test-backend test-frontend

[working-directory: 'backend']
test-backend:
    uv run pytest --cov

[working-directory: 'frontend']
test-frontend:
    npm run test
    npm run test:storybook

# Run the tests that call OpenAI (a few cents; needs OPENAI_API_KEY in backend/.env).
[working-directory: 'backend']
test-live:
    uv run --env-file .env pytest -m live --force-enable-socket

# Run the Playwright end-to-end tests (starts the database first).
[working-directory: 'frontend']
e2e: db
    npm run e2e

# --- Database and API types ---

# Apply database migrations.
[working-directory: 'backend']
migrate:
    uv run alembic upgrade head

# Regenerate the frontend's API types from the backend's OpenAPI schema.
[working-directory: 'backend']
gen-types:
    uv run python -m app.export_openapi ../frontend/openapi.json
    npm --prefix ../frontend run gen:api

# Download the embedding and Docling models (about 1 GB, once per machine; the tests need them).
[working-directory: 'backend']
download-models:
    uv run python -m app.ingestion.download_models

# --- Engine ---

# Parse, chunk and embed the stored rulebooks again: `just reindex`, `just reindex --game 3`;
# `--reparse` makes the LLM parser read the pages again instead of using the stored Markdown.
[working-directory: 'backend']
reindex *args:
    uv run python -m app.cli reindex {{args}}

# Build a parser's eval database from backend/eval/library.json and ingest its rulebooks:
# `just eval-ingest --parser llm` (Docling takes about 10 minutes; `--reparse` pays the LLM again).
[working-directory: 'backend']
eval-ingest *args:
    uv run python -m app.cli eval-ingest {{args}}

# Search a parser's eval database for each golden question and write a report to
# backend/eval/reports/: `just eval --parser llm`, or `just eval --compare` for both side by side.
[working-directory: 'backend']
eval *args:
    uv run python -m app.cli eval {{args}}

# Compare the LLM eval database's Markdown with each PDF page's text layer and write a report to
# backend/eval/reports/; the least-kept pages' missing and added words are printed, not saved.
[working-directory: 'backend']
eval-text:
    uv run python -m app.cli eval-text

# Answer each golden question from each parser's top chunks and grade the answers, which spends
# OpenAI credit (about $0.48); the report goes to backend/eval/reports/, the full answers to the
# git-ignored backend/data/answer-checks/.
[working-directory: 'backend']
eval-answers:
    uv run python -m app.cli eval-answers
