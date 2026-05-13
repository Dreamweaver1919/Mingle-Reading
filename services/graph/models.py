from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class GraphProvenance(BaseModel):
    chunk_id: str
    book_id: str
    chapter_id: str
    chapter_index: int
    paragraph_id: str
    paragraph_index: int
    text_excerpt: str
    source: Literal["chunk", "episode", "relation", "community", "saga"] = "chunk"
    metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeNode(BaseModel):
    episode_id: str
    book_id: str
    chunk_id: str
    chapter_id: str
    chapter_index: int
    paragraph_id: str
    paragraph_index: int
    text: str
    spoiler_level: int = 0
    tags: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    relation_ids: list[str] = Field(default_factory=list)
    community_ids: list[str] = Field(default_factory=list)
    saga_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)


class EntityNode(BaseModel):
    entity_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    entity_type: Literal["character", "location", "concept", "unknown"] = "character"
    mention_count: int = 0
    first_seen_chapter: int = 0
    last_seen_chapter: int = 0
    episode_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationEdge(BaseModel):
    edge_id: str
    source_entity_id: str
    target_entity_id: str
    relation_type: str
    validity_start_chapter: int
    validity_end_chapter: int | None = None
    episode_ids: list[str] = Field(default_factory=list)
    weight: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)


class CommunityNode(BaseModel):
    community_id: str
    label: str
    entity_ids: list[str] = Field(default_factory=list)
    episode_ids: list[str] = Field(default_factory=list)
    chapter_start: int = 0
    chapter_end: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)


class SagaNode(BaseModel):
    saga_id: str
    label: str
    episode_ids: list[str] = Field(default_factory=list)
    entity_ids: list[str] = Field(default_factory=list)
    chapter_start: int = 0
    chapter_end: int = 0
    summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)


class TemporalContextGraph(BaseModel):
    book_id: str
    title: str
    episodes: dict[str, EpisodeNode] = Field(default_factory=dict)
    entities: dict[str, EntityNode] = Field(default_factory=dict)
    relations: dict[str, RelationEdge] = Field(default_factory=dict)
    communities: dict[str, CommunityNode] = Field(default_factory=dict)
    sagas: dict[str, SagaNode] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphQuery(BaseModel):
    query: str = ""
    max_chapter: int | None = None
    top_k: int = 5
    entity_names: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata_filters: dict[str, Any] = Field(default_factory=dict)
    include_entities: bool = True
    include_relations: bool = True
    include_communities: bool = True
    include_sagas: bool = True


class GraphHit(BaseModel):
    hit_id: str
    hit_type: Literal["episode", "entity", "relation", "community", "saga"]
    score: float
    reason: str
    chapter_index: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    provenance: list[GraphProvenance] = Field(default_factory=list)


class GraphRetrievalResult(BaseModel):
    query: GraphQuery
    hits: list[GraphHit] = Field(default_factory=list)
    visible_episode_count: int = 0
    visible_entity_count: int = 0
    graph_metadata: dict[str, Any] = Field(default_factory=dict)
