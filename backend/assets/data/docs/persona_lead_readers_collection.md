# Persona Lead Readers Collection

This document summarizes the first three lead-reader personas collected for Muse Reading and explains how the assets should attach to the temporal graph layer.

## Scope

- `persona_lu_xun`
- `persona_mark_twain`
- `persona_zhang_ailing`

## Minimum collection requirements

Each lead-reader persona is now expected to meet all of the following:

- at least `20` total sources
- at least `10` work sources
- at least `10` voice sources

For Muse Reading, `voice sources` include interviews, quotes, letters, speeches, essays, prefaces, afterwords, autobiographical prose, and other materials that directly expose the author's voice, method, or stance.

Each persona currently has:

- one schema-conformant persona pack in `backend/assets/data/processed/personas/`
- multiple source records in `backend/assets/data/raw/persona_sources/`
- a shared registry entry in `backend/assets/data/manifests/persona_lead_readers_registry__v001.json`
- a large-source catalog in `backend/assets/data/raw/persona_sources/catalog_<persona>__v001.json`
- a status summary in `backend/assets/data/manifests/persona_collection_requirements_summary__v001.json`

## Collection policy

- Prefer public-domain original works when available.
- Use biography or critical references as metadata-only anchors when the source text is copyrighted.
- For modern authors such as Zhang Ailing, store only source metadata and evidence summaries by default.
- Do not reproduce long copyrighted passages in repository assets.

## Temporal graph mapping

Recommended graph structure:

- `persona` node
  - one per lead reader
- `persona_source` node
  - one per source record
- `grounded_in` edge
  - from persona node to source node
  - payload should include `source_type`, `time_anchor`, `copyright_status`, and `redistributable`
- optional `supports_trait` edge
  - from source node to normalized trait nodes such as `irony`, `social_diagnosis`, `urban_texture`, `vernacular_satire`

Recommended retrieval flow:

1. Select persona by user choice or system default.
2. Filter persona sources by release policy and reader-visible book progress.
3. Retrieve current-book chunks and persona-source summaries separately.
4. Merge them in orchestration so persona style is grounded but book answers remain spoiler-safe.

## Persona notes

### Lu Xun

- Best for diagnostic, socially incisive close reading.
- Strong source support from public-domain author works plus one metadata-only biography anchor.
- Current catalog status: `28 total / 12 works / 12 voice sources`

### Mark Twain

- Best for observational, satirical, anecdotal lead-reading commentary.
- Current bundle is fully public-domain and can be shipped in the open repository.
- Current catalog status: `30 total / 12 works / 15 voice sources`

### Zhang Ailing

- Best for scene-level, texture-heavy, emotionally restrained urban reading.
- Current bundle is intentionally metadata-heavy to respect copyright boundaries.
- Current catalog status: `30 total / 12 works / 13 voice sources`

## Next steps

- Add a formal schema for persona source records.
- Split source summaries into smaller evidence units for graph edges.
- Add persona-specific evaluation samples for consistency checking.
