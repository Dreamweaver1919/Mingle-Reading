from __future__ import annotations

from pathlib import Path

from eval.run_eval import run_evaluation
from backend.models import QuestionRequest
from services.ingest.parser import build_book_record
from services.qa.answering import build_answer
from services.summary.chapter_summary import summarize_chapter


def demo_record():
    source = Path(__file__).resolve().parents[1] / "examples" / "muse_demo_book.txt"
    return build_book_record("muse_demo_book", source.read_text(encoding="utf-8"), source)


def test_ingestion_builds_multiple_chapters():
    record = demo_record()
    assert record.chapter_count == 3
    assert len(record.chunks) >= 6


def test_spoiler_question_is_blocked():
    record = demo_record()
    response = build_answer(
        QuestionRequest(
            book_id=record.book_id,
            question="What is Aya's ending?",
            highlight_text=record.chunks[0].text,
            current_chapter=1,
        ),
        record.chunks,
    )
    assert response.safe is False
    assert response.reason == "question_requests_future_plot"


def test_summary_returns_current_chapter_only():
    record = demo_record()
    summary = summarize_chapter(record, 1, "neutral")
    assert summary.chapter_id == "chapter-001"
    assert "Chapter 1 stays within the reader's visible scope" in summary.summary
    assert "Lin opened the old notebook" in summary.summary
    assert "Aya returned the next afternoon" not in summary.summary


def test_eval_runner_reports_demo_sections():
    result = run_evaluation()
    assert result["book_id"] == "muse-demo-book"
    assert result["overall"]["failed"] == 0
    assert result["highlight_qa"]["sample_count"] >= 1
    assert result["anti_spoiler"]["sample_count"] >= 1
    assert result["chapter_summary"]["sample_count"] >= 1
