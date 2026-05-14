# Benchmark Fixtures

This directory holds the minimum benchmark data needed to smoke-test the MVP
evaluation flow.

## Files

- `highlight_qa/demo/*.jsonl`
  - line-delimited samples aligned with `backend/assets/schemas/highlight_qa.schema.json`
- `anti_spoiler/demo/*.jsonl`
  - line-delimited samples aligned with `backend/assets/schemas/anti_spoiler_eval.schema.json`
- `chapter_summary/demo/*.jsonl`
  - lightweight summary checks used by `backend/eval/run_eval.py`

## Scope

These fixtures are intentionally tiny and synthetic:

- they target the bundled `backend/assets/examples/muse_demo_book.txt`
- they are meant for regression checks, not model ranking
- they only assert minimum behavior needed for a direct `eval` run

## Run

```bash
python backend/eval/run_eval.py
pytest backend/tests/test_mvp.py
```
