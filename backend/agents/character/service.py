from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
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
    PersonaAgentConfigurationError,
    PersonaAgentInvocationError,
    resolve_persona_runtime,
)
from backend.agents.celebrity.retrieval import retrieve_chunks


_CHARACTER_PROFILE_CACHE: dict[tuple[str, str, int], CharacterProfile] = {}
_CHARACTER_CANDIDATE_CACHE: dict[tuple[str, int], list[CharacterCandidate]] = {}
_INLINE_BUBBLE_CACHE: dict[tuple[str, int, tuple[str, ...], str, str], list[InlineBubble]] = {}

_CHINESE_CHARACTER_STOPWORDS = {
    "他说",
    "她说",
    "我说",
    "你说",
    "他们",
    "她们",
    "我们",
    "你们",
    "人们",
    "大家",
    "有人",
    "没有",
    "不是",
    "不能",
    "一个",
    "一种",
    "一些",
    "这个",
    "那个",
    "这里",
    "那里",
    "这样",
    "那样",
    "现在",
    "已经",
    "仍然",
    "依然",
    "实际上",
    "然而",
    "因此",
    "于是",
    "因为",
    "所以",
    "但是",
    "可是",
    "如果",
    "或者",
    "并且",
    "自己",
    "时候",
    "事情",
    "东西",
    "样子",
    "地方",
    "目录",
    "封面",
    "版权",
    "注释",
    "脚注",
    "译本",
    "互动百科",
}

_CHINESE_CHARACTER_SUFFIX_BLOCKLIST = (
    "说道",
    "说过",
    "说着",
    "说完",
    "起来",
    "下去",
    "进去",
    "出来",
    "之外",
    "之中",
    "的话",
)

_CHINESE_CHARACTER_CONTAINS_BLOCKLIST = (
    "目录",
    "版本",
    "脚注",
    "注释",
    "百科",
    "出版",
)


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
    slug = re.sub("[^a-zA-Z0-9\u4e00-\u9fff]+", "-", name.lower()).strip("-")
    return slug or "candidate"


def _is_valid_character_name(name: str) -> bool:
    normalized = re.sub(r"\s+", " ", name).strip(" ，。、“”\"'《》<>（）()[]")
    if not normalized or len(normalized) <= 1:
        return False
    if re.search(r"[0-9]", normalized):
        return False

    if re.fullmatch(r"[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})?", normalized):
        return True

    if not re.fullmatch(r"[\u4e00-\u9fff]{2,6}", normalized):
        return False
    if normalized in _CHINESE_CHARACTER_STOPWORDS:
        return False
    if normalized.startswith(("第", "这", "那", "其", "每", "某")):
        return False
    if normalized.endswith(("的人", "一样", "一般", "时候", "之后", "之前")):
        return False
    if any(normalized.endswith(suffix) for suffix in _CHINESE_CHARACTER_SUFFIX_BLOCKLIST):
        return False
    if any(token in normalized for token in _CHINESE_CHARACTER_CONTAINS_BLOCKLIST):
        return False
    return True


def _sample_visible_chunks(chunks: list[BookChunk], current_chapter: int, limit: int = 60) -> list[BookChunk]:
    visible = [chunk for chunk in chunks if chunk.chapter_index <= current_chapter]
    if len(visible) <= limit:
        return visible
    step = max(1, len(visible) // limit)
    sampled = visible[::step][:limit]
    return sampled


from backend.knowledge_graph.storage import graph_exists, load_graph


def _graph_character_candidates(book, current_chapter: int, limit: int = 10) -> list[CharacterCandidate]:
    """Return character candidates from the knowledge graph, falling back to empty list if no graph exists."""
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
        name = entity.canonical_name
        if not name or not name.strip():
            continue
        chapter_span = entity.metadata.get("chapter_span", []) if entity.metadata else []
        candidates.append(
            CharacterCandidate(
                character_id=f"char-{_character_slug(name)}",
                character_name=name,
                mention_count=entity.mention_count,
                chapter_hits=sorted(chapter_span) if chapter_span else [entity.first_seen_chapter],
                preview=entity.summary or f"{name}，从第{entity.first_seen_chapter}章到第{entity.last_seen_chapter}章出场{entity.mention_count}次。",
            )
        )
    candidates.sort(key=lambda c: c.mention_count, reverse=True)
    return candidates[:limit]

def _build_model_messages(system_prompt: str, user_prompt: str, history: list[ChatMessage] | None = None) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": system_prompt}]
    for turn in (history or [])[-8:]:
        messages.append({"role": turn.role, "content": turn.content})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _invoke_runtime(persona_id: str, messages: list[dict[str, str]], *, max_tokens: int = 900, temperature: float = 0.4) -> tuple[str, str]:
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
    return deduped


def _character_evidence(chunks: list[BookChunk], character_name: str, current_chapter: int, top_k: int = 8) -> list[BookChunk]:
    visible = [chunk for chunk in chunks if chunk.chapter_index <= current_chapter]
    direct = [chunk for chunk in visible if character_name in chunk.text]
    if direct:
        return direct[:top_k]
    ranked = retrieve_chunks(visible, query=character_name, max_chapter=current_chapter, top_k=top_k)
    ranked_ids = {item.chunk_id for item in ranked}
    return [chunk for chunk in visible if chunk.chunk_id in ranked_ids][:top_k]


def generate_character_profile(book, character_name: str, current_chapter: int) -> CharacterProfile:
    cache_key = (book.book_id, character_name, current_chapter)
    if cache_key in _CHARACTER_PROFILE_CACHE:
        return _CHARACTER_PROFILE_CACHE[cache_key]

    evidence_chunks = _character_evidence(book.chunks, character_name, current_chapter, top_k=10)
    if not evidence_chunks:
        raise PersonaAgentInvocationError(f"character `{character_name}` has no visible evidence in current reading scope")

    evidence_block = "\n\n".join(
        [f"[{chunk.chunk_id} | 第 {chunk.chapter_index} 章]\n{chunk.text}" for chunk in evidence_chunks]
    )
    system_prompt = (
        "你是文学阅读系统里的角色画像生成助手。"
        "请基于给定正文，为指定角色生成结构化角色画像。"
        "只返回 JSON 对象，字段必须包含 summary, core_traits, relationships, signature_tension, current_scope。"
        "relationships 是数组，每项包含 target 和 description。"
        "不要使用未来剧情，不要补充当前证据之外的设定。"
    )
    user_prompt = (
        f"书名：{book.title}\n"
        f"当前已读上限：第 {current_chapter} 章\n"
        f"目标角色：{character_name}\n"
        f"证据：\n{evidence_block}"
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

    evidence_block = "\n\n".join(
        [f"[{chunk.chunk_id} | 第 {chunk.chapter_index} 章]\n{chunk.text}" for chunk in evidence_chunks[:top_k]]
    )
    system_prompt = (
        f"你现在是阅读器里的角色 companion，围绕角色“{character_name}”与读者对话。"
        "请保持角色视角和人物口吻，但不能越过当前已读范围。"
        "如果证据不足，要坦白说明目前还不能确定。"
        "不要扮演全知叙述者，不要提前透露未来剧情。"
    )
    user_prompt = (
        f"书名：{book.title}\n"
        f"当前已读上限：第 {current_chapter} 章\n"
        f"角色画像：{profile.summary}\n"
        f"角色特征：{', '.join(profile.core_traits)}\n"
        f"关键张力：{profile.signature_tension}\n"
        f"当前问题：{question}\n"
        f"当前相关正文：\n{evidence_block}"
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

    evidence_block = "\n\n".join(
        [f"[{chunk.chunk_id}]\n{chunk.text}" for chunk in visible_chunks[:8]]
    )
    if assistant_mode == "character" and character_name:
        runtime_persona = "neutral"
        instruction = f"围绕角色“{character_name}”挑出最值得读者注意的词句。"
    else:
        runtime_persona = persona_id
        instruction = "从文学导读角度挑出最值得读者停留的词句。"

    system_prompt = (
        "你是阅读器里的 in-text bubble 生成助手。"
        "请只返回 JSON 数组，每项包含 chunk_id, anchor_text, label, comment, emphasis。"
        "anchor_text 必须是原文里的精确子串，comment 控制在 22 个字以内，label 控制在 6 个字以内。"
        "不要返回当前页面之外的内容。"
    )
    user_prompt = (
        f"书名：{book.title}\n"
        f"当前已读上限：第 {current_chapter} 章\n"
        f"任务：{instruction}\n"
        f"最多返回 {max_bubbles} 条注释。\n"
        f"当前正文：\n{evidence_block}"
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
                    label=label or "注",
                    comment=comment,
                    emphasis=emphasis if emphasis in {"theme", "emotion", "relation", "foreshadow", "detail"} else "detail",
                )
            )
    _INLINE_BUBBLE_CACHE[cache_key] = bubbles
    return bubbles
