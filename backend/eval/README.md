# Evaluation

Measures how well search finds the rulebook passages that answer real rules questions. See "Evaluation" in [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md) for the design.

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

1. `just db`, then `just download-models` once.
2. `just eval-ingest`: builds the `bg_assistant_eval` database from the PDFs (about 10 minutes). Rerun it after a parser or chunker change.
3. `just eval`: runs the questions and writes a report to `reports/`.
