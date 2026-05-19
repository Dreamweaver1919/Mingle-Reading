from __future__ import annotations

from backend.api.schemas import QuestionRequest, QuestionResponse, RetrievedContext
from backend.knowledge_graph.storage import load_graph
from backend.knowledge_graph.orchestration.models import ReadingProgress, SelectionAnchor, SelectionContext
from backend.knowledge_graph.orchestration.service import OrchestrationService
from backend.agents.celebrity.persona_service import generate_persona_response
from backend.agents.celebrity.retrieval import retrieve_chunks
from backend.safety.anti_spoiler import is_spoiler_question


def _merge_contexts(local_hits: list[RetrievedContext], graph_hits) -> list[RetrievedContext]:
    merged: dict[str, RetrievedContext] = {hit.chunk_id: hit for hit in local_hits}
    for hit in graph_hits:
        paragraph_index = hit.paragraph_id if hit.paragraph_id is not None else 0
        merged.setdefault(
            hit.chunk_id,
            RetrievedContext(
                chunk_id=hit.chunk_id,
                chapter_index=hit.chapter_id,
                paragraph_index=paragraph_index,
                score=1.0,
                text=hit.text,
            ),
        )
    ranked = sorted(merged.values(), key=lambda item: (item.score, -item.chapter_index, -item.paragraph_index), reverse=True)
    return ranked


def _build_graph_knowledge_block(graph, query: str, max_chapter: int, top_k: int = 15) -> str:
    """Extract structured entity and relation knowledge from the graph."""
    if graph is None:
        return ""

    query_lower = query.lower()
    parts: list[str] = []

    # Find matching entities
    matched_entities: list[tuple[int, str, str, str]] = []  # (mentions, name, type, span)
    for entity in graph.entities.values():
        if entity.first_seen_chapter > max_chapter:
            continue
        name = entity.canonical_name
        aliases = entity.aliases or []
        all_forms = [name.lower()] + [a.lower() for a in aliases]
        if any(q in form or form in q for q in query_lower.split() for form in all_forms if len(q) >= 2):
            span = f"ch{entity.first_seen_chapter}-{entity.last_seen_chapter}"
            matched_entities.append((entity.mention_count, name, entity.entity_type, span))

    matched_entities.sort(key=lambda x: x[0], reverse=True)
    matched_entity_names = {name for _, name, _, _ in matched_entities[:top_k]}

    if matched_entities[:10]:
        parts.append("知识图谱中的相关实体：")
        for _, name, etype, span in matched_entities[:10]:
            parts.append(f"  - {name}（{etype}，出场{span}）")

    # Find relations between matched entities
    relation_parts: list[str] = []
    for edge in graph.relations.values():
        if edge.status != "active":
            continue
        if edge.valid_at_chapter > max_chapter:
            continue
        source = graph.entities.get(edge.source_entity_id)
        target = graph.entities.get(edge.target_entity_id)
        if source is None or target is None:
            continue
        if source.canonical_name in matched_entity_names or target.canonical_name in matched_entity_names:
            relation_parts.append(
                f"  - {source.canonical_name} --[{edge.relation_type}]--> {target.canonical_name}：{edge.fact}（ch{edge.valid_at_chapter}）"
            )
    if relation_parts[:15]:
        parts.append("知识图谱中的相关关系：")
        parts.extend(relation_parts[:15])

    if parts:
        parts.insert(0, "【知识图谱结构化数据】")
    return "\n".join(parts)


def build_answer(request: QuestionRequest, chunks) -> QuestionResponse:
    safety = is_spoiler_question(request.question)
    try:
        graph = load_graph(request.book_id)
    except FileNotFoundError:
        graph = None

    orchestration = OrchestrationService().orchestrate(
        chunks=chunks,
        request_id=f"qa-{request.book_id}-{request.current_chapter}",
        book_id=request.book_id,
        query=request.question,
        reading_progress=ReadingProgress(
            book_id=request.book_id,
            chapter_id=request.current_chapter,
            paragraph_id=9999,
            token_offset=10**9,
        ),
        selection_context=SelectionContext(
            book_id=request.book_id,
            selected_text=request.highlight_text,
            anchor=SelectionAnchor(chapter_id=request.current_chapter, paragraph_id=0),
        ),
        top_k=request.top_k,
        temporal_graph=graph,
    )
    local_contexts = retrieve_chunks(
        chunks=chunks,
        query=f"{request.highlight_text} {request.question}".strip(),
        max_chapter=request.current_chapter,
        top_k=request.top_k,
    )
    contexts = _merge_contexts(local_contexts, orchestration.hits)[: request.top_k]
    visible_context_texts = [context.text for context in contexts]

    graph_knowledge = _build_graph_knowledge_block(graph, request.question, request.current_chapter)
    if graph_knowledge:
        visible_context_texts.insert(0, graph_knowledge)

    if not safety.safe:
        refusal, model_name, _ = generate_persona_response(
            persona_id=request.persona_id,
            task="qa",
            book_title=request.book_id,
            question=(
                "用户的问题超出了已读范围，请拒绝剧透，并把话题收回当前已读内容。"
                f"\n原问题：{request.question}"
            ),
            visible_contexts=visible_context_texts,
            current_chapter=request.current_chapter,
            highlight_text=request.highlight_text,
            top_k=request.top_k,
            conversation_history=request.conversation_history,
        )
        return QuestionResponse(
            answer=refusal,
            persona_id=request.persona_id,
            safe=False,
            reason=safety.reason,
            contexts=contexts,
            model_name=model_name,
        )

    if not visible_context_texts:
        answer, model_name, _ = generate_persona_response(
            persona_id=request.persona_id,
            task="qa",
            book_title=request.book_id,
            question=(
                "当前没有检索到足够正文证据。请用中文明确说明证据不足，"
                "并引导用户改问更贴近当前段落的问题。"
            ),
            visible_contexts=[],
            current_chapter=request.current_chapter,
            highlight_text=request.highlight_text,
            top_k=request.top_k,
            conversation_history=request.conversation_history,
        )
        return QuestionResponse(
            answer=answer,
            persona_id=request.persona_id,
            safe=True,
            reason="no_visible_context",
            contexts=[],
            model_name=model_name,
        )

    answer, model_name, _ = generate_persona_response(
        persona_id=request.persona_id,
        task="qa",
        book_title=request.book_id,
        question=request.question,
        visible_contexts=visible_context_texts,
        current_chapter=request.current_chapter,
        highlight_text=request.highlight_text,
        top_k=request.top_k,
        conversation_history=request.conversation_history,
    )
    return QuestionResponse(
        answer=answer,
        persona_id=request.persona_id,
        safe=True,
        reason=safety.reason,
        contexts=contexts,
        model_name=model_name,
    )
