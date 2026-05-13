from __future__ import annotations

from backend.models import SummaryResponse
from services.persona.persona_service import stylize


def summarize_chapter(book, current_chapter: int, persona_id: str) -> SummaryResponse:
    chapter_chunks = [chunk for chunk in book.chunks if chunk.chapter_index == current_chapter]
    snippets = [chunk.text.strip() for chunk in chapter_chunks[:3] if chunk.text.strip()]
    if not snippets:
        summary = "No readable content is available for the current chapter yet."
    else:
        joined = " ".join(snippets)
        summary = (
            f"Chapter {current_chapter} stays within the reader's visible scope: {joined[:260]}. "
            "The summary should focus on relationship movement, emotional pressure, and what the"
            " current passage already makes legible without projecting future plot."
        )
    return SummaryResponse(
        summary=stylize(summary, persona_id),
        chapter_id=f"chapter-{current_chapter:03d}",
        persona_id=persona_id,
    )
