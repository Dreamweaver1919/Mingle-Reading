from pathlib import Path

from backend.common.config import EXAMPLES_DIR
from backend.common.models import BookChunk, BookRecord
from backend.knowledge_base.graph.builder import build_temporal_graph
from backend.knowledge_base.graph.llm_extraction import EpisodeGraphExtraction, ExtractedEntityCandidate, ExtractedFactCandidate
from backend.knowledge_base.graph.models import GraphQuery
from backend.knowledge_base.graph.retrieval import TemporalGraphRetriever, search_temporal_graph
from backend.knowledge_base.graph.storage import load_graph, save_graph
from backend.assets.data.data_processing_scripts.ingest.parser import build_book_record


def demo_graph():
    source = EXAMPLES_DIR / "muse_demo_book.txt"
    record = build_book_record("muse_demo_book", source.read_text(encoding="utf-8"), source)
    return build_temporal_graph(record)


def synthetic_temporal_record() -> BookRecord:
    return BookRecord(
        book_id="synthetic-book",
        title="synthetic-book",
        source_path=str(Path("synthetic-book.txt")),
        chapter_count=2,
        chunks=[
            BookChunk(
                chunk_id="synthetic-c001-p001",
                book_id="synthetic-book",
                chapter_id="chapter-001",
                chapter_index=1,
                paragraph_id="paragraph-001",
                paragraph_index=1,
                text="Lin is in the library. Aya is in the square.",
                chunk_level="l0_raw_paragraph",
                candidate_characters=["Lin", "Aya"],
                metadata={"locations_present": ["library", "square"]},
            ),
            BookChunk(
                chunk_id="synthetic-c001-p002",
                book_id="synthetic-book",
                chapter_id="chapter-001",
                chapter_index=1,
                paragraph_id="paragraph-002",
                paragraph_index=2,
                text="Lin speaks with Aya in the library.",
                chunk_level="l0_raw_paragraph",
                candidate_characters=["Lin", "Aya"],
                metadata={"locations_present": ["library"]},
            ),
            BookChunk(
                chunk_id="synthetic-c002-p001",
                book_id="synthetic-book",
                chapter_id="chapter-002",
                chapter_index=2,
                paragraph_id="paragraph-001",
                paragraph_index=1,
                text="Lin is in the harbor.",
                chunk_level="l0_raw_paragraph",
                candidate_characters=["Lin"],
                metadata={"locations_present": ["harbor"]},
            ),
        ],
    )


def llm_resolution_record() -> BookRecord:
    return BookRecord(
        book_id="llm-resolution-book",
        title="llm-resolution-book",
        source_path=str(Path("llm-resolution.txt")),
        chapter_count=1,
        chunks=[
            BookChunk(
                chunk_id="llm-c001-p001",
                book_id="llm-resolution-book",
                chapter_id="chapter-001",
                chapter_index=1,
                paragraph_id="paragraph-001",
                paragraph_index=1,
                text="José Arcadio stands in Macondo.",
                chunk_level="l0_raw_paragraph",
                candidate_characters=["José Arcadio"],
            ),
            BookChunk(
                chunk_id="llm-c001-p002",
                book_id="llm-resolution-book",
                chapter_id="chapter-001",
                chapter_index=1,
                paragraph_id="paragraph-002",
                paragraph_index=2,
                text="Arcadio speaks with Ursula in the square.",
                chunk_level="l0_raw_paragraph",
                candidate_characters=["Arcadio", "Ursula"],
            ),
        ],
    )


def test_temporal_graph_builds_richer_topology():
    graph = demo_graph()

    assert graph.graph_id.startswith("graph::")
    assert len(graph.chapters) >= 2
    assert len(graph.episodes) >= 6
    assert len(graph.sagas) >= 1
    assert any(entity.canonical_name == "Aya" for entity in graph.entities.values())
    assert any(episode.entities for episode in graph.episodes.values())
    assert any(saga.episode_ids for saga in graph.sagas.values())
    assert len(graph.chapter_timeline) == len(graph.chapters)
    assert any(episode.episode_type == "paragraph" for episode in graph.episodes.values())
    assert all(episode.reference_time.startswith("narrative://") for episode in graph.episodes.values())


def test_temporal_graph_supports_browse_and_lookup_utilities():
    graph = demo_graph()

    browsed = graph.browse("episode", limit=2, max_chapter=1)
    assert len(browsed) == 2
    assert all(item.chapter_index <= 1 for item in browsed)

    aya = next(entity for entity in graph.entities.values() if entity.canonical_name == "Aya")
    neighbors = graph.entity_neighbors(aya.entity_id)
    assert isinstance(neighbors, list)
    if neighbors:
        assert "relation_type" in neighbors[0]

    chapter_head = graph.chapters[:1]
    assert len(chapter_head) == 1
    assert chapter_head[0].node_kind == "chapter"


def test_temporal_graph_search_respects_progress_boundary_and_filters():
    graph = demo_graph()
    hits = search_temporal_graph(graph, "Aya relationship question", max_chapter=1, top_k=10)
    assert hits
    assert all(hit.chapter_index <= 1 for hit in hits)

    retrieval = TemporalGraphRetriever().retrieve(
        graph,
        GraphQuery(
            query="Aya",
            max_chapter=2,
            top_k=8,
            entity_names=["Aya"],
            node_types=["episode", "entity", "chapter", "relation"],
            min_entity_mentions=1,
        ),
    )
    assert retrieval.hits
    assert retrieval.hit_type_breakdown["episode"] >= 1
    assert retrieval.graph_stats.chapter_count >= 2
    assert "max_chapter" in retrieval.applied_filters
    assert "max_paragraph" in retrieval.applied_filters


def test_temporal_graph_invalidates_stateful_facts_and_respects_paragraph_boundary():
    graph = build_temporal_graph(synthetic_temporal_record())

    location_edges = [
        edge
        for edge in graph.relations.values()
        if edge.relation_type == "LOCATED_IN" and graph.entities[edge.source_entity_id].canonical_name == "Lin"
    ]
    assert len(location_edges) == 2
    assert any(edge.status == "invalidated" for edge in location_edges)
    assert any(edge.status == "active" for edge in location_edges)

    invalidated_edge = next(edge for edge in location_edges if edge.status == "invalidated")
    active_edge = next(edge for edge in location_edges if edge.status == "active")
    assert invalidated_edge.invalidated_by_edge_id == active_edge.edge_id
    assert invalidated_edge.invalid_at_chapter == 2
    assert invalidated_edge.invalid_at_paragraph == 1
    assert active_edge.valid_at_chapter == 2

    early_hits = search_temporal_graph(graph, "Lin location", max_chapter=1, max_paragraph=2, top_k=10)
    relation_hits = [hit for hit in early_hits if hit.hit_type == "relation"]
    assert relation_hits
    assert all(hit.payload["valid_at_chapter"] <= 1 for hit in relation_hits)

    chapter_two_hits = search_temporal_graph(graph, "Lin harbor", max_chapter=2, max_paragraph=1, top_k=10)
    harbor_relations = [
        hit for hit in chapter_two_hits if hit.hit_type == "relation" and hit.payload.get("status") == "active"
    ]
    assert any("harbor" in hit.payload.get("fact", "").lower() for hit in harbor_relations)


def test_temporal_graph_uses_llm_assisted_entity_and_fact_resolution(monkeypatch):
    import backend.knowledge_base.graph.llm_extraction as graph_llm_extraction

    calls = {"count": 0}

    def fake_runtime():
        return graph_llm_extraction.GraphExtractorRuntime(
            api_key="test",
            base_url="http://example.invalid",
            model_name="graph-model",
            provider_label="test-llm",
        )

    def fake_extract_episode_graph_with_llm(*, runtime, chunk, known_entities, recent_episode_contexts, timeout_seconds=90):
        calls["count"] += 1
        if chunk.paragraph_index == 1:
            return EpisodeGraphExtraction(
                entities=[
                    ExtractedEntityCandidate(
                        canonical_name="José Arcadio",
                        entity_type="character",
                        aliases=["Arcadio"],
                        evidence="José Arcadio stands in Macondo.",
                        confidence=0.98,
                    ),
                    ExtractedEntityCandidate(
                        canonical_name="Macondo",
                        entity_type="location",
                        evidence="José Arcadio stands in Macondo.",
                        confidence=0.93,
                    ),
                ],
                facts=[
                    ExtractedFactCandidate(
                        source="José Arcadio",
                        target="Macondo",
                        relation_type="LOCATED_IN",
                        state_family="location",
                        directionality="directed",
                        fact="José Arcadio is in Macondo.",
                        evidence="José Arcadio stands in Macondo.",
                        confidence=0.96,
                    )
                ],
                provider_label="test-llm",
            )
        assert any(item.canonical_name == "José Arcadio" for item in known_entities)
        return EpisodeGraphExtraction(
            entities=[
                ExtractedEntityCandidate(
                    canonical_name="José Arcadio",
                    entity_type="character",
                    aliases=["Arcadio"],
                    resolution_hint="José Arcadio",
                    evidence="Arcadio speaks with Ursula in the square.",
                    confidence=0.97,
                ),
                ExtractedEntityCandidate(
                    canonical_name="Ursula",
                    entity_type="character",
                    evidence="Arcadio speaks with Ursula in the square.",
                    confidence=0.95,
                ),
                ExtractedEntityCandidate(
                    canonical_name="square",
                    entity_type="location",
                    evidence="Arcadio speaks with Ursula in the square.",
                    confidence=0.88,
                ),
            ],
            facts=[
                ExtractedFactCandidate(
                    source="José Arcadio",
                    target="Ursula",
                    relation_type="SPOKE_WITH",
                    state_family="interaction",
                    directionality="undirected",
                    fact="José Arcadio speaks with Ursula.",
                    evidence="Arcadio speaks with Ursula in the square.",
                    confidence=0.94,
                )
            ],
            provider_label="test-llm",
        )

    monkeypatch.setattr(graph_llm_extraction, "resolve_graph_extractor_runtime", fake_runtime)
    monkeypatch.setattr(graph_llm_extraction, "extract_episode_graph_with_llm", fake_extract_episode_graph_with_llm)

    graph = build_temporal_graph(llm_resolution_record())

    assert calls["count"] == 2
    assert graph.metadata["entity_extraction"] == "llm-assisted-resolution"
    assert graph.metadata["fact_extraction"] == "llm-assisted-resolution"
    jose = next(entity for entity in graph.entities.values() if entity.canonical_name == "José Arcadio")
    assert jose.mention_count == 2
    assert "Arcadio" in jose.aliases
    spoke_edges = [edge for edge in graph.relations.values() if edge.relation_type == "SPOKE_WITH"]
    assert spoke_edges
    assert spoke_edges[0].metadata["extraction_mode"] == "llm-assisted"


def test_temporal_graph_falls_back_to_heuristics_when_llm_extraction_errors(monkeypatch):
    import backend.knowledge_base.graph.llm_extraction as graph_llm_extraction

    monkeypatch.setattr(
        graph_llm_extraction,
        "resolve_graph_extractor_runtime",
        lambda: graph_llm_extraction.GraphExtractorRuntime(
            api_key="test",
            base_url="http://example.invalid",
            model_name="graph-model",
            provider_label="test-llm",
        ),
    )

    def raise_extract(**kwargs):
        raise RuntimeError("upstream extractor unavailable")

    monkeypatch.setattr(graph_llm_extraction, "extract_episode_graph_with_llm", raise_extract)

    graph = build_temporal_graph(synthetic_temporal_record())

    assert graph.metadata["entity_extraction"] == "llm-assisted-resolution"
    assert graph.metadata["llm_extraction_warnings"]
    assert any(edge.metadata.get("extraction_mode") == "heuristic" for edge in graph.relations.values())


def test_llm_extraction_retries_without_response_format_when_provider_does_not_support_it(monkeypatch):
    import backend.knowledge_base.graph.llm_extraction as graph_llm_extraction

    calls: list[dict[str, object]] = []

    def fake_invoke_openai_compatible_messages(
        *,
        api_key,
        base_url,
        model_name,
        messages,
        temperature=0.4,
        max_tokens=700,
        timeout_seconds=90,
        response_format=None,
    ):
        calls.append({"response_format": response_format, "messages": messages})
        if response_format is not None:
            raise RuntimeError(
                'HTTP 400: {"error":{"message":"This response_format type is unavailable now"}}'
            )
        return (
            '{"entities":[{"canonical_name":"王二","entity_type":"character","aliases":[],"resolution_hint":"王二",'
            '"evidence":"王二看见了猪。","confidence":0.95}],"facts":[{"source":"王二","target":"猪",'
            '"relation_type":"OBSERVES","state_family":"interaction","directionality":"directed",'
            '"fact":"王二看见了猪。","evidence":"王二看见了猪。","confidence":0.91}]}'
        )

    monkeypatch.setattr(
        graph_llm_extraction,
        "invoke_openai_compatible_messages",
        fake_invoke_openai_compatible_messages,
    )

    runtime = graph_llm_extraction.GraphExtractorRuntime(
        api_key="test",
        base_url="http://example.invalid",
        model_name="graph-model",
        provider_label="test-llm",
    )
    chunk = BookChunk(
        chunk_id="llm-c001-p001",
        book_id="llm-json-retry-book",
        chapter_id="chapter-001",
        chapter_index=1,
        paragraph_id="paragraph-001",
        paragraph_index=1,
        text="王二看见了猪。",
        chunk_level="l0_raw_paragraph",
        candidate_characters=["王二"],
    )

    extraction = graph_llm_extraction.extract_episode_graph_with_llm(
        runtime=runtime,
        chunk=chunk,
        known_entities=[],
        recent_episode_contexts=[],
        timeout_seconds=30,
    )

    assert len(calls) == 2
    assert calls[0]["response_format"] == graph_llm_extraction.GRAPH_EXTRACTION_JSON_SCHEMA
    assert calls[1]["response_format"] is None
    assert extraction.entities[0].canonical_name == "王二"
    assert extraction.facts[0].relation_type == "OBSERVES"


def test_llm_extraction_retries_transient_timeout_before_succeeding(monkeypatch):
    import backend.knowledge_base.graph.llm_extraction as graph_llm_extraction

    calls = {"count": 0}

    def fake_invoke_openai_compatible_messages(
        *,
        api_key,
        base_url,
        model_name,
        messages,
        temperature=0.4,
        max_tokens=700,
        timeout_seconds=90,
        response_format=None,
    ):
        calls["count"] += 1
        if calls["count"] < 3:
            raise RuntimeError("network timeout: The read operation timed out")
        return (
            '{"entities":[{"canonical_name":"王二","entity_type":"character","aliases":[],"resolution_hint":"王二",'
            '"evidence":"王二看见了猪。","confidence":0.95}],"facts":[{"source":"王二","target":"猪",'
            '"relation_type":"OBSERVES","state_family":"interaction","directionality":"directed",'
            '"fact":"王二看见了猪。","evidence":"王二看见了猪。","confidence":0.91}]}'
        )

    monkeypatch.setattr(
        graph_llm_extraction,
        "invoke_openai_compatible_messages",
        fake_invoke_openai_compatible_messages,
    )

    runtime = graph_llm_extraction.GraphExtractorRuntime(
        api_key="test",
        base_url="http://example.invalid",
        model_name="graph-model",
        provider_label="test-llm",
    )
    chunk = BookChunk(
        chunk_id="llm-c001-p001",
        book_id="llm-timeout-retry-book",
        chapter_id="chapter-001",
        chapter_index=1,
        paragraph_id="paragraph-001",
        paragraph_index=1,
        text="王二看见了猪。",
        chunk_level="l0_raw_paragraph",
        candidate_characters=["王二"],
    )

    extraction = graph_llm_extraction.extract_episode_graph_with_llm(
        runtime=runtime,
        chunk=chunk,
        known_entities=[],
        recent_episode_contexts=[],
        timeout_seconds=30,
    )

    assert calls["count"] == 3
    assert extraction.entities[0].canonical_name == "王二"


def test_llm_extraction_retries_full_extraction_when_non_json_persists_once(monkeypatch):
    import backend.knowledge_base.graph.llm_extraction as graph_llm_extraction

    calls = {"count": 0}

    def fake_invoke_openai_compatible_messages(
        *,
        api_key,
        base_url,
        model_name,
        messages,
        temperature=0.4,
        max_tokens=700,
        timeout_seconds=90,
        response_format=None,
    ):
        calls["count"] += 1
        if calls["count"] == 1:
            return "not json at all"
        if calls["count"] == 2:
            return "still not json"
        return (
            '{"entities":[{"canonical_name":"王二","entity_type":"character","aliases":[],"resolution_hint":"王二",'
            '"evidence":"王二看见了猪。","confidence":0.95}],"facts":[{"source":"王二","target":"猪",'
            '"relation_type":"OBSERVES","state_family":"interaction","directionality":"directed",'
            '"fact":"王二看见了猪。","evidence":"王二看见了猪。","confidence":0.91}]}'
        )

    monkeypatch.setattr(
        graph_llm_extraction,
        "invoke_openai_compatible_messages",
        fake_invoke_openai_compatible_messages,
    )

    runtime = graph_llm_extraction.GraphExtractorRuntime(
        api_key="test",
        base_url="http://example.invalid",
        model_name="graph-model",
        provider_label="test-llm",
    )
    chunk = BookChunk(
        chunk_id="llm-c001-p001",
        book_id="llm-non-json-retry-book",
        chapter_id="chapter-001",
        chapter_index=1,
        paragraph_id="paragraph-001",
        paragraph_index=1,
        text="王二看见了猪。",
        chunk_level="l0_raw_paragraph",
        candidate_characters=["王二"],
    )

    extraction = graph_llm_extraction.extract_episode_graph_with_llm(
        runtime=runtime,
        chunk=chunk,
        known_entities=[],
        recent_episode_contexts=[],
        timeout_seconds=30,
    )

    assert calls["count"] == 3
    assert extraction.entities[0].canonical_name == "王二"


def test_temporal_graph_storage_persists_metadata(tmp_path, monkeypatch):
    import backend.knowledge_base.graph.storage as graph_storage

    graph = demo_graph()
    monkeypatch.setattr(graph_storage, "GRAPHS_DIR", tmp_path)

    save_graph(graph)
    loaded = load_graph(graph.book_id)

    assert loaded.graph_id == graph.graph_id
    assert loaded.metadata["storage"]["storage_version"] == graph_storage.STORAGE_VERSION
    assert loaded.metadata["storage"]["loaded"] is True
    assert loaded.metadata["graph_stats"]["chapter_count"] >= 2
