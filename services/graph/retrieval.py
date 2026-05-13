from __future__ import annotations

import math
import re
from typing import Any

from .models import GraphHit, GraphQuery, GraphRetrievalResult, TemporalContextGraph


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\u4e00-\u9fff]+", text.lower())


def _text_score(query_tokens: list[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    text_tokens = _tokenize(text)
    if not text_tokens:
        return 0.0
    overlap = sum(1 for token in query_tokens if token in text_tokens)
    return overlap / math.sqrt(len(text_tokens))


def _matches_metadata(metadata: dict[str, Any], filters: dict[str, Any]) -> bool:
    for key, expected in filters.items():
        if metadata.get(key) != expected:
            return False
    return True


def _visible_episode_ids(graph: TemporalContextGraph, max_chapter: int | None) -> list[str]:
    return [
        episode_id
        for episode_id, episode in graph.episodes.items()
        if max_chapter is None or episode.chapter_index <= max_chapter
    ]


class TemporalGraphRetriever:
    """Retrieve progress-aware temporal context with provenance."""

    def retrieve(self, graph: TemporalContextGraph, query: GraphQuery) -> GraphRetrievalResult:
        visible_episode_ids = _visible_episode_ids(graph, query.max_chapter)
        visible_entity_ids = {
            entity_id
            for entity_id, entity in graph.entities.items()
            if query.max_chapter is None or entity.first_seen_chapter <= query.max_chapter
        }
        query_tokens = _tokenize(query.query)
        requested_entity_terms = {item.strip().lower() for item in query.entity_names if item.strip()}
        requested_tags = set(query.tags)

        hits: list[GraphHit] = []

        for episode_id in visible_episode_ids:
            episode = graph.episodes[episode_id]
            if requested_tags and not requested_tags.intersection(episode.tags):
                continue
            if query.metadata_filters and not _matches_metadata(episode.metadata, query.metadata_filters):
                continue

            entity_bonus = 0.0
            if requested_entity_terms:
                entity_names = {
                    graph.entities[entity_id].canonical_name.lower()
                    for entity_id in episode.entities
                    if entity_id in graph.entities
                }
                matches = requested_entity_terms.intersection(entity_names)
                entity_bonus = 0.75 * len(matches)
                if not matches and query.entity_names:
                    continue

            metadata_bonus = 0.25 * sum(
                1
                for key, value in query.metadata_filters.items()
                if episode.metadata.get(key) == value
            )
            tag_bonus = 0.2 * len(requested_tags.intersection(episode.tags))
            score = _text_score(query_tokens, episode.text) + entity_bonus + metadata_bonus + tag_bonus
            if score <= 0:
                continue

            hits.append(
                GraphHit(
                    hit_id=episode_id,
                    hit_type="episode",
                    score=round(score, 4),
                    reason="episode_text+entity+metadata",
                    chapter_index=episode.chapter_index,
                    payload={
                        "chunk_id": episode.chunk_id,
                        "entities": episode.entities,
                        "tags": episode.tags,
                        "community_ids": episode.community_ids,
                        "saga_ids": episode.saga_ids,
                    },
                    provenance=episode.provenance,
                )
            )

        ranked_episode_hits = sorted(hits, key=lambda item: item.score, reverse=True)[: query.top_k]
        output_hits = list(ranked_episode_hits)
        supporting_episode_ids = {hit.hit_id for hit in ranked_episode_hits if hit.hit_type == "episode"}

        if query.include_entities:
            output_hits.extend(
                self._retrieve_entities(graph, query, visible_entity_ids, supporting_episode_ids)
            )
        if query.include_relations:
            output_hits.extend(self._retrieve_relations(graph, query, visible_episode_ids, visible_entity_ids, supporting_episode_ids))
        if query.include_communities:
            output_hits.extend(self._retrieve_communities(graph, query, supporting_episode_ids))
        if query.include_sagas:
            output_hits.extend(self._retrieve_sagas(graph, query, supporting_episode_ids))

        output_hits = sorted(output_hits, key=lambda item: (item.score, -(item.chapter_index or 0)), reverse=True)
        return GraphRetrievalResult(
            query=query,
            hits=output_hits[: max(query.top_k, len(ranked_episode_hits)) + 6],
            visible_episode_count=len(visible_episode_ids),
            visible_entity_count=len(visible_entity_ids),
            graph_metadata=graph.metadata,
        )

    def _retrieve_entities(
        self,
        graph: TemporalContextGraph,
        query: GraphQuery,
        visible_entity_ids: set[str],
        supporting_episode_ids: set[str],
    ) -> list[GraphHit]:
        hits: list[GraphHit] = []
        query_tokens = _tokenize(query.query)
        requested_entities = {value.lower() for value in query.entity_names}
        for entity_id in visible_entity_ids:
            entity = graph.entities[entity_id]
            searchable_text = " ".join([entity.canonical_name, *entity.aliases, entity.entity_type])
            score = _text_score(query_tokens, searchable_text)
            if requested_entities and entity.canonical_name.lower() in requested_entities:
                score += 1.0
            support_overlap = supporting_episode_ids.intersection(entity.episode_ids)
            if support_overlap:
                score += min(len(support_overlap), 3) * 0.3
            if score <= 0:
                continue
            hits.append(
                GraphHit(
                    hit_id=entity.entity_id,
                    hit_type="entity",
                    score=round(score, 4),
                    reason="entity_name+episode_overlap",
                    chapter_index=entity.first_seen_chapter,
                    payload={
                        "canonical_name": entity.canonical_name,
                        "entity_type": entity.entity_type,
                        "mention_count": entity.mention_count,
                        "episode_ids": entity.episode_ids[:6],
                    },
                    provenance=[
                        graph.episodes[episode_id].provenance[0]
                        for episode_id in entity.episode_ids[:3]
                        if episode_id in graph.episodes and graph.episodes[episode_id].provenance
                    ],
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:3]

    def _retrieve_relations(
        self,
        graph: TemporalContextGraph,
        query: GraphQuery,
        visible_episode_ids: list[str],
        visible_entity_ids: set[str],
        supporting_episode_ids: set[str],
    ) -> list[GraphHit]:
        hits: list[GraphHit] = []
        visible_episodes = set(visible_episode_ids)
        requested_entities = {value.lower() for value in query.entity_names}
        for edge in graph.relations.values():
            if edge.source_entity_id not in visible_entity_ids or edge.target_entity_id not in visible_entity_ids:
                continue
            if query.max_chapter is not None and edge.validity_start_chapter > query.max_chapter:
                continue
            if not visible_episodes.intersection(edge.episode_ids):
                continue

            source_name = graph.entities[edge.source_entity_id].canonical_name
            target_name = graph.entities[edge.target_entity_id].canonical_name
            name_text = f"{source_name} {target_name} {edge.relation_type}"
            score = _text_score(_tokenize(query.query), name_text) + min(edge.weight, 3.0) * 0.2
            if requested_entities and {
                source_name.lower(),
                target_name.lower(),
            }.intersection(requested_entities):
                score += 0.8
            if supporting_episode_ids.intersection(edge.episode_ids):
                score += 0.6
            if score <= 0:
                continue
            hits.append(
                GraphHit(
                    hit_id=edge.edge_id,
                    hit_type="relation",
                    score=round(score, 4),
                    reason="edge_validity+entity_overlap",
                    chapter_index=edge.validity_start_chapter,
                    payload={
                        "source_entity_id": edge.source_entity_id,
                        "target_entity_id": edge.target_entity_id,
                        "relation_type": edge.relation_type,
                        "validity_start_chapter": edge.validity_start_chapter,
                        "validity_end_chapter": edge.validity_end_chapter,
                        "episode_ids": edge.episode_ids,
                    },
                    provenance=edge.provenance[:3],
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:3]

    def _retrieve_communities(
        self,
        graph: TemporalContextGraph,
        query: GraphQuery,
        supporting_episode_ids: set[str],
    ) -> list[GraphHit]:
        hits: list[GraphHit] = []
        for community in graph.communities.values():
            if query.max_chapter is not None and community.chapter_start > query.max_chapter:
                continue
            if not supporting_episode_ids.intersection(community.episode_ids):
                continue
            label_score = _text_score(_tokenize(query.query), community.label)
            score = label_score + 0.3 * min(len(community.entity_ids), 4)
            hits.append(
                GraphHit(
                    hit_id=community.community_id,
                    hit_type="community",
                    score=round(score, 4),
                    reason="community_overlap",
                    chapter_index=community.chapter_start,
                    payload={
                        "label": community.label,
                        "entity_ids": community.entity_ids,
                        "episode_ids": community.episode_ids[:6],
                    },
                    provenance=community.provenance[:3],
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:2]

    def _retrieve_sagas(
        self,
        graph: TemporalContextGraph,
        query: GraphQuery,
        supporting_episode_ids: set[str],
    ) -> list[GraphHit]:
        hits: list[GraphHit] = []
        for saga in graph.sagas.values():
            if query.max_chapter is not None and saga.chapter_start > query.max_chapter:
                continue
            if not supporting_episode_ids.intersection(saga.episode_ids):
                continue
            score = _text_score(_tokenize(query.query), f"{saga.label} {saga.summary}") + 0.25 * len(
                supporting_episode_ids.intersection(saga.episode_ids)
            )
            hits.append(
                GraphHit(
                    hit_id=saga.saga_id,
                    hit_type="saga",
                    score=round(score, 4),
                    reason="saga_temporal_context",
                    chapter_index=saga.chapter_start,
                    payload={
                        "label": saga.label,
                        "summary": saga.summary,
                        "chapter_start": saga.chapter_start,
                        "chapter_end": saga.chapter_end,
                        "entity_ids": saga.entity_ids,
                    },
                    provenance=saga.provenance[:3],
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:2]


def search_temporal_graph(
    graph: TemporalContextGraph,
    query: str,
    max_chapter: int,
    top_k: int = 5,
) -> list[GraphHit]:
    result = TemporalGraphRetriever().retrieve(
        graph,
        GraphQuery(query=query, max_chapter=max_chapter, top_k=top_k),
    )
    return result.hits
