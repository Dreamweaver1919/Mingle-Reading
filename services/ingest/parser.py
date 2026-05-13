from __future__ import annotations

import re
from pathlib import Path

from backend.models import BookChunk, BookRecord


CHAPTER_PATTERNS = [
    re.compile(r"^\s*Chapter\s+\d+.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*CHAPTER\s+\d+.*$", re.MULTILINE),
    re.compile(r"^\s*第[一二三四五六七八九十百千0-9]+章.*$", re.MULTILINE),
]


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", lowered)
    return lowered.strip("-") or "book"


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_chapters(text: str) -> list[tuple[str, str]]:
    normalized = normalize_text(text)
    for pattern in CHAPTER_PATTERNS:
        matches = list(pattern.finditer(normalized))
        if len(matches) >= 2:
            chapters: list[tuple[str, str]] = []
            for index, match in enumerate(matches):
                start = match.start()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized)
                title = match.group(0).strip()
                body = normalized[start:end].strip()
                chapters.append((title, body))
            return chapters
    return [("Chapter 1", normalized)]


def score_spoiler_level(chapter_index: int) -> int:
    if chapter_index <= 1:
        return 0
    if chapter_index <= 3:
        return 1
    return 2


def spoiler_label(spoiler_level: int) -> str:
    if spoiler_level <= 0:
        return "safe"
    if spoiler_level == 1:
        return "mild"
    return "high"


def extract_candidate_characters(paragraph: str) -> list[str]:
    matches = re.findall(r"\b[A-Z][a-z]{2,}\b", paragraph)
    blocked = {"Chapter", "When", "The", "By", "At"}
    deduped: list[str] = []
    for match in matches:
        if match in blocked:
            continue
        if match not in deduped:
            deduped.append(match)
    return deduped[:5]


def build_book_record(title: str, raw_text: str, source_path: Path) -> BookRecord:
    chapters = split_chapters(raw_text)
    book_id = slugify(title)
    chunks: list[BookChunk] = []
    token_offset = 0
    for chapter_index, (chapter_title, chapter_text) in enumerate(chapters, start=1):
        paragraphs = [p.strip() for p in chapter_text.split("\n\n") if p.strip()]
        for paragraph_index, paragraph in enumerate(paragraphs, start=1):
            chunk_id = f"{book_id}-c{chapter_index:03d}-p{paragraph_index:03d}"
            level = score_spoiler_level(chapter_index)
            chunks.append(
                BookChunk(
                    chunk_id=chunk_id,
                    book_id=book_id,
                    chapter_id=f"chapter-{chapter_index:03d}",
                    section_id=f"section-{chapter_index:03d}",
                    paragraph_start_id=f"paragraph-{paragraph_index:03d}",
                    paragraph_end_id=f"paragraph-{paragraph_index:03d}",
                    chunk_level="l0_raw_paragraph",
                    chapter_index=chapter_index,
                    paragraph_id=f"paragraph-{paragraph_index:03d}",
                    paragraph_index=paragraph_index,
                    text=paragraph,
                    token_offset=token_offset,
                    spoiler_level=level,
                    position={
                        "chapter_index": chapter_index,
                        "section_index": chapter_index,
                        "char_start": token_offset,
                        "char_end": token_offset + len(paragraph),
                    },
                    spoiler_guard={
                        "spoiler_level": spoiler_label(level),
                        "max_visible_chapter_index": chapter_index,
                    },
                    tags=["book_text", "demo_chunk"],
                    candidate_characters=extract_candidate_characters(paragraph),
                    metadata={"chapter_title": chapter_title},
                )
            )
            token_offset += max(1, len(paragraph.split()))
    return BookRecord(
        book_id=book_id,
        title=title,
        source_path=str(source_path),
        chapter_count=len(chapters),
        chunks=chunks,
    )
