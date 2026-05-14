# Hierarchical Dataset And Source Registry Builders

`backend/scripts/` now contains two entrypoints:

- `backend/scripts/source_registry_manifest_builder.py`
  - registers local `txt/json` sources into standard raw records and source manifests
  - supports `books` and `persona_sources` modes
  - can optionally call the hierarchical builder for `books`
- `backend/scripts/hierarchical_dataset_builder.py`
  - builds layered Muse Reading dataset artifacts plus graph-intermediate exports from one normalized book source

## 1. Source registry entrypoint

Use this when a local source should first be registered into the `backend/assets/data/`-style directory layout and manifest structure.

### Supported inputs

- plain `.txt`
- source `.json` with `content` or `text`
- serialized `BookRecord` `.json` in `books` mode
- one file, multiple files, or a directory of `.txt/.json`

### Run for books

```bash
python backend/scripts/source_registry_manifest_builder.py backend/scripts/demo_book.txt --mode books
```

This writes to `backend/scripts/registry_output/` by default:

```text
backend/scripts/registry_output/
  backend/assets/data/
    raw/
      books/
        book_demo_book__source_project_demo_book__v001.json
    processed/
      books/
        book_demo_book/
          v001/
            raw_record.json
            hierarchical_chunks.jsonl
            l0_raw_paragraph.jsonl
            l1_fine_grained.jsonl
            l2_structure_summary.jsonl
            l3_global_index.jsonl
            l4_quote_or_stance.jsonl
            manifest.json
            graph/
              graph.json
              episodes.jsonl
              entities.jsonl
              relations.jsonl
              communities.jsonl
              sagas.jsonl
    manifests/
      manifest__books__book_demo_book__v001.json
      source_registry__books__v001.json
```

### Run for persona sources

```bash
python backend/scripts/source_registry_manifest_builder.py path/to/persona_notes.txt --mode persona_sources --persona-name "Lu Xun" --source-type author_work
```

This writes:

```text
backend/scripts/registry_output/
  backend/assets/data/
    raw/
      persona_sources/
        persona_source_persona_notes__source_author_work__v001.json
    manifests/
      manifest__persona_sources__persona_source_persona_notes__v001.json
      source_registry__persona_sources__v001.json
```

### Useful options

- `--output-root backend/scripts/registry_output_custom`
- `--version v002`
- `--source-type licensed_book`
- `--copyright-status licensed`
- `--skip-hierarchical-build`
  - `books` mode only
  - registers raw/manifests without generating processed chunks
- `--recursive`
  - expands directory inputs and picks up `.txt/.json` files

### Registration behavior

- `books` mode normalizes ids to lowercase ASCII with underscores, for example `book_demo_book`.
- `persona_sources` mode emits `persona_source_<slug>` and optional `persona_<slug>`.
- Raw source filenames follow the `backend/docs/data/muse_reading_data_design.md` pattern for books:
  - `book_<title_slug>__source_<source_type>__v001.json`
- Source manifests are stored under `backend/assets/data/manifests/` and batch registry files are grouped by mode:
  - `manifest__books__<book_id>__v001.json`
  - `manifest__persona_sources__<source_id>__v001.json`
  - `source_registry__books__v001.json`
  - `source_registry__persona_sources__v001.json`

## 2. Hierarchical dataset builder

Use this when a normalized book raw record already exists and only the layered processed artifacts are needed.

### Supported inputs

- plain `.txt`
- `raw_text` style `.json` with `content`
- serialized `BookRecord` `.json`

### Run

```bash
python backend/scripts/hierarchical_dataset_builder.py backend/scripts/demo_book.txt --output-dir backend/scripts/build_output/demo_run
```

### Outputs

- `raw_record.json`
- `hierarchical_chunks.jsonl`
- `l0_raw_paragraph.jsonl`
- `l1_fine_grained.jsonl`
- `l2_structure_summary.jsonl`
- `l3_global_index.jsonl`
- `l4_quote_or_stance.jsonl`
- `graph/graph.json`
- `graph/episodes.jsonl`
- `graph/entities.jsonl`
- `graph/relations.jsonl`
- `graph/communities.jsonl`
- `graph/sagas.jsonl`
- `manifest.json`

## 3. Notes

- L1 uses paragraph windows for retrieval-friendly chunks.
- L2 is a chapter-structure summary scaffold.
- L3 is a single global routing/index chunk.
- L4 is a quote/stance placeholder layer for downstream persona or commentary workers.
- Graph exports are produced from the L0 paragraph view so they remain spoiler-aware and position-aligned.
- The new registry script is the recommended entrypoint when the source still needs provenance registration.
