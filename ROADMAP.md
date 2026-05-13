# Roadmap

## Current MVP

The repository already covers a runnable reading loop:

- upload a text file
- parse chapters and paragraphs into chunks
- render a static reading interface
- ask highlight-grounded questions
- generate chapter summaries
- apply basic persona styling
- apply basic anti-spoiler constraints
- build temporal graph artifacts for uploaded texts
- run lightweight evaluation scripts

## Near-Term Priorities

1. Strengthen evaluation coverage
   - retrieval evaluation
   - persona consistency evaluation
   - richer anti-spoiler evaluation

2. Improve text-to-graph quality
   - better entity extraction
   - cleaner relation typing
   - stronger chapter-level progression signals

3. Harden open-source packaging
   - expand setup documentation
   - add more public demo assets
   - formalize source registry validation

## Planned Data Work

- expand public-domain or redistributable demo texts
- refine persona source catalogs
- convert source catalogs into graph-ready evidence shards
- improve release manifests for open-source safe data packaging

## Planned Product Work

- richer reading interactions
- better progress-aware retrieval orchestration
- more controllable Chinese lead-reader personas
- tighter frontend integration for graph-backed QA and summaries

## Out of Scope for This MVP

- production deployment infrastructure
- multi-user authentication
- external vector database hosting
- large-scale training pipelines
- complex CI/CD workflows
