# Data Skeleton

This directory is the minimal project-aligned data skeleton for Muse Reading.

## Layout

- `raw/books/`: original book-level assets after provenance registration.
- `raw/persona_sources/`: original author, character, biography, and criticism sources.
- `processed/books/`: normalized book text, paragraph map, and retrieval chunks.
- `processed/personas/`: structured persona packs consumed by prompts or RAG.
- `annotations/highlight_qa/`: highlight-centered interaction gold data.
- `annotations/chapter_evolution/`: chapter summary and understanding-evolution annotations.
- `eval/retrieval/`: retrieval benchmarks and query-doc relevance labels.
- `eval/persona_consistency/`: persona fidelity evaluation sets.
- `eval/anti_spoiler/`: SANQA/ERE/CME-oriented adversarial evaluation sets.
- `manifests/`: license, source, split, and release manifests.

## What belongs here

- metadata manifests
- normalized JSON / JSONL
- annotation exports
- evaluation packages

## What should stay out

- code
- notebooks unrelated to data packaging
- model checkpoints
- vector database runtime files

## Release note

If a book is not public-domain or explicitly licensed for redistribution, store only metadata manifests here in open releases.
