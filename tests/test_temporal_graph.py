from pathlib import Path

from services.graph.builder import build_temporal_graph
from services.graph.retrieval import search_temporal_graph
from services.ingest.parser import build_book_record


def demo_graph():
    source = Path("examples/muse_demo_book.txt")
    record = build_book_record("muse_demo_book", source.read_text(encoding="utf-8"), source)
    return build_temporal_graph(record)


def test_temporal_graph_builds_sagas_and_relations():
    graph = demo_graph()
    assert len(graph.episodes) >= 6
    assert len(graph.sagas) >= 1
    assert any(entity.canonical_name == "Aya" for entity in graph.entities.values())
    assert any(episode.entities for episode in graph.episodes.values())
    assert any(saga.episode_ids for saga in graph.sagas.values())


def test_temporal_graph_search_respects_progress_boundary():
    graph = demo_graph()
    hits = search_temporal_graph(graph, "Aya relationship question", max_chapter=1, top_k=10)
    assert hits
    assert all(hit.chapter_index <= 1 for hit in hits)
