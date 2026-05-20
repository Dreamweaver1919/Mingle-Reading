from __future__ import annotations

import json
import re
from typing import Any

from backend.api.schemas import (
    BookChunk,
    ChatMessage,
    CharacterCandidate,
    CharacterChatResponse,
    CharacterProfile,
    CharacterRelationship,
    InlineBubble,
)
from backend.agents.celebrity.model_client import invoke_openai_compatible_messages
from backend.agents.celebrity.persona_service import (
    PersonaAgentInvocationError,
    resolve_persona_runtime,
)
from backend.agents.celebrity.retrieval import retrieve_chunks
from backend.knowledge_graph.orchestration.models import ReadingProgress
from backend.knowledge_graph.orchestration.service import OrchestrationService
from backend.knowledge_graph.storage import graph_exists, load_graph


_CHARACTER_PROFILE_CACHE: dict[tuple[str, str, int], CharacterProfile] = {}
_CHARACTER_CANDIDATE_CACHE: dict[tuple[str, int], list[CharacterCandidate]] = {}
_INLINE_BUBBLE_CACHE: dict[tuple[str, int, tuple[str, ...], str, str], list[InlineBubble]] = {}


def _extract_json_payload(text: str) -> Any:
    fenced = re.search(r"```json\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return json.loads(fenced.group(1).strip())
    start_object = text.find("{")
    start_array = text.find("[")
    starts = [value for value in (start_object, start_array) if value >= 0]
    if not starts:
        raise ValueError("model response did not contain JSON")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    if end <= start:
        raise ValueError("model response did not contain a complete JSON payload")
    return json.loads(text[start : end + 1])


def _character_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-")
    return slug or "candidate"


def _build_model_messages(
    system_prompt: str,
    user_prompt: str,
    history: list[ChatMessage] | None = None,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    for turn in (history or [])[-8:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _invoke_runtime(
    persona_id: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 900,
    temperature: float = 0.4,
) -> tuple[str, str]:
    _, api_key, base_url, model_name = resolve_persona_runtime(persona_id)
    try:
        answer = invoke_openai_compatible_messages(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # pragma: no cover
        raise PersonaAgentInvocationError(f"character service model call failed: {exc}") from exc
    return answer, model_name


def _graph_character_candidates(book, current_chapter: int, limit: int = 10) -> list[CharacterCandidate]:
    if not graph_exists(book.book_id):
        return []
    try:
        graph = load_graph(book.book_id)
    except Exception:
        return []

    candidates: list[CharacterCandidate] = []
    for entity in graph.entities.values():
        if entity.entity_type != "character":
            continue
        if entity.first_seen_chapter > current_chapter:
            continue
        chapter_span = entity.metadata.get("chapter_span", []) if entity.metadata else []
        preview = entity.summary or f"{entity.canonical_name} appears in visible chapters."
        candidates.append(
            CharacterCandidate(
                character_id=f"char-{_character_slug(entity.canonical_name)}",
                character_name=entity.canonical_name,
                mention_count=entity.mention_count,
                chapter_hits=sorted(chapter_span) if chapter_span else [entity.first_seen_chapter],
                preview=preview,
            )
        )
    candidates.sort(key=lambda item: item.mention_count, reverse=True)
    return candidates[:limit]


def list_character_candidates(book, current_chapter: int, limit: int = 10) -> list[CharacterCandidate]:
    cache_key = (book.book_id, current_chapter)
    if cache_key in _CHARACTER_CANDIDATE_CACHE:
        return _CHARACTER_CANDIDATE_CACHE[cache_key][:limit]

    candidates = _graph_character_candidates(book, current_chapter, limit=200)
    deduped: list[CharacterCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.character_name.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)

    _CHARACTER_CANDIDATE_CACHE[cache_key] = deduped
    return deduped[:limit]


def _character_evidence(
    chunks: list[BookChunk],
    character_name: str,
    current_chapter: int,
    top_k: int = 8,
) -> list[BookChunk]:
    visible = [chunk for chunk in chunks if chunk.chapter_index <= current_chapter]
    direct = [chunk for chunk in visible if character_name in chunk.text]
    if direct:
        return direct[:top_k]
    ranked = retrieve_chunks(visible, query=character_name, max_chapter=current_chapter, top_k=top_k)
    ranked_ids = {item.chunk_id for item in ranked}
    return [chunk for chunk in visible if chunk.chunk_id in ranked_ids][:top_k]


def _orchestrate_character_context(
    book,
    character_name: str,
    current_chapter: int,
    query: str,
    *,
    top_k: int = 8,
    window_mode: str = "visible",
) -> dict[str, Any]:
    try:
        graph = load_graph(book.book_id)
    except FileNotFoundError:
        return {}

    result = OrchestrationService().orchestrate(
        chunks=book.chunks,
        request_id=f"character-{book.book_id}-{_character_slug(character_name)}-{current_chapter}",
        book_id=book.book_id,
        query=query,
        reading_progress=ReadingProgress(
            book_id=book.book_id,
            chapter_id=current_chapter,
            paragraph_id=9999,
            token_offset=10**9,
        ),
        selection_context=None,
        top_k=top_k,
        temporal_graph=graph,
        window_mode=window_mode,
    )
    return result.structured_context or {}


def _build_character_graph_block(structured_context: dict[str, Any] | None, character_name: str) -> str:
    if not structured_context:
        return ""

    sections: list[str] = []

    visible_facts = []
    for item in structured_context.get("visible_facts", []):
        source_name = str(item.get("source_name", ""))
        target_name = str(item.get("target_name", ""))
        if character_name not in source_name and character_name not in target_name:
            continue
        visible_facts.append(
            f"- {source_name} --[{item.get('relation_type', '')}]--> {target_name} | {item.get('fact', '')}"
        )
        if len(visible_facts) >= 8:
            break
    if visible_facts:
        sections.append("Visible facts:\n" + "\n".join(visible_facts))

    entity_lines = []
    for item in structured_context.get("entities", []):
        name = str(item.get("name", ""))
        if character_name not in name:
            continue
        entity_lines.append(f"- {name}: {item.get('summary', '')}")
    if entity_lines:
        sections.append("Character entities:\n" + "\n".join(entity_lines[:3]))

    community_lines = []
    for item in structured_context.get("local_communities", []):
        members = ", ".join(item.get("members", []))
        if character_name not in members:
            continue
        community_lines.append(f"- {item.get('label', '')}: {item.get('summary', '')}")
    if community_lines:
        sections.append("Local communities:\n" + "\n".join(community_lines[:3]))

    arc_lines = []
    for item in structured_context.get("long_arcs", []):
        key_entities = ", ".join(item.get("key_entities", []))
        if character_name not in key_entities:
            continue
        arc_lines.append(
            f"- {item.get('label', '')} (chapter {item.get('chapter_start')} to {item.get('chapter_end')}): {item.get('summary', '')}"
        )
    if arc_lines:
        sections.append("Visible arcs:\n" + "\n".join(arc_lines[:3]))

    return "\n\n".join(sections)


def generate_character_profile(book, character_name: str, current_chapter: int) -> CharacterProfile:
    cache_key = (book.book_id, character_name, current_chapter)
    if cache_key in _CHARACTER_PROFILE_CACHE:
        return _CHARACTER_PROFILE_CACHE[cache_key]

    evidence_chunks = _character_evidence(book.chunks, character_name, current_chapter, top_k=10)
    if not evidence_chunks:
        raise PersonaAgentInvocationError(f"character `{character_name}` has no visible evidence in current reading scope")

    structured_context = _orchestrate_character_context(
        book,
        character_name,
        current_chapter,
        query=f"{character_name} 人物画像 关系 处境",
        top_k=10,
        window_mode="visible",
    )
    graph_block = _build_character_graph_block(structured_context, character_name)
    evidence_block = "\n\n".join(
        f"[{chunk.chunk_id} | chapter {chunk.chapter_index}]\n{chunk.text}" for chunk in evidence_chunks
    )

    system_prompt = (
        "你是一个严格受阅读进度约束的人物分析助手。"
        "只根据用户当前可见章节中的证据生成人物画像，不要使用未来剧情。"
        "请输出 JSON，字段必须包含 summary, core_traits, relationships, signature_tension, current_scope。"
        "relationships 必须是对象数组，每项包含 target 和 description。"
    )
    user_prompt = (
        f"书名: {book.title}\n"
        f"当前可见章节: {current_chapter}\n"
        f"人物: {character_name}\n\n"
        f"图谱上下文:\n{graph_block or '无'}\n\n"
        f"正文证据:\n{evidence_block}"
    )
    answer, model_name = _invoke_runtime(
        "neutral",
        _build_model_messages(system_prompt, user_prompt),
        max_tokens=1100,
        temperature=0.25,
    )
    payload = _extract_json_payload(answer)
    relationships = [
        CharacterRelationship(
            target=str(item.get("target", "")).strip(),
            description=str(item.get("description", "")).strip(),
        )
        for item in payload.get("relationships", [])
        if str(item.get("target", "")).strip() and str(item.get("description", "")).strip()
    ]
    profile = CharacterProfile(
        character_id=f"char-{_character_slug(character_name)}",
        character_name=character_name,
        summary=str(payload.get("summary", "")).strip(),
        core_traits=[str(item).strip() for item in payload.get("core_traits", []) if str(item).strip()],
        relationships=relationships,
        signature_tension=str(payload.get("signature_tension", "")).strip(),
        evidence_chunk_ids=[chunk.chunk_id for chunk in evidence_chunks],
        current_scope=str(payload.get("current_scope", "")).strip(),
        model_name=model_name,
    )
    _CHARACTER_PROFILE_CACHE[cache_key] = profile
    return profile


def answer_as_character(
    book,
    character_name: str,
    question: str,
    current_chapter: int,
    conversation_history: list[ChatMessage] | None = None,
    top_k: int = 6,
) -> CharacterChatResponse:
    profile = generate_character_profile(book, character_name, current_chapter)
    evidence_chunks = _character_evidence(book.chunks, character_name, current_chapter, top_k=top_k)
    retrieval_hits = retrieve_chunks(
        [chunk for chunk in book.chunks if chunk.chapter_index <= current_chapter],
        query=f"{character_name} {question}",
        max_chapter=current_chapter,
        top_k=top_k,
    )
    seen = {chunk.chunk_id for chunk in evidence_chunks}
    for hit in retrieval_hits:
        if hit.chunk_id in seen:
            continue
        match = next((chunk for chunk in book.chunks if chunk.chunk_id == hit.chunk_id), None)
        if match is not None:
            evidence_chunks.append(match)
            seen.add(hit.chunk_id)

    structured_context = _orchestrate_character_context(
        book,
        character_name,
        current_chapter,
        query=f"{character_name} {question}",
        top_k=top_k,
        window_mode="visible",
    )
    graph_block = _build_character_graph_block(structured_context, character_name)
    evidence_block = "\n\n".join(
        f"[{chunk.chunk_id} | chapter {chunk.chapter_index}]\n{chunk.text}" for chunk in evidence_chunks[:top_k]
    )
    system_prompt = (
        f"你现在扮演 {character_name}。"
        "你只能基于当前可见章节中的事实回答，不能泄露未来剧情，不能引用读者尚未看到的信息。"
        "如果证据不足，可以保留、迟疑、模糊，但不要编造未来事实。"
    )
    user_prompt = (
        f"书名: {book.title}\n"
        f"当前可见章节: {current_chapter}\n"
        f"角色摘要: {profile.summary}\n"
        f"核心特征: {', '.join(profile.core_traits)}\n"
        f"核心张力: {profile.signature_tension}\n"
        f"用户问题: {question}\n\n"
        f"图谱上下文:\n{graph_block or '无'}\n\n"
        f"正文证据:\n{evidence_block}"
    )
    answer, model_name = _invoke_runtime(
        "neutral",
        _build_model_messages(system_prompt, user_prompt, conversation_history),
        max_tokens=900,
        temperature=0.5,
    )
    return CharacterChatResponse(
        answer=answer.strip(),
        character_name=character_name,
        safe=True,
        reason="within_visible_scope",
        model_name=model_name,
        profile=profile,
    )


def generate_inline_bubbles(
    book,
    current_chapter: int,
    visible_chunk_ids: list[str],
    persona_id: str,
    assistant_mode: str,
    character_name: str,
    max_bubbles: int,
) -> list[InlineBubble]:
    cache_key = (book.book_id, current_chapter, tuple(sorted(visible_chunk_ids)), assistant_mode, character_name or persona_id)
    if cache_key in _INLINE_BUBBLE_CACHE:
        return _INLINE_BUBBLE_CACHE[cache_key]

    visible_chunks = [chunk for chunk in book.chunks if chunk.chunk_id in set(visible_chunk_ids)]
    if not visible_chunks:
        return []

    evidence_block = "\n\n".join(f"[{chunk.chunk_id}]\n{chunk.text}" for chunk in visible_chunks[:8])
    if assistant_mode == "character" and character_name:
        runtime_persona = "neutral"
        instruction = f"请以 {character_name} 的视角生成贴在文段旁边的短评气泡。"
    else:
        runtime_persona = persona_id
        instruction = "请生成面向读者的短评气泡。"

    system_prompt = (
        "你是一个为阅读器生成行内批注气泡的助手。"
        "请输出 JSON 数组，每项包含 chunk_id, anchor_text, label, comment, emphasis。"
        "anchor_text 必须直接出现在对应 chunk 的正文中。label 最多 8 个字，comment 最多 40 个字。"
    )
    user_prompt = (
        f"书名: {book.title}\n"
        f"当前可见章节: {current_chapter}\n"
        f"任务说明: {instruction}\n"
        f"最多生成 {max_bubbles} 条。\n\n"
        f"可见正文:\n{evidence_block}"
    )
    answer, _ = _invoke_runtime(
        runtime_persona,
        _build_model_messages(system_prompt, user_prompt),
        max_tokens=700,
        temperature=0.25,
    )
    payload = _extract_json_payload(answer)
    chunk_map = {chunk.chunk_id: chunk for chunk in visible_chunks}
    bubbles: list[InlineBubble] = []
    if isinstance(payload, list):
        for index, item in enumerate(payload[:max_bubbles], start=1):
            chunk_id = str(item.get("chunk_id", "")).strip()
            anchor_text = str(item.get("anchor_text", "")).strip()
            label = str(item.get("label", "")).strip()[:8]
            comment = str(item.get("comment", "")).strip()[:40]
            emphasis = str(item.get("emphasis", "detail")).strip()
            chunk = chunk_map.get(chunk_id)
            if not chunk or not anchor_text or anchor_text not in chunk.text or not comment:
                continue
            bubbles.append(
                InlineBubble(
                    bubble_id=f"bubble-{chunk_id}-{index}",
                    chunk_id=chunk_id,
                    anchor_text=anchor_text,
                    label=label or "细读",
                    comment=comment,
                    emphasis=emphasis if emphasis in {"theme", "emotion", "relation", "foreshadow", "detail"} else "detail",
                )
            )
    _INLINE_BUBBLE_CACHE[cache_key] = bubbles
    return bubbles
