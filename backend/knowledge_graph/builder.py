from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Callable

from backend.api.schemas import BookChunk, BookRecord

from . import llm_extraction
from . import build_logger as build_logger_mod
from . import storage as graph_storage
from .models import (
    ChapterNode,
    ChapterTimelineEntry,
    CommunityNode,
    EntityNode,
    EpisodeNode,
    GraphProvenance,
    RelationDirectionality,
    RelationEdge,
    RelationStatus,
    SagaNode,
    TemporalContextGraph,
)


STATEFUL_FAMILIES = {"location", "membership", "status"}
CHAPTER_CONSOLIDATION_FAMILIES = {"location", "membership", "status", "interaction", "identity"}


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", lowered)
    return lowered.strip("_") or "unknown"


def _excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _chapter_title(chunk: BookChunk) -> str:
    metadata = chunk.metadata or {}
    title = metadata.get("chapter_title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return chunk.chapter_id.replace("_", " ").title()


def _build_provenance(chunk: BookChunk, source: str, extra_metadata: dict | None = None) -> GraphProvenance:
    metadata = dict(extra_metadata or {})
    metadata.setdefault("spoiler_guard", chunk.spoiler_guard)
    metadata.setdefault("chunk_level", chunk.chunk_level)
    metadata.setdefault("section_id", chunk.section_id)
    return GraphProvenance(
        chunk_id=chunk.chunk_id,
        book_id=chunk.book_id,
        chapter_id=chunk.chapter_id,
        chapter_index=chunk.chapter_index,
        paragraph_id=chunk.paragraph_id,
        paragraph_index=chunk.paragraph_index,
        text_excerpt=_excerpt(chunk.text),
        source=source,  # type: ignore[arg-type]
        metadata=metadata,
    )


def _normalize_entity_name(name: str) -> str:
    return " ".join(name.strip().split())


def _infer_entity_type(name: str, declared_type: str, chunk: BookChunk) -> str:
    allowed = {"character", "location", "concept", "group", "theme", "artifact", "unknown"}
    if declared_type in allowed:
        return declared_type
    return "unknown"


def _entity_aliases(name: str) -> list[str]:
    aliases = {name}
    parts = name.split()
    if len(parts) > 1:
        aliases.add(parts[-1])
    return sorted(alias for alias in aliases if alias)




def _fact_signature(
    relation_type: str,
    state_family: str,
    source_entity_id: str,
    target_entity_id: str,
    directionality: RelationDirectionality,
) -> str:
    if directionality == "undirected":
        pair = sorted((source_entity_id, target_entity_id))
        return f"{relation_type}|{state_family}|{pair[0]}|{pair[1]}"
    return f"{relation_type}|{state_family}|{source_entity_id}|{target_entity_id}"


def _state_key(state_family: str, source_entity_id: str, directionality: RelationDirectionality, target_entity_id: str) -> str:
    if state_family not in STATEFUL_FAMILIES:
        return ""
    if directionality == "undirected":
        ordered = sorted((source_entity_id, target_entity_id))
        return f"{state_family}|{ordered[0]}|{ordered[1]}"
    return f"{state_family}|{source_entity_id}"


def _entity_alias_forms(entity: EntityNode) -> set[str]:
    return {
        _slugify(entity.canonical_name),
        *(_slugify(alias) for alias in entity.aliases),
    }


class TemporalGraphBuilder:
    """Build a Graphiti-style temporal knowledge graph from paragraph episodes."""

    def __init__(
        self,
        extractor_runtime: llm_extraction.GraphExtractorRuntime | None = None,
        progress_callback: Callable[[dict], None] | None = None,
        strict_llm_extraction: bool = False,
        build_logger: build_logger_mod.GraphBuildLogger | None = None,
    ) -> None:
        self.extractor_runtime = extractor_runtime or llm_extraction.resolve_graph_extractor_runtime()
        self.progress_callback = progress_callback
        self.strict_llm_extraction = strict_llm_extraction
        self.build_logger = build_logger

    def build(self, book: BookRecord) -> TemporalContextGraph:
        if self.strict_llm_extraction and self.extractor_runtime is None:
            raise RuntimeError(
                "strict Graphiti extraction requires GRAPHITI_EXTRACTOR_API_KEY, "
                "GRAPHITI_EXTRACTOR_BASE_URL and GRAPHITI_EXTRACTOR_MODEL_NAME."
            )
        now = datetime.now(UTC).isoformat()
        extraction_backend = "llm-assisted-resolution" if self.extractor_runtime is not None else "none"

        sorted_chunks = sorted(book.chunks, key=lambda item: (item.chapter_index, item.paragraph_index))
        total_chunks = len(sorted_chunks)
        processed_chunk_ids: set[str] = set()
        previous_episode_id: str | None = None

        # --- resume from checkpoint if a partial graph exists ---
        if graph_storage.graph_exists(book.book_id):
            graph = graph_storage.load_graph(book.book_id)
            processed_chunk_ids = {ep.chunk_id for ep in graph.episodes.values() if ep.chunk_id}
            entity_id_by_alias, active_relation_by_signature, active_state_relation_by_key, relation_version_counter = (
                self._rebuild_state_from_graph(graph)
            )
            chapter_entities, chapter_episode_ids, chapter_relation_ids = self._rebuild_chapter_indexes(graph)
            chapter_active_relation_ids: dict[int, set[str]] = defaultdict(set)
            chapter_invalidated_relation_ids: dict[int, set[str]] = defaultdict(set)
            chapter_provenance: dict[int, list[GraphProvenance]] = defaultdict(list)
            chapter_paragraph_count: Counter[int] = Counter()
            for ep in graph.episodes.values():
                chapter_episode_ids[ep.chapter_index].append(ep.episode_id)
                chapter_paragraph_count[ep.chapter_index] += 1
            # find previous episode
            sorted_eps = sorted(graph.episodes.values(), key=lambda e: e.episode_index)
            if sorted_eps:
                previous_episode_id = sorted_eps[-1].episode_id
            remaining = total_chunks - len(processed_chunk_ids)
            if self.build_logger is not None:
                self.build_logger.build_start(
                    total_chunks=total_chunks,
                    extraction_backend=extraction_backend,
                )
        else:
            graph = TemporalContextGraph(
                graph_id=f"graph::{book.book_id}",
                book_id=book.book_id,
                title=book.title,
                metadata={
                    "source_path": book.source_path,
                    "chapter_count": book.chapter_count,
                    "chunk_count": total_chunks,
                    "builder": "TemporalGraphBuilder",
                    "graph_style": "graphiti-inspired",
                    "entity_extraction": extraction_backend,
                    "fact_extraction": extraction_backend,
                    "created_at": now,
                    "llm_calls": 0,
                    "llm_skipped": 0,
                    "chapter_consolidations": [],
                },
            )
            entity_id_by_alias: dict[str, str] = {}
            active_relation_by_signature: dict[str, str] = {}
            active_state_relation_by_key: dict[str, str] = {}
            relation_version_counter: Counter[str] = Counter()
            chapter_entities: dict[int, set[str]] = defaultdict(set)
            chapter_episode_ids: dict[int, list[str]] = defaultdict(list)
            chapter_relation_ids: dict[int, set[str]] = defaultdict(set)
            chapter_active_relation_ids: dict[int, set[str]] = defaultdict(set)
            chapter_invalidated_relation_ids: dict[int, set[str]] = defaultdict(set)
            chapter_provenance: dict[int, list[GraphProvenance]] = defaultdict(list)
            chapter_paragraph_count: Counter[int] = Counter()
            if self.build_logger is not None:
                self.build_logger.build_start(
                    total_chunks=total_chunks,
                    extraction_backend=extraction_backend,
                )

        if self.build_logger is not None:
            self.build_logger.build_start(
                total_chunks=total_chunks,
                extraction_backend=extraction_backend,
            )

        for episode_index, chunk in enumerate(sorted_chunks, start=1):
            if chunk.chunk_id in processed_chunk_ids:
                continue
            self._emit_progress(
                stage="graph-episode-start",
                title="Processing graph episode",
                message=(
                    f"已处理文段 {episode_index - 1}/{total_chunks}，"
                    f"当前进入 chapter {chunk.chapter_index} paragraph {chunk.paragraph_index} 的图谱构建。"
                ),
                processed_snippets=episode_index - 1,
                total_snippets=total_chunks,
                current_snippet_id=chunk.chunk_id,
                current_chapter_index=chunk.chapter_index,
                current_paragraph_index=chunk.paragraph_index,
                details={
                    "phase": "episode-start",
                    "source_paragraph_indices": chunk.metadata.get("source_paragraph_indices", []),
                    "source_paragraph_count": chunk.metadata.get("source_paragraph_count", 1),
                    "packet_token_count": chunk.metadata.get("packet_token_count", len(chunk.text)),
                    "is_merged_packet": chunk.metadata.get("is_merged_packet", False),
                },
            )
            if self.build_logger is not None:
                self.build_logger.episode_start(
                    chunk_id=chunk.chunk_id,
                    chapter=chunk.chapter_index,
                    paragraph=chunk.paragraph_index,
                    text=chunk.text,
                    token_count=int(chunk.metadata.get("packet_token_count", len(chunk.text)) or 0),
                    source_para_count=int(chunk.metadata.get("source_paragraph_count", 1) or 1),
                    is_merged=bool(chunk.metadata.get("is_merged_packet", False)),
                )
                self.build_logger.flush()
            llm_episode_extraction = self._extract_episode_with_llm(chunk=chunk, graph=graph)
            if self.build_logger is not None:
                gate = chunk.metadata.get("llm_gate", {})
                llm_called = llm_episode_extraction is not None
                self.build_logger.llm_decision(
                    chunk_id=chunk.chunk_id,
                    called=llm_called,
                    score=int(gate.get("score", 0)),
                    reasons=gate.get("reasons", []),
                )
                if llm_called and llm_episode_extraction is not None:
                    self.build_logger.llm_response(
                        chunk_id=chunk.chunk_id,
                        entity_count=len(llm_episode_extraction.entities),
                        fact_count=len(llm_episode_extraction.facts),
                        entities=[
                            {"name": e.canonical_name, "type": e.entity_type, "aliases": e.aliases}
                            for e in llm_episode_extraction.entities
                        ],
                        facts=[
                            {"source": f.source, "target": f.target,
                             "relation": f.relation_type, "fact": f.fact}
                            for f in llm_episode_extraction.facts
                        ],
                        raw_response=getattr(llm_episode_extraction, "raw_response", ""),
                    )
                self.build_logger.flush()
            chapter_node_id = f"chapter_{chunk.chapter_index:03d}"
            chapter = graph.chapters.get(chapter_node_id)
            if chapter is None:
                chapter = ChapterNode(
                    chapter_node_id=chapter_node_id,
                    book_id=book.book_id,
                    chapter_id=chunk.chapter_id,
                    chapter_index=chunk.chapter_index,
                    title=_chapter_title(chunk),
                    spoiler_level=chunk.spoiler_level,
                    metadata={"section_ids": [], "chunk_levels": [], "reference_time": f"chapter://{book.book_id}/{chunk.chapter_index:03d}"},
                    provenance=[],
                )
                graph.chapters[chapter_node_id] = chapter

            episode_id = f"episode_{chunk.chapter_index:03d}_{chunk.paragraph_index:03d}"
            reference_time = f"narrative://{book.book_id}/c{chunk.chapter_index:03d}/p{chunk.paragraph_index:03d}"
            episode = EpisodeNode(
                episode_id=episode_id,
                episode_type="paragraph",
                book_id=book.book_id,
                chunk_id=chunk.chunk_id,
                chapter_id=chunk.chapter_id,
                chapter_index=chunk.chapter_index,
                paragraph_id=chunk.paragraph_id,
                paragraph_index=chunk.paragraph_index,
                episode_index=episode_index,
                text=chunk.text,
                spoiler_level=chunk.spoiler_level,
                tags=list(chunk.tags),
                reference_time=reference_time,
                created_at=now,
                metadata={
                    "token_offset": chunk.token_offset,
                    "position": chunk.position,
                    "section_id": chunk.section_id,
                    "paragraph_start_id": chunk.paragraph_start_id,
                    "paragraph_end_id": chunk.paragraph_end_id,
                    "extraction_mode": (
                        llm_episode_extraction.extraction_mode if llm_episode_extraction is not None else "skipped"
                    ),
                    **chunk.metadata,
                },
                provenance=[_build_provenance(chunk, "episode", {"reference_time": reference_time})],
            )
            if previous_episode_id is not None:
                episode.prev_episode_id = previous_episode_id
                graph.episodes[previous_episode_id].next_episode_id = episode_id
            previous_episode_id = episode_id

            graph.episodes[episode_id] = episode
            chapter.episode_ids.append(episode_id)
            chapter.paragraph_count += 1
            chapter.spoiler_level = max(chapter.spoiler_level, chunk.spoiler_level)
            if chunk.section_id and chunk.section_id not in chapter.metadata["section_ids"]:
                chapter.metadata["section_ids"].append(chunk.section_id)
            if chunk.chunk_level not in chapter.metadata["chunk_levels"]:
                chapter.metadata["chunk_levels"].append(chunk.chunk_level)
            chapter.provenance.extend(episode.provenance)
            chapter_episode_ids[chunk.chapter_index].append(episode_id)
            chapter_provenance[chunk.chapter_index].extend(episode.provenance)
            chapter_paragraph_count[chunk.chapter_index] += 1

            entity_nodes = self._resolve_entities(
                chunk,
                graph,
                entity_id_by_alias,
                llm_episode_extraction=llm_episode_extraction,
            )
            entity_ids = [entity.entity_id for entity in entity_nodes]
            episode.entity_ids = entity_ids
            chapter.entity_ids = sorted(set(chapter.entity_ids).union(entity_ids))
            chapter_entities[chunk.chapter_index].update(entity_ids)

            for entity in entity_nodes:
                if episode_id not in entity.episode_ids:
                    entity.episode_ids.append(episode_id)
                entity.mention_count += 1
                if entity.first_seen_chapter == 0 or chunk.chapter_index < entity.first_seen_chapter:
                    entity.first_seen_chapter = chunk.chapter_index
                    entity.first_seen_paragraph = chunk.paragraph_index
                if (
                    chunk.chapter_index > entity.last_seen_chapter
                    or (
                        chunk.chapter_index == entity.last_seen_chapter
                        and chunk.paragraph_index >= entity.last_seen_paragraph
                    )
                ):
                    entity.last_seen_chapter = chunk.chapter_index
                    entity.last_seen_paragraph = chunk.paragraph_index
                entity.metadata.setdefault("chapter_span", [])
                if chunk.chapter_index not in entity.metadata["chapter_span"]:
                    entity.metadata["chapter_span"].append(chunk.chapter_index)

            relation_ids = self._extract_and_resolve_relations(
                chunk=chunk,
                episode=episode,
                entity_nodes=entity_nodes,
                graph=graph,
                now=now,
                active_relation_by_signature=active_relation_by_signature,
                active_state_relation_by_key=active_state_relation_by_key,
                relation_version_counter=relation_version_counter,
                llm_episode_extraction=llm_episode_extraction,
            )
            episode.relation_ids = relation_ids
            chapter.relation_ids = sorted(set(chapter.relation_ids).union(relation_ids))
            chapter_relation_ids[chunk.chapter_index].update(relation_ids)
            self._emit_progress(
                stage="graph-episode-complete",
                title="Episode graph step completed",
                message=(
                    f"已完成文段 {episode_index}/{total_chunks}，"
                    f"当前文段的 entities / facts 已写入临时图状态。"
                ),
                processed_snippets=episode_index,
                total_snippets=total_chunks,
                current_snippet_id=chunk.chunk_id,
                current_chapter_index=chunk.chapter_index,
                current_paragraph_index=chunk.paragraph_index,
                details={
                    "phase": "episode-complete",
                    "entity_count": len(entity_ids),
                    "relation_count": len(relation_ids),
                    "source_paragraph_indices": chunk.metadata.get("source_paragraph_indices", []),
                    "source_paragraph_count": chunk.metadata.get("source_paragraph_count", 1),
                    "packet_token_count": chunk.metadata.get("packet_token_count", len(chunk.text)),
                    "is_merged_packet": chunk.metadata.get("is_merged_packet", False),
                },
            )
            if self.build_logger is not None:
                extraction_mode = (
                    llm_episode_extraction.extraction_mode
                    if llm_episode_extraction is not None
                    else "skipped"
                )
                self.build_logger.episode_end(
                    chunk_id=chunk.chunk_id,
                    extraction_mode=extraction_mode,
                    entity_count=len(entity_ids),
                    relation_count=len(relation_ids),
                    entity_names=[
                        graph.entities[eid].canonical_name
                        for eid in entity_ids if eid in graph.entities
                    ],
                    relations=[
                        {"source": graph.entities[graph.relations[rid].source_entity_id].canonical_name
                         if rid in graph.relations and graph.relations[rid].source_entity_id in graph.entities else "?",
                         "target": graph.entities[graph.relations[rid].target_entity_id].canonical_name
                         if rid in graph.relations and graph.relations[rid].target_entity_id in graph.entities else "?",
                         "relation": graph.relations[rid].relation_type if rid in graph.relations else "?",
                         "status": graph.relations[rid].status if rid in graph.relations else "?"}
                        for rid in relation_ids
                    ],
                )
                self.build_logger.flush()
            graph_storage.save_graph(graph)

        self._emit_progress(
            stage="chapter-consolidation",
            title="Consolidating chapter facts",
            message="Normalizing chapter-level aliases and relation state families before higher-level graph assembly.",
            processed_snippets=total_chunks,
            total_snippets=total_chunks,
            details={
                "phase": "chapter-consolidation",
                "chapter_count": len(chapter_entities),
                "active_entity_count": len(graph.entities),
                "active_relation_count": len(graph.relations),
            },
        )
        self._consolidate_chapters(
            graph=graph,
            chapter_entities=chapter_entities,
            entity_id_by_alias=entity_id_by_alias,
            active_relation_by_signature=active_relation_by_signature,
            active_state_relation_by_key=active_state_relation_by_key,
        )

        self._emit_progress(
            stage="graph-community-build",
            title="Building communities",
            message=f"所有文段已完成 episode/fact 写入，正在聚合 {total_chunks} 个文段对应的 community 结构。",
            processed_snippets=total_chunks,
            total_snippets=total_chunks,
            details={"phase": "community-build"},
        )
        communities = self._build_communities(
            graph=graph,
            chapter_entities=chapter_entities,
            chapter_episode_ids=chapter_episode_ids,
            chapter_provenance=chapter_provenance,
        )
        graph.communities.update(communities)

        self._emit_progress(
            stage="graph-saga-build",
            title="Building sagas",
            message="正在把跨章节叙事主线组织成 saga 结构。",
            processed_snippets=total_chunks,
            total_snippets=total_chunks,
            details={"phase": "saga-build", "community_count": len(communities)},
        )
        sagas = self._build_sagas(
            graph=graph,
            chapter_entities=chapter_entities,
            chapter_episode_ids=chapter_episode_ids,
            chapter_provenance=chapter_provenance,
        )
        graph.sagas.update(sagas)

        for relation in graph.relations.values():
            chapter_relation_ids[relation.valid_at_chapter].add(relation.edge_id)
            if relation.status == "active":
                chapter_active_relation_ids[relation.valid_at_chapter].add(relation.edge_id)
            else:
                chapter_invalidated_relation_ids[relation.valid_at_chapter].add(relation.edge_id)

        self._emit_progress(
            stage="graph-timeline-build",
            title="Assembling chapter timeline",
            message="正在汇总 chapter timeline、active facts 和 invalidated facts。",
            processed_snippets=total_chunks,
            total_snippets=total_chunks,
            details={"phase": "timeline-build", "saga_count": len(sagas)},
        )
        graph.chapter_timeline = self._build_chapter_timeline(
            graph=graph,
            chapter_episode_ids=chapter_episode_ids,
            chapter_entities=chapter_entities,
            chapter_relation_ids=chapter_relation_ids,
            chapter_active_relation_ids=chapter_active_relation_ids,
            chapter_invalidated_relation_ids=chapter_invalidated_relation_ids,
            chapter_provenance=chapter_provenance,
            chapter_paragraph_count=chapter_paragraph_count,
        )
        self._attach_chapter_collections(graph)

        for entity in graph.entities.values():
            chapter_span = entity.metadata.get("chapter_span", [])
            entity.summary = self._entity_summary(entity, chapter_span)
            entity.metadata["episode_count"] = len(set(entity.episode_ids))
            entity.metadata["alias_count"] = len(entity.aliases)

        graph.metadata["graph_stats"] = graph.stats().model_dump()
        graph.metadata["chapter_timeline_count"] = len(graph.chapter_timeline)
        graph.metadata["active_relation_count"] = sum(1 for edge in graph.relations.values() if edge.status == "active")
        graph.metadata["invalidated_relation_count"] = sum(1 for edge in graph.relations.values() if edge.status == "invalidated")
        self._emit_progress(
            stage="graph-build-finished",
            title="Temporal graph assembled",
            message="图谱内存结构已经构建完成，等待持久化写盘。",
            processed_snippets=total_chunks,
            total_snippets=total_chunks,
            details={
                "phase": "graph-build-finished",
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
                "community_count": len(graph.communities),
                "saga_count": len(graph.sagas),
            },
        )
        if self.build_logger is not None:
            self.build_logger.build_end(
                {
                    "total_episodes": total_chunks,
                    "entity_count": len(graph.entities),
                    "relation_count": len(graph.relations),
                    "community_count": len(graph.communities),
                    "saga_count": len(graph.sagas),
                    "chapter_timeline_count": len(graph.chapter_timeline),
                    "active_relation_count": int(graph.metadata.get("active_relation_count", 0)),
                    "invalidated_relation_count": int(graph.metadata.get("invalidated_relation_count", 0)),
                    "llm_calls": int(graph.metadata.get("llm_calls", 0)),
                    "llm_skipped": int(graph.metadata.get("llm_skipped", 0)),
                }
            )
            self.build_logger.close()
        return graph

    def _emit_progress(self, **payload: dict) -> None:
        if self.progress_callback is not None:
            self.progress_callback(payload)

    def _resolve_entities(
        self,
        chunk: BookChunk,
        graph: TemporalContextGraph,
        entity_id_by_alias: dict[str, str],
        llm_episode_extraction: llm_extraction.EpisodeGraphExtraction | None = None,
    ) -> list[EntityNode]:
        extraction_candidates = self._entity_candidates_from_extraction(chunk, llm_episode_extraction)
        resolved: list[EntityNode] = []
        for raw_name, raw_type, aliases, resolution_hint, evidence, confidence, resolution_strategy in extraction_candidates:
            canonical_name = _normalize_entity_name(raw_name)
            aliases = sorted({*aliases, *(_entity_aliases(canonical_name))})
            alias_keys = {_slugify(alias) for alias in aliases}
            entity_id = None
            if resolution_hint:
                entity_id = entity_id_by_alias.get(_slugify(resolution_hint))
            for alias_key in alias_keys:
                entity_id = entity_id_by_alias.get(alias_key)
                if entity_id:
                    break
            if entity_id is None:
                entity_id = f"entity_{_slugify(canonical_name)}"
                if entity_id in graph.entities:
                    relation_index = len(graph.entities) + 1
                    entity_id = f"{entity_id}_{relation_index:03d}"
                entity = EntityNode(
                    entity_id=entity_id,
                    canonical_name=canonical_name,
                    aliases=aliases,
                    entity_type=_infer_entity_type(canonical_name, raw_type, chunk),  # type: ignore[arg-type]
                    metadata={
                        "resolution_strategy": resolution_strategy,
                        "resolution_hint": resolution_hint,
                        "last_evidence": evidence,
                        "last_confidence": confidence,
                    },
                )
                graph.entities[entity_id] = entity
            else:
                entity = graph.entities[entity_id]
                for alias in aliases:
                    if alias not in entity.aliases:
                        entity.aliases.append(alias)
                if canonical_name not in entity.aliases and canonical_name != entity.canonical_name:
                    entity.aliases.append(canonical_name)
                entity.metadata["resolution_strategy"] = resolution_strategy
                if resolution_hint:
                    entity.metadata["resolution_hint"] = resolution_hint
                if evidence:
                    entity.metadata["last_evidence"] = evidence
                entity.metadata["last_confidence"] = confidence
            for alias_key in alias_keys:
                entity_id_by_alias[alias_key] = entity.entity_id
            resolved.append(entity)
        deduped = {entity.entity_id: entity for entity in resolved}
        return list(deduped.values())

    def _entity_candidates_from_extraction(
        self,
        chunk: BookChunk,
        llm_episode_extraction: llm_extraction.EpisodeGraphExtraction | None,
    ) -> list[tuple[str, str, list[str], str, str, float, str]]:
        if llm_episode_extraction and llm_episode_extraction.entities:
            rows: list[tuple[str, str, list[str], str, str, float, str]] = []
            for item in llm_episode_extraction.entities:
                aliases = [alias for alias in item.aliases if alias.strip()]
                rows.append(
                    (
                        item.canonical_name,
                        item.entity_type,
                        aliases,
                        item.resolution_hint,
                        item.evidence,
                        item.confidence,
                        "llm-assisted",
                    )
                )
            return rows
        return []

    def _extract_and_resolve_relations(
        self,
        *,
        chunk: BookChunk,
        episode: EpisodeNode,
        entity_nodes: list[EntityNode],
        graph: TemporalContextGraph,
        now: str,
        active_relation_by_signature: dict[str, str],
        active_state_relation_by_key: dict[str, str],
        relation_version_counter: Counter[str],
        llm_episode_extraction: llm_extraction.EpisodeGraphExtraction | None = None,
    ) -> list[str]:
        relation_ids: list[str] = []
        if llm_episode_extraction and llm_episode_extraction.facts:
            for fact_candidate in llm_episode_extraction.facts:
                source_entity = self._match_entity_by_name(fact_candidate.source, entity_nodes)
                target_entity = self._match_entity_by_name(fact_candidate.target, entity_nodes)
                if source_entity is None or target_entity is None or source_entity.entity_id == target_entity.entity_id:
                    continue
                relation_ids.extend(
                    self._upsert_relation_edge(
                        chunk=chunk,
                        episode=episode,
                        graph=graph,
                        now=now,
                        active_relation_by_signature=active_relation_by_signature,
                        active_state_relation_by_key=active_state_relation_by_key,
                        relation_version_counter=relation_version_counter,
                        source_entity=source_entity,
                        target_entity=target_entity,
                        relation_type=fact_candidate.relation_type,
                        state_family=fact_candidate.state_family,
                        directionality=fact_candidate.directionality,
                        fact_text=fact_candidate.fact,
                        evidence_text=fact_candidate.evidence or fact_candidate.fact,
                        extraction_mode="llm-assisted",
                        confidence=fact_candidate.confidence,
                    )
                )
        return sorted(set(relation_ids))

    def _upsert_relation_edge(
        self,
        *,
        chunk: BookChunk,
        episode: EpisodeNode,
        graph: TemporalContextGraph,
        now: str,
        active_relation_by_signature: dict[str, str],
        active_state_relation_by_key: dict[str, str],
        relation_version_counter: Counter[str],
        source_entity: EntityNode,
        target_entity: EntityNode,
        relation_type: str,
        state_family: str,
        directionality: RelationDirectionality,
        fact_text: str,
        evidence_text: str,
        extraction_mode: str,
        confidence: float,
    ) -> list[str]:
        signature = _fact_signature(
            relation_type=relation_type,
            state_family=state_family,
            source_entity_id=source_entity.entity_id,
            target_entity_id=target_entity.entity_id,
            directionality=directionality,
        )
        existing_edge_id = active_relation_by_signature.get(signature)
        if existing_edge_id:
            edge = graph.relations[existing_edge_id]
            edge.weight += 1.0
            if episode.episode_id not in edge.episode_ids:
                edge.episode_ids.append(episode.episode_id)
            edge.provenance.append(_build_provenance(chunk, "relation", {"sentence": evidence_text}))
            edge.metadata["last_seen_episode_id"] = episode.episode_id
            edge.metadata["extraction_mode"] = extraction_mode
            edge.metadata["confidence"] = max(float(edge.metadata.get("confidence", 0.0)), confidence)
            return [edge.edge_id]

        state_key = _state_key(state_family, source_entity.entity_id, directionality, target_entity.entity_id)
        superseded_edges: list[str] = []
        if state_key:
            active_state_edge_id = active_state_relation_by_key.get(state_key)
            if active_state_edge_id and active_state_edge_id in graph.relations:
                active_edge = graph.relations[active_state_edge_id]
                if active_edge.target_entity_id != target_entity.entity_id:
                    active_edge.status = "invalidated"
                    active_edge.invalid_at_chapter = chunk.chapter_index
                    active_edge.invalid_at_paragraph = chunk.paragraph_index
                    active_edge.expired_at = now
                    active_edge.invalidated_by_edge_id = "pending"
                    superseded_edges.append(active_edge.edge_id)

        base_signature_slug = _slugify(signature)
        relation_version_counter[base_signature_slug] += 1
        version = relation_version_counter[base_signature_slug]
        edge_id = f"edge_{base_signature_slug}_v{version:03d}"
        reference_time = f"narrative://{chunk.book_id}/c{chunk.chapter_index:03d}/p{chunk.paragraph_index:03d}"
        edge = RelationEdge(
            edge_id=edge_id,
            source_entity_id=source_entity.entity_id,
            target_entity_id=target_entity.entity_id,
            relation_type=relation_type,
            state_family=state_family,
            directionality=directionality,
            fact=fact_text,
            fact_signature=signature,
            weight=1.0,
            status="active",
            valid_at_chapter=chunk.chapter_index,
            valid_at_paragraph=chunk.paragraph_index,
            created_at=now,
            reference_time=reference_time,
            supersedes_edge_ids=superseded_edges,
            episode_ids=[episode.episode_id],
            metadata={
                "chapter_id": chunk.chapter_id,
                "paragraph_id": chunk.paragraph_id,
                "sentence_excerpt": _excerpt(evidence_text, limit=240),
                "state_key": state_key,
                "extraction_mode": extraction_mode,
                "confidence": confidence,
            },
            provenance=[_build_provenance(chunk, "relation", {"sentence": evidence_text, "reference_time": reference_time})],
        )
        graph.relations[edge_id] = edge
        active_relation_by_signature[signature] = edge_id
        if state_key:
            active_state_relation_by_key[state_key] = edge_id
        for superseded_edge_id in superseded_edges:
            graph.relations[superseded_edge_id].invalidated_by_edge_id = edge_id
        return [edge_id]

    def _match_entity_by_name(self, name: str, entity_nodes: list[EntityNode]) -> EntityNode | None:
        normalized = _normalize_entity_name(name)
        if not normalized:
            return None
        lowered = normalized.lower()
        for entity in entity_nodes:
            if entity.canonical_name.lower() == lowered:
                return entity
            if any(alias.lower() == lowered for alias in entity.aliases):
                return entity
        for entity in entity_nodes:
            forms = {entity.canonical_name.lower(), *(alias.lower() for alias in entity.aliases)}
            if any(lowered in form or form in lowered for form in forms if form):
                return entity
        return None

    def _entity_summary(self, entity: EntityNode, chapter_span: list[int]) -> str:
        if not chapter_span:
            return f"{entity.canonical_name} appears in the current book graph."
        return (
            f"{entity.canonical_name} is tracked as a {entity.entity_type} "
            f"from chapter {chapter_span[0]} to chapter {chapter_span[-1]} "
            f"across {entity.mention_count} mentions."
        )

    def _build_communities(
        self,
        graph: TemporalContextGraph,
        chapter_entities: dict[int, set[str]],
        chapter_episode_ids: dict[int, list[str]],
        chapter_provenance: dict[int, list[GraphProvenance]],
    ) -> dict[str, CommunityNode]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        relation_ids_by_entity: dict[str, set[str]] = defaultdict(set)
        for edge in graph.relations.values():
            adjacency[edge.source_entity_id].add(edge.target_entity_id)
            adjacency[edge.target_entity_id].add(edge.source_entity_id)
            relation_ids_by_entity[edge.source_entity_id].add(edge.edge_id)
            relation_ids_by_entity[edge.target_entity_id].add(edge.edge_id)

        communities: dict[str, CommunityNode] = {}
        visited: set[str] = set()
        component_index = 1

        for entity_id in sorted(graph.entities):
            if entity_id in visited:
                continue
            stack = [entity_id]
            component: set[str] = set()
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.add(current)
                stack.extend(adjacency[current] - visited)

            chapters = sorted(
                chapter_index
                for chapter_index, entity_ids in chapter_entities.items()
                if entity_ids.intersection(component)
            )
            episode_ids = sorted(
                {
                    episode_id
                    for chapter_index in chapters
                    for episode_id in chapter_episode_ids[chapter_index]
                    if set(graph.episodes[episode_id].entity_ids).intersection(component)
                }
            )
            relation_ids = sorted({edge_id for entity in component for edge_id in relation_ids_by_entity[entity]})
            label_names = [
                graph.entities[candidate].canonical_name
                for candidate in sorted(component, key=lambda item: graph.entities[item].mention_count, reverse=True)[:3]
            ]
            community_id = f"community_{component_index:03d}"
            summary = (
                f"Community {component_index} links "
                f"{', '.join(label_names) if label_names else 'local entities'} "
                f"through {len(relation_ids)} temporal facts."
            )
            communities[community_id] = CommunityNode(
                community_id=community_id,
                label="/".join(label_names) or community_id,
                summary=summary,
                entity_ids=sorted(component),
                episode_ids=episode_ids,
                relation_ids=relation_ids,
                chapter_start=chapters[0] if chapters else 0,
                chapter_end=chapters[-1] if chapters else 0,
                metadata={"entity_count": len(component), "dominant_entities": label_names},
                provenance=[item for chapter_index in chapters for item in chapter_provenance[chapter_index][:2]],
            )
            for episode_id in episode_ids:
                graph.episodes[episode_id].community_ids.append(community_id)
            component_index += 1

        return communities

    def _build_sagas(
        self,
        graph: TemporalContextGraph,
        chapter_entities: dict[int, set[str]],
        chapter_episode_ids: dict[int, list[str]],
        chapter_provenance: dict[int, list[GraphProvenance]],
    ) -> dict[str, SagaNode]:
        if not chapter_episode_ids:
            return {}

        sagas: dict[str, SagaNode] = {}
        sorted_chapters = sorted(chapter_episode_ids)
        saga_groups: list[list[int]] = []
        current_group: list[int] = []

        for chapter_index in sorted_chapters:
            if not current_group:
                current_group = [chapter_index]
                continue
            previous_entities = chapter_entities.get(current_group[-1], set())
            current_entities = chapter_entities.get(chapter_index, set())
            if previous_entities.intersection(current_entities):
                current_group.append(chapter_index)
            else:
                saga_groups.append(current_group)
                current_group = [chapter_index]
        if current_group:
            saga_groups.append(current_group)

        for index, chapters in enumerate(saga_groups, start=1):
            episode_ids = [episode_id for chapter_index in chapters for episode_id in chapter_episode_ids[chapter_index]]
            entity_counter = Counter(
                entity_id for chapter_index in chapters for entity_id in chapter_entities.get(chapter_index, set())
            )
            dominant_entities = [entity_id for entity_id, _ in entity_counter.most_common(4)]
            label_parts = [graph.entities[entity_id].canonical_name for entity_id in dominant_entities[:2]]
            relation_ids = [
                relation.edge_id
                for relation in graph.relations.values()
                if relation.valid_at_chapter >= chapters[0] and relation.valid_at_chapter <= chapters[-1]
            ]
            summary = (
                f"Chapters {chapters[0]}-{chapters[-1]} track "
                f"{', '.join(label_parts) if label_parts else 'the current narrative thread'} "
                f"through {len(episode_ids)} episodes and {len(relation_ids)} facts."
            )
            saga_id = f"saga_{index:03d}"
            sagas[saga_id] = SagaNode(
                saga_id=saga_id,
                label=" / ".join(label_parts) or f"chapters_{chapters[0]}_{chapters[-1]}",
                episode_ids=episode_ids,
                entity_ids=dominant_entities,
                relation_ids=relation_ids,
                chapter_start=chapters[0],
                chapter_end=chapters[-1],
                summary=summary,
                metadata={"chapter_count": len(chapters), "dominant_entities": dominant_entities},
                provenance=[item for chapter_index in chapters for item in chapter_provenance[chapter_index][:2]],
            )
            for episode_id in episode_ids:
                graph.episodes[episode_id].saga_ids.append(saga_id)

        return sagas

    def _build_chapter_timeline(
        self,
        graph: TemporalContextGraph,
        chapter_episode_ids: dict[int, list[str]],
        chapter_entities: dict[int, set[str]],
        chapter_relation_ids: dict[int, set[str]],
        chapter_active_relation_ids: dict[int, set[str]],
        chapter_invalidated_relation_ids: dict[int, set[str]],
        chapter_provenance: dict[int, list[GraphProvenance]],
        chapter_paragraph_count: Counter[int],
    ) -> list[ChapterTimelineEntry]:
        timeline: list[ChapterTimelineEntry] = []
        saga_map: dict[int, list[str]] = defaultdict(list)
        community_map: dict[int, list[str]] = defaultdict(list)
        for saga in graph.sagas.values():
            for chapter_index in range(saga.chapter_start, saga.chapter_end + 1):
                saga_map[chapter_index].append(saga.saga_id)
        for community in graph.communities.values():
            for chapter_index in range(community.chapter_start, community.chapter_end + 1):
                community_map[chapter_index].append(community.community_id)

        for chapter_index in sorted(chapter_episode_ids):
            chapter_id = graph.episodes[chapter_episode_ids[chapter_index][0]].chapter_id
            title = graph.chapters[f"chapter_{chapter_index:03d}"].title
            entity_names = [
                graph.entities[entity_id].canonical_name
                for entity_id in sorted(
                    chapter_entities.get(chapter_index, set()),
                    key=lambda item: graph.entities[item].mention_count,
                    reverse=True,
                )[:3]
            ]
            timeline.append(
                ChapterTimelineEntry(
                    chapter_id=chapter_id,
                    chapter_index=chapter_index,
                    title=title,
                    episode_ids=chapter_episode_ids[chapter_index],
                    entity_ids=sorted(chapter_entities.get(chapter_index, set())),
                    relation_ids=sorted(chapter_relation_ids.get(chapter_index, set())),
                    active_relation_ids=sorted(chapter_active_relation_ids.get(chapter_index, set())),
                    invalidated_relation_ids=sorted(chapter_invalidated_relation_ids.get(chapter_index, set())),
                    community_ids=community_map.get(chapter_index, []),
                    saga_ids=saga_map.get(chapter_index, []),
                    spoiler_level=max(
                        graph.episodes[episode_id].spoiler_level for episode_id in chapter_episode_ids[chapter_index]
                    ),
                    paragraph_count=chapter_paragraph_count[chapter_index],
                    summary=(
                        f"Chapter {chapter_index} centers on "
                        f"{', '.join(entity_names) if entity_names else 'the local narrative state'}."
                    ),
                    metadata={"dominant_entities": entity_names},
                    provenance=chapter_provenance[chapter_index][:4],
                )
            )
        return timeline

    def _attach_chapter_collections(self, graph: TemporalContextGraph) -> None:
        for timeline_entry in graph.chapter_timeline:
            chapter = graph.chapters.get(f"chapter_{timeline_entry.chapter_index:03d}")
            if chapter is None:
                continue
            chapter.community_ids = timeline_entry.community_ids
            chapter.saga_ids = timeline_entry.saga_ids
            chapter.active_relation_ids = timeline_entry.active_relation_ids
            chapter.invalidated_relation_ids = timeline_entry.invalidated_relation_ids
            chapter.metadata["timeline_summary"] = timeline_entry.summary
            for relation_id in timeline_entry.relation_ids:
                if relation_id not in chapter.relation_ids:
                    chapter.relation_ids.append(relation_id)

    def _extract_episode_with_llm(
        self,
        *,
        chunk: BookChunk,
        graph: TemporalContextGraph,
    ) -> llm_extraction.EpisodeGraphExtraction | None:
        if self.extractor_runtime is None:
            return None

        known_entities = [
            llm_extraction.KnownEntityCandidate(
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                entity_type=entity.entity_type,
                aliases=entity.aliases,
                mention_count=entity.mention_count,
                last_seen_chapter=entity.last_seen_chapter,
                last_seen_paragraph=entity.last_seen_paragraph,
            )
            for entity in sorted(graph.entities.values(), key=lambda item: item.mention_count, reverse=True)
            if entity.last_seen_chapter < chunk.chapter_index
            or (
                entity.last_seen_chapter == chunk.chapter_index
                and entity.last_seen_paragraph < chunk.paragraph_index
            )
        ]
        recent_episode_contexts = [
            episode.text for episode in sorted(graph.episodes.values(), key=lambda item: item.episode_index)[-3:]
        ]
        try:
            graph.metadata["llm_calls"] = int(graph.metadata.get("llm_calls", 0)) + 1
            self._emit_progress(
                stage="llm-request-dispatched",
                title="LLM entity/fact resolution",
                message=f"Dispatching entity/fact extraction prompt for {chunk.chunk_id}.",
                current_snippet_id=chunk.chunk_id,
                current_chapter_index=chunk.chapter_index,
                current_paragraph_index=chunk.paragraph_index,
                details={
                    "phase": "llm-request-dispatched",
                    "provider": self.extractor_runtime.provider_label,
                    "source_paragraph_indices": chunk.metadata.get("source_paragraph_indices", []),
                    "source_paragraph_count": chunk.metadata.get("source_paragraph_count", 1),
                    "packet_token_count": chunk.metadata.get("packet_token_count", len(chunk.text)),
                    "is_merged_packet": chunk.metadata.get("is_merged_packet", False),
                },
            )
            extraction = llm_extraction.extract_episode_graph_with_llm(
                runtime=self.extractor_runtime,
                chunk=chunk,
                known_entities=known_entities,
                recent_episode_contexts=recent_episode_contexts,
            )
            self._emit_progress(
                stage="llm-response-received",
                title="LLM response received",
                message=(
                    f"Received LLM extraction for {chunk.chunk_id}: "
                    f"{len(extraction.entities)} entities, {len(extraction.facts)} facts."
                ),
                current_snippet_id=chunk.chunk_id,
                current_chapter_index=chunk.chapter_index,
                current_paragraph_index=chunk.paragraph_index,
                details={
                    "phase": "llm-response-received",
                    "entity_candidates": len(extraction.entities),
                    "fact_candidates": len(extraction.facts),
                    "source_paragraph_indices": chunk.metadata.get("source_paragraph_indices", []),
                    "source_paragraph_count": chunk.metadata.get("source_paragraph_count", 1),
                    "packet_token_count": chunk.metadata.get("packet_token_count", len(chunk.text)),
                    "is_merged_packet": chunk.metadata.get("is_merged_packet", False),
                },
            )
            return extraction
        except Exception as exc:
            graph.metadata.setdefault("llm_extraction_warnings", [])
            graph.metadata["llm_extraction_warnings"].append(
                {
                    "chunk_id": chunk.chunk_id,
                    "chapter_index": chunk.chapter_index,
                    "paragraph_index": chunk.paragraph_index,
                    "reason": str(exc),
                }
            )
            if self.strict_llm_extraction:
                raise RuntimeError(f"strict llm extraction failed for {chunk.chunk_id}: {exc}") from exc
            self._emit_progress(
                stage="llm-request-failed",
                title="LLM extraction failed",
                message=f"LLM extraction failed for {chunk.chunk_id}; skipping episode.",
                current_snippet_id=chunk.chunk_id,
                current_chapter_index=chunk.chapter_index,
                current_paragraph_index=chunk.paragraph_index,
                details={
                    "phase": "llm-request-failed",
                    "error": str(exc),
                    "source_paragraph_indices": chunk.metadata.get("source_paragraph_indices", []),
                    "source_paragraph_count": chunk.metadata.get("source_paragraph_count", 1),
                    "packet_token_count": chunk.metadata.get("packet_token_count", len(chunk.text)),
                    "is_merged_packet": chunk.metadata.get("is_merged_packet", False),
                },
            )
            return None

    def _consolidate_chapters(
        self,
        *,
        graph: TemporalContextGraph,
        chapter_entities: dict[int, set[str]],
        entity_id_by_alias: dict[str, str],
        active_relation_by_signature: dict[str, str],
        active_state_relation_by_key: dict[str, str],
    ) -> None:
        for chapter_index, entity_ids in chapter_entities.items():
            canonical_groups: dict[str, list[str]] = defaultdict(list)
            for entity_id in entity_ids:
                entity = graph.entities.get(entity_id)
                if entity is None:
                    continue
                canonical_groups[_slugify(entity.canonical_name)].append(entity_id)
            merged_pairs = 0
            for group in canonical_groups.values():
                if len(group) < 2:
                    continue
                primary_id = max(group, key=lambda item: graph.entities[item].mention_count)
                for secondary_id in group:
                    if secondary_id == primary_id or secondary_id not in graph.entities:
                        continue
                    self._merge_entity_into_primary(
                        graph=graph,
                        primary_id=primary_id,
                        secondary_id=secondary_id,
                        entity_id_by_alias=entity_id_by_alias,
                    )
                    entity_ids.discard(secondary_id)
                    entity_ids.add(primary_id)
                    merged_pairs += 1
            deduped_relations = self._deduplicate_relations_for_chapter(graph=graph, chapter_index=chapter_index)
            graph.metadata["chapter_consolidations"].append(
                {
                    "chapter_index": chapter_index,
                    "merged_entities": merged_pairs,
                    "deduplicated_relations": deduped_relations,
                }
            )
        self._rebuild_relation_indexes(
            graph=graph,
            active_relation_by_signature=active_relation_by_signature,
            active_state_relation_by_key=active_state_relation_by_key,
        )

    def _merge_entity_into_primary(
        self,
        *,
        graph: TemporalContextGraph,
        primary_id: str,
        secondary_id: str,
        entity_id_by_alias: dict[str, str],
    ) -> None:
        primary = graph.entities.get(primary_id)
        secondary = graph.entities.get(secondary_id)
        if primary is None or secondary is None:
            return
        primary.aliases = sorted(set(primary.aliases).union(secondary.aliases).union({secondary.canonical_name}))
        primary.mention_count += secondary.mention_count
        primary.episode_ids = sorted(set(primary.episode_ids).union(secondary.episode_ids))
        if primary.first_seen_chapter == 0 or (
            secondary.first_seen_chapter
            and (secondary.first_seen_chapter, secondary.first_seen_paragraph)
            < (primary.first_seen_chapter, primary.first_seen_paragraph)
        ):
            primary.first_seen_chapter = secondary.first_seen_chapter
            primary.first_seen_paragraph = secondary.first_seen_paragraph
        if (secondary.last_seen_chapter, secondary.last_seen_paragraph) > (
            primary.last_seen_chapter,
            primary.last_seen_paragraph,
        ):
            primary.last_seen_chapter = secondary.last_seen_chapter
            primary.last_seen_paragraph = secondary.last_seen_paragraph
        for alias in _entity_alias_forms(primary).union(_entity_alias_forms(secondary)):
            entity_id_by_alias[alias] = primary_id
        for episode in graph.episodes.values():
            if secondary_id in episode.entity_ids:
                episode.entity_ids = [primary_id if entity_id == secondary_id else entity_id for entity_id in episode.entity_ids]
                episode.entity_ids = sorted(set(episode.entity_ids))
        for chapter in graph.chapters.values():
            if secondary_id in chapter.entity_ids:
                chapter.entity_ids = sorted({primary_id if entity_id == secondary_id else entity_id for entity_id in chapter.entity_ids})
        for relation in graph.relations.values():
            if relation.source_entity_id == secondary_id:
                relation.source_entity_id = primary_id
            if relation.target_entity_id == secondary_id:
                relation.target_entity_id = primary_id
        del graph.entities[secondary_id]

    def _deduplicate_relations_for_chapter(self, *, graph: TemporalContextGraph, chapter_index: int) -> int:
        seen: dict[tuple[str, str, str], str] = {}
        removed = 0
        for edge_id, relation in list(graph.relations.items()):
            if relation.valid_at_chapter != chapter_index or relation.state_family not in CHAPTER_CONSOLIDATION_FAMILIES:
                continue
            relation.fact_signature = _fact_signature(
                relation_type=relation.relation_type,
                state_family=relation.state_family,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
                directionality=relation.directionality,
            )
            dedupe_key = (relation.fact_signature, relation.status, str(relation.invalidated_by_edge_id or ""))
            existing_edge_id = seen.get(dedupe_key)
            if existing_edge_id is None:
                seen[dedupe_key] = edge_id
                continue
            existing = graph.relations[existing_edge_id]
            existing.weight += relation.weight
            existing.episode_ids = sorted(set(existing.episode_ids).union(relation.episode_ids))
            existing.provenance.extend(relation.provenance)
            existing.metadata["confidence"] = max(
                float(existing.metadata.get("confidence", 0.0)),
                float(relation.metadata.get("confidence", 0.0)),
            )
            for chapter in graph.chapters.values():
                if edge_id in chapter.relation_ids:
                    chapter.relation_ids = [existing_edge_id if rid == edge_id else rid for rid in chapter.relation_ids]
                    chapter.relation_ids = sorted(set(chapter.relation_ids))
            for episode in graph.episodes.values():
                if edge_id in episode.relation_ids:
                    episode.relation_ids = [existing_edge_id if rid == edge_id else rid for rid in episode.relation_ids]
                    episode.relation_ids = sorted(set(episode.relation_ids))
            del graph.relations[edge_id]
            removed += 1
        return removed

    def _rebuild_relation_indexes(
        self,
        *,
        graph: TemporalContextGraph,
        active_relation_by_signature: dict[str, str],
        active_state_relation_by_key: dict[str, str],
    ) -> None:
        active_relation_by_signature.clear()
        active_state_relation_by_key.clear()
        for relation in graph.relations.values():
            relation.fact_signature = _fact_signature(
                relation_type=relation.relation_type,
                state_family=relation.state_family,
                source_entity_id=relation.source_entity_id,
                target_entity_id=relation.target_entity_id,
                directionality=relation.directionality,
            )
            if relation.status == "active":
                active_relation_by_signature[relation.fact_signature] = relation.edge_id
                state_key = _state_key(
                    relation.state_family,
                    relation.source_entity_id,
                    relation.directionality,
                    relation.target_entity_id,
                )
                if state_key:
                    active_state_relation_by_key[state_key] = relation.edge_id


    def _rebuild_state_from_graph(
        self,
        graph: TemporalContextGraph,
    ) -> tuple[dict[str, str], dict[str, str], dict[str, str], Counter[str]]:
        entity_id_by_alias: dict[str, str] = {}
        for entity in graph.entities.values():
            for alias in _entity_alias_forms(entity):
                entity_id_by_alias.setdefault(alias, entity.entity_id)
        active_relation_by_signature: dict[str, str] = {}
        active_state_relation_by_key: dict[str, str] = {}
        relation_version_counter: Counter[str] = Counter()
        for edge in graph.relations.values():
            edge.fact_signature = _fact_signature(
                relation_type=edge.relation_type,
                state_family=edge.state_family,
                source_entity_id=edge.source_entity_id,
                target_entity_id=edge.target_entity_id,
                directionality=edge.directionality,
            )
            base_slug = _slugify(edge.fact_signature)
            version = int(edge.edge_id.rsplit("_v", 1)[-1]) if "_v" in edge.edge_id else 1
            relation_version_counter[base_slug] = max(relation_version_counter.get(base_slug, 0), version)
            if edge.status == "active":
                active_relation_by_signature[edge.fact_signature] = edge.edge_id
                state_key = _state_key(
                    edge.state_family, edge.source_entity_id, edge.directionality, edge.target_entity_id
                )
                if state_key:
                    active_state_relation_by_key[state_key] = edge.edge_id
        return entity_id_by_alias, active_relation_by_signature, active_state_relation_by_key, relation_version_counter

    def _rebuild_chapter_indexes(
        self,
        graph: TemporalContextGraph,
    ) -> tuple[dict[int, set[str]], dict[int, list[str]], dict[int, set[str]]]:
        chapter_entities: dict[int, set[str]] = defaultdict(set)
        chapter_episode_ids: dict[int, list[str]] = defaultdict(list)
        chapter_relation_ids: dict[int, set[str]] = defaultdict(set)
        for ep in graph.episodes.values():
            chapter_episode_ids[ep.chapter_index].append(ep.episode_id)
            chapter_entities[ep.chapter_index].update(ep.entity_ids)
            chapter_relation_ids[ep.chapter_index].update(ep.relation_ids)
        return chapter_entities, chapter_episode_ids, chapter_relation_ids


def build_temporal_graph(book: BookRecord) -> TemporalContextGraph:
    return TemporalGraphBuilder().build(book)
