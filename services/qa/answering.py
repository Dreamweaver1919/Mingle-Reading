from __future__ import annotations

from backend.models import QuestionRequest, QuestionResponse
from services.graph.storage import load_graph
from services.orchestration.models import ReadingProgress, SelectionAnchor, SelectionContext
from services.orchestration.service import OrchestrationService
from services.persona.persona_service import stylize
from services.qa.retrieval import retrieve_chunks
from services.safety.anti_spoiler import is_spoiler_question


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
    contexts = retrieve_chunks(
        chunks=chunks,
        query=f"{request.highlight_text} {request.question}".strip(),
        max_chapter=request.current_chapter,
        top_k=request.top_k,
    )
    merged_support = "\n".join(hit.text for hit in orchestration.hits[:2])
    if not safety.safe:
        answer = (
            "这个问题很可能会越过你当前的阅读进度。我先不直接透露后文，"
            "可以改为解释你已经读到的线索、人物动机或这段文字的张力。"
        )
        return QuestionResponse(
            answer=stylize(answer, request.persona_id),
            persona_id=request.persona_id,
            safe=False,
            reason=safety.reason,
            contexts=contexts,
        )

    if not contexts:
        answer = "我还没有在你当前已读范围里找到足够扎实的支撑段落，建议换个提问方式，或先扩展到相邻段落。"
        return QuestionResponse(
            answer=stylize(answer, request.persona_id),
            persona_id=request.persona_id,
            safe=True,
            reason="no_visible_context",
            contexts=[],
        )

    support = " ".join(context.text for context in contexts[:2])
    answer = (
        f"基于你当前已读内容，我会先结合原文与关系线索来回答。原文支撑：{support[:180]}。"
        f" 图谱支撑：{merged_support[:180]}。"
        " 如果结合高亮文本来看，这里更像是在推进人物关系、主题张力或叙事伏笔，"
        "但我只依据你当前已读范围作答，并且先过滤再检索。"
    )
    return QuestionResponse(
        answer=stylize(answer, request.persona_id),
        persona_id=request.persona_id,
        safe=True,
        reason=safety.reason,
        contexts=contexts,
    )
