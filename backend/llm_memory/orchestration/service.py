from __future__ import annotations

from typing import Any

from backend.common.models import BookChunk
from backend.knowledge_base.graph.models import TemporalContextGraph
from backend.knowledge_base.graph.retrieval import search_temporal_graph

from .models import (
    Citation,
    GuardrailTrace,
    OrchestrationResult,
    ReadingProgress,
    RetrievalFilters,
    RetrievalHit,
    RetrievalRequest,
    SelectionContext,
)
from .utils import keyword_score, unique_preserve_order


class OrchestrationService:
    def orchestrate(
        self,
        *,
        chunks: list[BookChunk],
        request_id: str,
        book_id: str,
        query: str,
        reading_progress: ReadingProgress | dict[str, Any],
        selection_context: SelectionContext | dict[str, Any] | None = None,
        top_k: int = 6,
        temporal_graph: TemporalContextGraph | None = None,
    ) -> OrchestrationResult:
        progress = self._coerce_progress(reading_progress, book_id)
        selection = self._coerce_selection(selection_context, book_id)
        filters = self._build_filters(progress, selection, chunks)
        retrieval_request = RetrievalRequest(
            request_id=request_id,
            scope="mixed",
            kb_id=f"{book_id}-mixed",
            query=self._compose_query(query, selection),
            selection_context=selection,
            reading_progress=progress,
            filters=filters,
            top_k=top_k,
        )
        visible_chunks, trace = self._filter_visible_chunks(chunks, progress, selection, filters)
        text_hits = self._retrieve_text_hits(visible_chunks, retrieval_request)
        graph_hits = self._retrieve_graph_hits(visible_chunks, retrieval_request, temporal_graph)
        merged_hits = self._merge_hits(text_hits, graph_hits, top_k)
        trace.retrieval_counts = {
            "book_text": len(text_hits),
            "graph": len(graph_hits),
            "merged": len(merged_hits),
        }
        citations = [
            Citation(
                chunk_id=hit.chunk_id,
                source_type=hit.source_type,
                chapter_id=hit.chapter_id,
                section_id=hit.section_id,
                paragraph_id=hit.paragraph_id,
                score=hit.score,
            )
            for hit in merged_hits
        ]
        return OrchestrationResult(
            request_id=request_id,
            retrieval_request=retrieval_request,
            hits=merged_hits,
            citations=citations,
            guardrail_trace=trace,
        )

    def _coerce_progress(
        self,
        reading_progress: ReadingProgress | dict[str, Any],
        book_id: str,
    ) -> ReadingProgress:
        progress = (
            reading_progress
            if isinstance(reading_progress, ReadingProgress)
            else ReadingProgress.model_validate(reading_progress)
        )
        if progress.book_id != book_id:
            progress = progress.model_copy(update={"book_id": book_id})
        return progress

    def _coerce_selection(
        self,
        selection_context: SelectionContext | dict[str, Any] | None,
        book_id: str,
    ) -> SelectionContext | None:
        if selection_context is None:
            return None
        selection = (
            selection_context
            if isinstance(selection_context, SelectionContext)
            else SelectionContext.model_validate(selection_context)
        )
        if selection.book_id != book_id:
            selection = selection.model_copy(update={"book_id": book_id})
        return selection

    def _compose_query(self, query: str, selection: SelectionContext | None) -> str:
        parts = [query.strip()]
        if selection and selection.selected_text.strip():
            parts.append(selection.selected_text.strip())
        return " ".join(part for part in parts if part)

    def _build_filters(
        self,
        progress: ReadingProgress,
        selection: SelectionContext | None,
        chunks: list[BookChunk],
    ) -> RetrievalFilters:
        character_ids = unique_preserve_order(self._collect_character_filters(selection, chunks, progress))
        theme_tags = unique_preserve_order(self._collect_theme_filters(selection, chunks, progress))
        return RetrievalFilters(
            max_chapter_id=progress.chapter_id,
            max_paragraph_id=progress.paragraph_id,
            max_token_offset=progress.token_offset,
            character_ids=character_ids,
            theme_tags=theme_tags,
        )

    def _collect_character_filters(
        self,
        selection: SelectionContext | None,
        chunks: list[BookChunk],
        progress: ReadingProgress,
    ) -> list[str]:
        if not selection:
            return []
        selected = selection.selected_text.lower()
        visible = [chunk for chunk in chunks if self._is_chunk_visible(chunk, progress)]
        candidates: list[str] = []
        for chunk in visible:
            chunk_characters = self._chunk_characters(chunk)
            if selection.anchor and self._chunk_paragraph_id(chunk) == selection.anchor.paragraph_id:
                candidates.extend(chunk_characters)
                continue
            for character in chunk_characters:
                if character.replace("_", " ") in selected:
                    candidates.append(character)
        return candidates

    def _collect_theme_filters(
        self,
        selection: SelectionContext | None,
        chunks: list[BookChunk],
        progress: ReadingProgress,
    ) -> list[str]:
        if not selection:
            return []
        visible = [chunk for chunk in chunks if self._is_chunk_visible(chunk, progress)]
        anchor_paragraph = selection.anchor.paragraph_id if selection.anchor else None
        themes: list[str] = []
        for chunk in visible:
            if anchor_paragraph is not None and self._chunk_paragraph_id(chunk) != anchor_paragraph:
                continue
            themes.extend(self._chunk_theme_tags(chunk))
        return themes

    def _filter_visible_chunks(
        self,
        chunks: list[BookChunk],
        progress: ReadingProgress,
        selection: SelectionContext | None,
        filters: RetrievalFilters,
    ) -> tuple[list[BookChunk], GuardrailTrace]:
        visible = [chunk for chunk in chunks if self._is_chunk_visible(chunk, progress)]
        progress_consistent = True
        warnings: list[str] = []
        if selection and selection.anchor and selection.anchor.chapter_id > progress.chapter_id:
            progress_consistent = False
            warnings.append("selection_anchor_after_progress")
        trace = GuardrailTrace(
            max_chapter_id=filters.max_chapter_id,
            max_paragraph_id=filters.max_paragraph_id,
            max_token_offset=filters.max_token_offset,
            visible_chunk_count=len(visible),
            filtered_out_chunk_count=max(0, len(chunks) - len(visible)),
            progress_consistent=progress_consistent,
            selection_anchor_chapter_id=selection.anchor.chapter_id if selection and selection.anchor else None,
            selected_character_filters=filters.character_ids,
            selected_theme_filters=filters.theme_tags,
            retrieval_plan=[
                "apply_progress_filters_before_retrieval",
                "retrieve_book_text_hits",
                "retrieve_graph_hits",
                "merge_and_deduplicate_hits",
            ],
            warnings=warnings,
        )
        return visible, trace

    def _retrieve_text_hits(
        self,
        visible_chunks: list[BookChunk],
        retrieval_request: RetrievalRequest,
    ) -> list[RetrievalHit]:
        scored: list[tuple[float, BookChunk]] = []
        for chunk in visible_chunks:
            score = keyword_score(retrieval_request.query, chunk.text)
            score += self._progress_bonus(chunk, retrieval_request.reading_progress, retrieval_request.selection_context)
            if score <= 0:
                continue
            scored.append((score, chunk))
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)
        return [
            RetrievalHit(
                chunk_id=chunk.chunk_id,
                source_type="book_text",
                score=round(score, 4),
                text=chunk.text,
                chapter_id=chunk.chapter_index,
                section_id=self._safe_int(chunk.section_id),
                paragraph_id=self._chunk_paragraph_id(chunk),
                metadata=self._chunk_metadata(chunk),
            )
            for score, chunk in ranked[: retrieval_request.top_k]
        ]

    def _retrieve_graph_hits(
        self,
        visible_chunks: list[BookChunk],
        retrieval_request: RetrievalRequest,
        temporal_graph: TemporalContextGraph | None = None,
    ) -> list[RetrievalHit]:
        if temporal_graph is not None:
            graph_hits = search_temporal_graph(
                temporal_graph,
                query=retrieval_request.query,
                max_chapter=retrieval_request.reading_progress.chapter_id,
                top_k=retrieval_request.top_k,
            )
            hits: list[RetrievalHit] = []
            for hit in graph_hits:
                payload = dict(hit.payload)
                provenance = hit.provenance[0] if hit.provenance else None
                chunk_id = payload.get("chunk_id") or (provenance.chunk_id if provenance else hit.hit_id)
                paragraph_id = payload.get("paragraph_id") or (provenance.paragraph_index if provenance else None)
                section_id = payload.get("section_id")
                if section_id is None and provenance is not None:
                    section_id = provenance.metadata.get("section_id")
                hits.append(
                    RetrievalHit(
                        chunk_id=chunk_id,
                        source_type="graph",
                        score=round(hit.score, 4),
                        text=payload.get("text") or payload.get("summary") or payload.get("label") or hit.reason,
                        chapter_id=hit.chapter_index or (provenance.chapter_index if provenance else 0),
                        section_id=section_id,
                        paragraph_id=paragraph_id,
                        metadata=payload,
                    )
                )
            return hits

        character_filters = set(retrieval_request.filters.character_ids)
        theme_filters = set(retrieval_request.filters.theme_tags)
        scored: list[tuple[float, BookChunk]] = []
        for chunk in visible_chunks:
            score = 0.0
            chunk_characters = set(self._chunk_characters(chunk))
            chunk_themes = set(self._chunk_theme_tags(chunk))
            if character_filters and chunk_characters:
                score += 1.2 * len(character_filters & chunk_characters)
            if theme_filters and chunk_themes:
                score += 0.8 * len(theme_filters & chunk_themes)
            if not character_filters and not theme_filters:
                score += self._progress_bonus(
                    chunk,
                    retrieval_request.reading_progress,
                    retrieval_request.selection_context,
                )
            else:
                score += self._progress_bonus(
                    chunk,
                    retrieval_request.reading_progress,
                    retrieval_request.selection_context,
                ) * 0.5
            if score <= 0:
                continue
            scored.append((score, chunk))
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)
        hits: list[RetrievalHit] = []
        for score, chunk in ranked[: retrieval_request.top_k]:
            hit_text = self._graph_summary_text(chunk)
            hits.append(
                RetrievalHit(
                    chunk_id=chunk.chunk_id,
                    source_type="graph",
                    score=round(score, 4),
                    text=hit_text,
                    chapter_id=chunk.chapter_index,
                    section_id=self._safe_int(chunk.section_id),
                    paragraph_id=self._chunk_paragraph_id(chunk),
                    metadata=self._chunk_metadata(chunk),
                )
            )
        return hits

    def _merge_hits(
        self,
        text_hits: list[RetrievalHit],
        graph_hits: list[RetrievalHit],
        top_k: int,
    ) -> list[RetrievalHit]:
        merged_by_source_id: dict[tuple[str, str], RetrievalHit] = {}
        for hit in text_hits + graph_hits:
            merged_by_source_id[(hit.chunk_id, hit.source_type)] = hit
        ranked = sorted(
            merged_by_source_id.values(),
            key=lambda hit: (hit.score, hit.chapter_id, hit.paragraph_id or 0),
            reverse=True,
        )
        return ranked[:top_k]

    def _is_chunk_visible(self, chunk: BookChunk, progress: ReadingProgress) -> bool:
        if chunk.chapter_index < progress.chapter_id:
            return True
        if chunk.chapter_index > progress.chapter_id:
            return False
        paragraph_id = self._chunk_paragraph_id(chunk)
        if progress.paragraph_id is not None and paragraph_id is not None and paragraph_id > progress.paragraph_id:
            return False
        if (
            progress.token_offset is not None
            and chunk.token_offset
            and chunk.token_offset > progress.token_offset
            and (progress.paragraph_id is None or paragraph_id == progress.paragraph_id)
        ):
            return False
        return True

    def _progress_bonus(
        self,
        chunk: BookChunk,
        progress: ReadingProgress,
        selection: SelectionContext | None,
    ) -> float:
        bonus = 0.0
        if chunk.chapter_index == progress.chapter_id:
            bonus += 0.3
        paragraph_id = self._chunk_paragraph_id(chunk)
        if selection and selection.anchor and paragraph_id is not None and selection.anchor.paragraph_id is not None:
            distance = abs(paragraph_id - selection.anchor.paragraph_id)
            bonus += max(0.0, 0.6 - 0.15 * distance)
        return bonus

    def _chunk_characters(self, chunk: BookChunk) -> list[str]:
        values = chunk.metadata.get("characters_present") or chunk.candidate_characters
        return unique_preserve_order(values)

    def _chunk_theme_tags(self, chunk: BookChunk) -> list[str]:
        values = chunk.metadata.get("theme_tags") or chunk.tags
        return unique_preserve_order(values)

    def _chunk_metadata(self, chunk: BookChunk) -> dict[str, Any]:
        metadata = dict(chunk.metadata)
        metadata.setdefault("book_id", chunk.book_id)
        metadata.setdefault("chapter_id", chunk.chapter_index)
        metadata.setdefault("section_id", self._safe_int(chunk.section_id))
        metadata.setdefault("paragraph_id", self._chunk_paragraph_id(chunk))
        metadata.setdefault("characters_present", self._chunk_characters_fallback(chunk))
        metadata.setdefault("theme_tags", unique_preserve_order(chunk.tags))
        metadata.setdefault("spoiler_level", chunk.spoiler_guard.get("spoiler_level", "visible"))
        return metadata

    def _chunk_characters_fallback(self, chunk: BookChunk) -> list[str]:
        return unique_preserve_order(chunk.candidate_characters)

    def _graph_summary_text(self, chunk: BookChunk) -> str:
        characters = ", ".join(self._chunk_characters(chunk)) or "unknown_characters"
        themes = ", ".join(self._chunk_theme_tags(chunk)) or "untagged_theme"
        return f"graph view: chapter {chunk.chapter_index}, characters={characters}, themes={themes}"

    def _chunk_paragraph_id(self, chunk: BookChunk) -> int | None:
        return self._safe_int(chunk.paragraph_id)

    def _safe_int(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        digits = "".join(character for character in str(value) if character.isdigit())
        if not digits:
            return None
        return int(digits)
