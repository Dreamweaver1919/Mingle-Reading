# Muse Reading Data Design

## 1. Design alignment with existing materials

This design follows the current project line in the provided reports and slides rather than replacing it:

- Four core asset classes stay unchanged: `book text corpus`, `persona source corpus`, `annotation data`, `evaluation data`.
- Chunking keeps both current practical work and future expansion:
  - current implementable layer: paragraph or sliding-window retrieval chunks;
  - reserved higher layers: chapter structure summary, global index, quote/stance layers.
- Anti-spoiler evaluation keeps the PBM direction:
  - `SANQA`: progress-aware answerability and spoiler control;
  - `ERE`: emotion resonance and response boundary;
  - `CME`: cumulative meaning evolution across reading progress.
- Persona construction keeps the source split already proposed in slides:
  - `fact layer`
  - `style layer`
  - `source layer`

## 2. Data source taxonomy

### 2.1 Book text sources

- `public_domain_book`: public-domain novels, essays, classics.
- `open_license_book`: openly licensed text corpora.
- `licensed_book`: EPUB/TXT obtained with explicit permission.
- `project_demo_book`: internal demo-only text used for prototype verification before full licensing is clear.

Typical raw formats:

- `epub`
- `txt`
- `docx`
- `pdf` as temporary input only, not the preferred archival format

### 2.2 Persona sources

- `author_work`: original essays, letters, prefaces, interviews, diaries.
- `character_source`: book passages directly describing a character's speech, motives, relations, and arc.
- `biography_reference`: biographies, memoirs, encyclopedia pages, educational summaries.
- `critical_reference`: literary criticism or public lectures used to extract stable analysis style.

### 2.3 Annotation sources

- `highlight_qa`: user-highlight-triggered QA or commentary pairs.
- `salience_label`: emotional peak, conflict intensity, symbolism density, psychological complexity.
- `chapter_evolution`: chapter summary plus meaning updates across progress checkpoints.
- `persona_review`: human review for persona style fidelity and boundary control.

### 2.4 Evaluation sources

- `retrieval_eval`
- `persona_consistency_eval`
- `anti_spoiler_eval`
- `user_study_sample`

## 3. Unified directory structure

```text
data/
  raw/
    books/
    persona_sources/
  processed/
    books/
    personas/
  annotations/
    highlight_qa/
    chapter_evolution/
  eval/
    retrieval/
    persona_consistency/
    anti_spoiler/
  manifests/

schemas/
  raw_text.schema.json
  chunk.schema.json
  persona.schema.json
  highlight_qa.schema.json
  chapter_evolution.schema.json
  anti_spoiler_eval.schema.json

examples/data/
  raw_text/
  chunks/
  personas/
  highlight_qa/
  chapter_evolution/
  anti_spoiler_eval/
```

## 4. Naming convention

Use lowercase ASCII only. Use underscore `_` inside identifiers and hyphen `-` only in dates.

### 4.1 Canonical ids

- `book_id`: `book_<title_slug>`
  - example: `book_the_pig_like_maverick`
- `chapter_id`: `ch_<3-digit-index>`
  - example: `ch_003`
- `section_id`: `sec_<3-digit-index>`
- `paragraph_id`: `para_<4-digit-index>`
- `chunk_id`: `chunk_<book_short>_<chapter>_<local_index>`
  - example: `chunk_pig_003_0007`
- `persona_id`: `persona_<name_slug>`
  - example: `persona_lu_xun`
- `sample_id`: `<task>_<book_short>_<chapter>_<index>`
  - example: `highlight_qa_pig_003_0002`

### 4.2 File naming

- Raw text file:
  - `book_<title_slug>__source_<source_type>__v001.json`
- Chunk file:
  - `chunks__book_<title_slug>__ch_<3-digit-index>__v001.jsonl`
- Persona file:
  - `persona_<name_slug>__v001.json`
- Annotation file:
  - `<task>__book_<title_slug>__split_<split>__v001.jsonl`
- Eval file:
  - `<task>__book_<title_slug>__split_<split>__v001.jsonl`

### 4.3 Split naming

- `train`
- `dev`
- `test`
- `gold`
- `demo`

## 5. Core schema intent

### 5.1 `raw_text`

Stores one book or source document before chunking but after basic legal and provenance registration.

### 5.2 `chunk`

Stores retrieval-ready units with strict position metadata for anti-spoiler filtering.

### 5.3 `persona`

Stores fact, style, stance, quote references, and usage constraints for author or character agents.

### 5.4 `highlight_qa`

Stores interaction samples centered on a highlighted span and surrounding context.

### 5.5 `chapter_evolution`

Stores chapter summary plus progress-aware understanding updates, designed to support chapter wrap-up and CME-style evaluation.

### 5.6 `anti_spoiler_eval`

Stores adversarial progress-aware questions, gold labels, leakage categories, and scoring metadata.

## 6. Data flow

```text
source acquisition
  -> legal/provenance registration
  -> raw text normalization
  -> chapter/section parsing
  -> paragraph alignment
  -> chunk generation
  -> metadata enrichment
  -> persona extraction / annotation authoring
  -> golden-set review
  -> eval-set packaging
  -> open-source filtering and release manifest
```

### 6.1 Detailed handoff points

1. `raw/books` and `raw/persona_sources`
   - owned by ingestion / copyright checking.
2. `processed/books`
   - owned by text pipeline and chunking pipeline.
3. `processed/personas`
   - owned by persona extraction and prompt-design collaboration.
4. `annotations/*`
   - owned by human annotation and QA review.
5. `eval/*`
   - owned by benchmark design and evaluation scripts.

## 7. Open-source boundary

### Can be open-sourced

- Schema definitions.
- Naming rules and directory conventions.
- Annotation guidelines and scoring rubrics.
- Evaluation prompts, labels, and score aggregation code.
- Metadata-only manifests for copyrighted books.
- Synthetic or manually rewritten demo examples that do not reproduce large copyrighted passages.

### Should not be openly released by default

- Full copyrighted EPUB/TXT content.
- Large contiguous passages from licensed books.
- Raw persona corpora compiled from non-open biographical or critical sources without redistribution rights.
- Internal API logs containing user reading traces.

### Conditional release

- Public-domain full texts may be released if source and license are recorded.
- Short excerpts may be released as demo context if rights and length are reviewed.

## 8. Current minimum build strategy

This delivery intentionally builds only the minimum stable scaffold:

- schema-first
- metadata-first
- sample-first
- no assumption that ingestion scripts already exist

That keeps the structure decoupled for other agents who may later add:

- EPUB parsers
- chunk builders
- annotation tooling
- evaluation runners
