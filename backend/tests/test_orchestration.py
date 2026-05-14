from pathlib import Path

from backend.common.config import EXAMPLES_DIR
from backend.knowledge_base.graph.builder import build_temporal_graph
from backend.data.ingest.parser import build_book_record
from backend.llm_memory.orchestration.models import ReadingProgress, SelectionAnchor, SelectionContext
from backend.llm_memory.orchestration.service import OrchestrationService


def demo_assets():
    source = EXAMPLES_DIR / "muse_demo_book.txt"
    record = build_book_record("muse_demo_book", source.read_text(encoding="utf-8"), source)
    graph = build_temporal_graph(record)
    return record, graph


def test_orchestration_returns_mixed_hits_and_trace():
    record, graph = demo_assets()
    result = OrchestrationService().orchestrate(
        chunks=record.chunks,
        request_id="test-001",
        book_id=record.book_id,
        query="Aya relationship question",
        reading_progress=ReadingProgress(book_id=record.book_id, chapter_id=1, paragraph_id=4, token_offset=9999),
        selection_context=SelectionContext(
            book_id=record.book_id,
            selected_text=record.chunks[3].text,
            anchor=SelectionAnchor(chapter_id=1, paragraph_id=4),
        ),
        top_k=4,
        temporal_graph=graph,
    )
    assert result.hits
    assert result.guardrail_trace.filter_first is True
    assert result.guardrail_trace.visible_chunk_count > 0
    assert any(citation.source_type in {"book_text", "graph"} for citation in result.citations)
