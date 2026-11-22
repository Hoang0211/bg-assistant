# Evaluation

Measures how well search finds the rulebook passages that answer real rules questions, how much of each page's text the parser kept, and whether a model can answer the questions from what search finds. See "Evaluation" in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) for the design.

- `golden_questions.json`: 30 questions with where each answer is printed, written from the PDFs before looking at any results
- `library.json`: the games and rulebooks the eval database is built from
- `reports/`: one Markdown report per run

## Rulebooks

The PDFs are the publishers' copyright, so they aren't in the repo. Download each one, save it in `backend/data/rulebooks/` under the name below, and `just eval-ingest` checks its `sha256` against `library.json`. A different edition has different page numbers, which would count as misses.

Several of these games have more than one edition, each with its own rulebook, so a rulebook you find may not be the one the golden questions were written from; the `sha256` check tells you when it isn't.

| File                                   | Rulebook                       | Publisher        |
| -------------------------------------- | ------------------------------ | ---------------- |
| `SSAP_EN.pdf`                          | Sea Salt & Paper               | Bombyx           |
| `SSAP_EXTRA_SALT_EN.pdf`               | Sea Salt & Paper: Extra Salt   | Bombyx           |
| `SSAP_EXTRA_PEPPER_EN.pdf`             | Sea Salt & Paper: Extra Pepper | Bombyx           |
| `Rebel_Princess_Deluxe_Edition_EN.pdf` | Rebel Princess                 | Bézier Games     |
| `Splendor_EN.pdf`                      | Splendor                       | Space Cowboys    |
| `Catan_EN.pdf`                         | Catan                          | Catan Studio     |
| `Power_Grid_EN.pdf`                    | Power Grid                     | Rio Grande Games |

## Running it

1. `just db`, then `just download-models` once. The parser needs `OPENAI_API_KEY` in `backend/.env`.
2. `just eval-ingest`: builds the `bg_assistant_eval` database from the PDFs. The first run has the model read every page (about $0.37 for the 60 pages) and stores the Markdown; later runs reuse it for free, so rerun it after any chunker change. `just eval-ingest --reparse` reads the pages again, after a change to the parser's prompt or model.
3. `just eval`: runs the questions through search and writes a report to `reports/` (free).
4. `just eval-text`: compares the stored Markdown with each page's text layer and writes a report (free).
5. `just eval-answers`: answers each question from its top chunks and grades the answers (about $0.10).
