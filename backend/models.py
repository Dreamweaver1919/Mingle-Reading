from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class BookChunk(BaseModel):
    chunk_id: str
    book_id: str
    chapter_id: str
    section_id: str | None = None
    paragraph_start_id: str | None = None
    paragraph_end_id: str | None = None
    chunk_level: Literal["l0_raw_paragraph", "l1_fine_grained"] = "l0_raw_paragraph"
    chapter_index: int
    paragraph_id: str
    paragraph_index: int
    text: str
    token_offset: int = 0
    spoiler_level: int = 0
    position: dict[str, int] = Field(default_factory=dict)
    spoiler_guard: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    candidate_characters: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BookRecord(BaseModel):
    book_id: str
    title: str
    source_path: str
    chapter_count: int
    chunks: list[BookChunk]


class UploadResponse(BaseModel):
    book_id: str
    title: str
    chapter_count: int
    chunk_count: int


class QuestionRequest(BaseModel):
    book_id: str
    question: str
    highlight_text: str = ""
    current_chapter: int = 1
    persona_id: str = "neutral"
    top_k: int = 4


class RetrievedContext(BaseModel):
    chunk_id: str
    chapter_index: int
    paragraph_index: int
    score: float
    text: str


class QuestionResponse(BaseModel):
    answer: str
    persona_id: str
    safe: bool
    reason: str
    contexts: list[RetrievedContext]


class SummaryRequest(BaseModel):
    book_id: str
    current_chapter: int
    persona_id: str = "neutral"


class SummaryResponse(BaseModel):
    summary: str
    chapter_id: str
    persona_id: str


class PersonaProfile(BaseModel):
    persona_id: str
    name: str
    source_type: Literal["literary_master", "book_character", "neutral"]
    style_traits: list[str]
    reasoning_style: list[str]
    citation: str
    prompt_scaffold: list[str] = Field(default_factory=list)


class ReadingProgress(BaseModel):
    book_id: str
    chapter_id: int
    section_id: int = 0
    paragraph_id: int = 0
    token_offset: int = 0
    scroll_offset: float = 0.0
    dwell_seconds: int = 0
    updated_at: str = ""


class SelectionAnchor(BaseModel):
    chapter_id: int
    section_id: int = 0
    paragraph_id: int = 0


class SelectionContext(BaseModel):
    book_id: str
    selection_id: str = ""
    selected_text: str
    left_context: str = ""
    right_context: str = ""
    anchor: SelectionAnchor


class RetrievalRequest(BaseModel):
    request_id: str = ""
    scope: Literal["book_text", "graph", "mixed"] = "mixed"
    kb_id: str
    query: str
    selection_context: SelectionContext
    reading_progress: ReadingProgress
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 6


class Citation(BaseModel):
    chunk_id: str
    chapter_id: int
    section_id: int = 0


class OrchestrationResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    contexts: list[RetrievedContext] = Field(default_factory=list)
    guardrail_trace: dict[str, Any] = Field(default_factory=dict)
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)
