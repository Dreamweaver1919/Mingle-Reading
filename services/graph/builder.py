from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict

from backend.models import BookChunk, BookRecord

from .models import (
    CommunityNode,
    EntityNode,
    EpisodeNode,
    GraphProvenance,
    RelationEdge,
    SagaNode,
    TemporalContextGraph,
)


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", lowered)
    return lowered.strip("_") or "unknown"


def _excerpt(text: str, limit: int = 180) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 3]}..."


def _extract_entity_names(chunk: BookChunk) -> list[str]:
    names: list[str] = []
    raw_names = list(chunk.candidate_characters)
    metadata = chunk.metadata or {}
    metadata_names = metadata.get("characters_present", [])
    if isinstance(metadata_names, list):
        raw_names.extend(name for name in metadata_names if isinstance(name, str))

    if not raw_names:
        raw_names.extend(re.findall(r"\b[A-Z][a-z]{2,}\b", chunk.text))

    for name in raw_names:
        normalized = " ".join(name.strip().split())
        if not normalized:
            continue
        if normalized not in names:
            names.append(normalized)
    return names


def _build_provenance(chunk: BookChunk, source: str, extra_metadata: dict | None = None) -> GraphProvenance:
    metadata = dict(extra_metadata or {})
    metadata.setdefault("spoiler_guard", chunk.spoiler_guard)
    metadata.setdefault("chunk_level", chunk.chunk_level)
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


def _relation_type(chunk: BookChunk) -> str:
    lowered = chunk.text.lower()
    if any(term in lowered for term in ("said", "asked", "replied", "told", "说", "问", "答")):
        return "co_present_dialogue"
    if any(term in lowered for term in ("fought", "killed", "against", "war", "fight", "冲突", "争执")):
        return "co_present_conflict"
    return "co_present"


class TemporalGraphBuilder:
    """Build a local, Graphiti-aligned temporal context graph from book chunks."""

    def build(self, book: BookRecord) -> TemporalContextGraph:
        graph = TemporalContextGraph(
            book_id=book.book_id,
            title=book.title,
            metadata={
                "source_path": book.source_path,
                "chapter_count": book.chapter_count,
                "chunk_count": len(book.chunks),
                "builder": "TemporalGraphBuilder",
            },
        )

        entity_chapters: dict[str, set[int]] = defaultdict(set)
        entity_provenance: dict[str, list[GraphProvenance]] = defaultdict(list)
        entity_episode_ids: dict[str, list[str]] = defaultdict(list)
        chapter_entities: dict[int, set[str]] = defaultdict(set)
        chapter_episode_ids: dict[int, list[str]] = defaultdict(list)
        chapter_provenance: dict[int, list[GraphProvenance]] = defaultdict(list)
        for chunk in book.chunks:
            episode_id = f"episode_{chunk.chunk_id}"
            entity_names = _extract_entity_names(chunk)
            entity_ids = [f"entity_{_slugify(name)}" for name in entity_names]
            provenance = [_build_provenance(chunk, "episode")]

            episode = EpisodeNode(
                episode_id=episode_id,
                book_id=chunk.book_id,
                chunk_id=chunk.chunk_id,
                chapter_id=chunk.chapter_id,
                chapter_index=chunk.chapter_index,
                paragraph_id=chunk.paragraph_id,
                paragraph_index=chunk.paragraph_index,
                text=chunk.text,
                spoiler_level=chunk.spoiler_level,
                tags=list(chunk.tags),
                entities=entity_ids,
                metadata=dict(chunk.metadata),
                provenance=provenance,
            )
            graph.episodes[episode_id] = episode
            chapter_episode_ids[chunk.chapter_index].append(episode_id)
            chapter_provenance[chunk.chapter_index].extend(provenance)

            for name, entity_id in zip(entity_names, entity_ids, strict=False):
                entity = graph.entities.get(entity_id)
                if entity is None:
                    entity = EntityNode(
                        entity_id=entity_id,
                        canonical_name=name,
                        aliases=[name],
                        mention_count=0,
                        first_seen_chapter=chunk.chapter_index,
                        last_seen_chapter=chunk.chapter_index,
                    )
                    graph.entities[entity_id] = entity
                entity.mention_count += 1
                entity.last_seen_chapter = max(entity.last_seen_chapter, chunk.chapter_index)
                entity.first_seen_chapter = min(entity.first_seen_chapter, chunk.chapter_index)
                if episode_id not in entity.episode_ids:
                    entity.episode_ids.append(episode_id)
                entity_chapters[entity_id].add(chunk.chapter_index)
                entity_provenance[entity_id].append(_build_provenance(chunk, "chunk"))
                entity_episode_ids[entity_id].append(episode_id)
                chapter_entities[chunk.chapter_index].add(entity_id)

            relation_ids: list[str] = []
            for source_entity_id, target_entity_id in itertools.combinations(sorted(set(entity_ids)), 2):
                edge_key = (
                    source_entity_id,
                    target_entity_id,
                    _relation_type(chunk),
                )
                edge_id = (
                    f"edge_{source_entity_id.removeprefix('entity_')}"
                    f"__{target_entity_id.removeprefix('entity_')}"
                    f"__{edge_key[2]}"
                )
                edge = graph.relations.get(edge_id)
                if edge is None:
                    edge = RelationEdge(
                        edge_id=edge_id,
                        source_entity_id=source_entity_id,
                        target_entity_id=target_entity_id,
                        relation_type=edge_key[2],
                        validity_start_chapter=chunk.chapter_index,
                        validity_end_chapter=chunk.chapter_index,
                        weight=0.0,
                    )
                    graph.relations[edge_id] = edge
                edge.validity_start_chapter = min(edge.validity_start_chapter, chunk.chapter_index)
                edge.validity_end_chapter = max(edge.validity_end_chapter or chunk.chapter_index, chunk.chapter_index)
                edge.weight += 1.0
                if episode_id not in edge.episode_ids:
                    edge.episode_ids.append(episode_id)
                edge.provenance.append(_build_provenance(chunk, "relation"))
                relation_ids.append(edge_id)

            episode.relation_ids = relation_ids

        for entity_id, entity in graph.entities.items():
            chapters = sorted(entity_chapters[entity_id])
            entity.metadata.update(
                {
                    "chapter_span": chapters,
                    "episode_count": len(set(entity_episode_ids[entity_id])),
                    "provenance_count": len(entity_provenance[entity_id]),
                }
            )

        communities = self._build_communities(
            graph=graph,
            chapter_entities=chapter_entities,
            chapter_episode_ids=chapter_episode_ids,
            chapter_provenance=chapter_provenance,
        )
        graph.communities.update(communities)

        sagas = self._build_sagas(
            graph=graph,
            chapter_entities=chapter_entities,
            chapter_episode_ids=chapter_episode_ids,
            chapter_provenance=chapter_provenance,
        )
        graph.sagas.update(sagas)
        return graph

    def _build_communities(
        self,
        graph: TemporalContextGraph,
        chapter_entities: dict[int, set[str]],
        chapter_episode_ids: dict[int, list[str]],
        chapter_provenance: dict[int, list[GraphProvenance]],
    ) -> dict[str, CommunityNode]:
        adjacency: dict[str, set[str]] = defaultdict(set)
        for edge in graph.relations.values():
            adjacency[edge.source_entity_id].add(edge.target_entity_id)
            adjacency[edge.target_entity_id].add(edge.source_entity_id)

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
                    if set(graph.episodes[episode_id].entities).intersection(component)
                }
            )
            label_names = [
                graph.entities[candidate].canonical_name
                for candidate in sorted(component, key=lambda item: graph.entities[item].mention_count, reverse=True)[:3]
            ]
            community_id = f"community_{component_index:03d}"
            community = CommunityNode(
                community_id=community_id,
                label="/".join(label_names) or community_id,
                entity_ids=sorted(component),
                episode_ids=episode_ids,
                chapter_start=chapters[0] if chapters else 0,
                chapter_end=chapters[-1] if chapters else 0,
                metadata={
                    "entity_count": len(component),
                    "dominant_entities": label_names,
                },
                provenance=[
                    item
                    for chapter_index in chapters
                    for item in chapter_provenance[chapter_index][:2]
                ],
            )
            communities[community_id] = community
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
            overlap = previous_entities.intersection(current_entities)
            if overlap:
                current_group.append(chapter_index)
            else:
                saga_groups.append(current_group)
                current_group = [chapter_index]
        if current_group:
            saga_groups.append(current_group)

        for index, chapters in enumerate(saga_groups, start=1):
            episode_ids = [
                episode_id
                for chapter_index in chapters
                for episode_id in chapter_episode_ids[chapter_index]
            ]
            entity_counter = Counter(
                entity_id
                for chapter_index in chapters
                for entity_id in chapter_entities.get(chapter_index, set())
            )
            dominant_entities = [entity_id for entity_id, _ in entity_counter.most_common(4)]
            label_parts = [graph.entities[entity_id].canonical_name for entity_id in dominant_entities[:2]]
            saga_id = f"saga_{index:03d}"
            summary = (
                f"Chapters {chapters[0]}-{chapters[-1]} track "
                f"{', '.join(label_parts) if label_parts else 'the current narrative thread'} "
                f"across {len(episode_ids)} visible episodes."
            )
            saga = SagaNode(
                saga_id=saga_id,
                label=" / ".join(label_parts) or f"chapters_{chapters[0]}_{chapters[-1]}",
                episode_ids=episode_ids,
                entity_ids=dominant_entities,
                chapter_start=chapters[0],
                chapter_end=chapters[-1],
                summary=summary,
                metadata={
                    "chapter_count": len(chapters),
                    "dominant_entities": dominant_entities,
                },
                provenance=[
                    item
                    for chapter_index in chapters
                    for item in chapter_provenance[chapter_index][:2]
                ],
            )
            sagas[saga_id] = saga
            for episode_id in episode_ids:
                graph.episodes[episode_id].saga_ids.append(saga_id)

        return sagas


def build_temporal_graph(book: BookRecord) -> TemporalContextGraph:
    return TemporalGraphBuilder().build(book)
