# Contributing

Thanks for helping improve Muse Reading. The current repository is a lightweight Python MVP built with:

- `FastAPI` for the API layer
- a static frontend in `frontend/`
- local JSON files under `backend/workspace_state/` for runtime storage

## Before You Start

- Read the project overview in `README.md`.
- Keep changes aligned with the existing MVP scope.
- Do not commit generated files from `backend/workspace_state/`.
- Prefer small, reviewable pull requests.

## Local Setup

1. Create and activate a Python environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
python main.py
```

4. Open `http://127.0.0.1:8000`.

## Project Areas

- `backend/api/`: FastAPI app and HTTP endpoints
- `backend/common/`: shared config and Pydantic models
- `backend/data/`: ingestion and local storage helpers
- `backend/knowledge_base/`: graph, QA retrieval, and character logic
- `backend/safety/`: anti-spoiler safeguards
- `backend/llm_memory/`: persona, orchestration, and summary generation
- `frontend/`: static HTML/CSS/JS reader UI
- `backend/assets/data/`, `backend/assets/schemas/`, `backend/benchmarks/`, `backend/eval/`: dataset, schema, and evaluation assets
- `backend/scripts/`: build and dataset utility scripts
- `backend/tests/`: pytest coverage for the MVP

## Development Expectations

- Reuse the current data schemas and file naming conventions where possible.
- Keep new features compatible with the existing FastAPI + static frontend architecture.
- Add or update tests when behavior changes.
- Document any new root-level setup requirement in a follow-up README change.

## Recommended Checks

Run these before opening a pull request:

```bash
pytest -q
python backend/eval/run_eval.py
```

If your change touches dataset builders, also run the relevant script and confirm it produces valid JSON/JSONL output.

## Pull Request Notes

When opening a PR, include:

- what changed
- why it changed
- how you verified it
- any known limitations or follow-up work

## Scope and Safety

- Avoid committing copyrighted raw text unless it is clearly redistributable.
- Prefer schema, examples, and metadata-only records when source redistribution is unclear.
- Keep persona and evaluation assets traceable to their sources.
