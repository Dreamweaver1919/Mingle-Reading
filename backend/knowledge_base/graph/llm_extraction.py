from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.common.models import BookChunk
from backend.llm_memory.persona.model_client import invoke_openai_compatible_messages


GraphEntityType = Literal["character", "location", "artifact", "group", "theme", "concept", "unknown"]
GraphRelationDirectionality = Literal["directed", "undirected"]

ALLOWED_ENTITY_TYPES: set[str] = {"character", "location", "artifact", "group", "theme", "concept", "unknown"}
ALLOWED_DIRECTIONALITIES: set[str] = {"directed", "undirected"}
ALLOWED_STATE_FAMILIES: set[str] = {
    "context",
    "location",
    "membership",
    "interaction",
    "sentiment",
    "identity",
    "status",
    "theme",
}

GRAPH_EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "graphiti_episode_extraction",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "canonical_name": {"type": "string"},
                            "entity_type": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                            "resolution_hint": {"type": "string"},
                            "evidence": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "canonical_name",
                            "entity_type",
                            "aliases",
                            "resolution_hint",
                            "evidence",
                            "confidence",
                        ],
                    },
                },
                "facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "source": {"type": "string"},
                            "target": {"type": "string"},
                            "relation_type": {"type": "string"},
                            "state_family": {"type": "string"},
                            "directionality": {"type": "string"},
                            "fact": {"type": "string"},
                            "evidence": {"type": "string"},
                            "confidence": {"type": "number"},
                        },
                        "required": [
                            "source",
                            "target",
                            "relation_type",
                            "state_family",
                            "directionality",
                            "fact",
                            "evidence",
                            "confidence",
                        ],
                    },
                },
            },
            "required": ["entities", "facts"],
        },
    },
}

GRAPH_EXTRACTION_JSON_OBJECT: dict[str, Any] = {"type": "json_object"}


@dataclass(slots=True)
class GraphExtractorRuntime:
    api_key: str
    base_url: str
    model_name: str
    provider_label: str


class KnownEntityCandidate(BaseModel):
    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = Field(default_factory=list)
    mention_count: int = 0
    last_seen_chapter: int = 0
    last_seen_paragraph: int = 0


class ExtractedEntityCandidate(BaseModel):
    canonical_name: str
    entity_type: GraphEntityType = "character"
    aliases: list[str] = Field(default_factory=list)
    resolution_hint: str = ""
    evidence: str = ""
    confidence: float = 0.0


class ExtractedFactCandidate(BaseModel):
    source: str
    target: str
    relation_type: str
    state_family: str = "context"
    directionality: GraphRelationDirectionality = "undirected"
    fact: str
    evidence: str = ""
    confidence: float = 0.0


class EpisodeGraphExtraction(BaseModel):
    entities: list[ExtractedEntityCandidate] = Field(default_factory=list)
    facts: list[ExtractedFactCandidate] = Field(default_factory=list)
    extraction_mode: Literal["llm-assisted", "heuristic"] = "llm-assisted"
    provider_label: str = ""
    raw_response: str = ""


def resolve_graph_extractor_runtime() -> GraphExtractorRuntime | None:
    if os.getenv("PYTEST_CURRENT_TEST"):
        return None
    if os.getenv("GRAPHITI_EXTRACTOR_DISABLE", "").strip().lower() in {"1", "true", "yes"}:
        return None
    candidates = [
        (
            "GRAPHITI_EXTRACTOR_API_KEY",
            "GRAPHITI_EXTRACTOR_BASE_URL",
            "GRAPHITI_EXTRACTOR_MODEL_NAME",
            "graphiti-extractor",
        ),
        (
            "MUSE_NEUTRAL_API_KEY",
            "MUSE_NEUTRAL_BASE_URL",
            "MUSE_NEUTRAL_MODEL_NAME",
            "neutral-fallback",
        ),
    ]
    for api_key_var, base_url_var, model_name_var, label in candidates:
        api_key = os.getenv(api_key_var, "").strip()
        base_url = os.getenv(base_url_var, "").strip()
        model_name = os.getenv(model_name_var, "").strip()
        if api_key and base_url and model_name:
            return GraphExtractorRuntime(
                api_key=api_key,
                base_url=base_url,
                model_name=model_name,
                provider_label=label,
            )
    return None


def extract_episode_graph_with_llm(
    *,
    runtime: GraphExtractorRuntime,
    chunk: BookChunk,
    known_entities: list[KnownEntityCandidate],
    recent_episode_contexts: list[str],
    timeout_seconds: int = 90,
) -> EpisodeGraphExtraction:
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(
        chunk=chunk,
        known_entities=known_entities,
        recent_episode_contexts=recent_episode_contexts,
    )
    latest_raw = ""
    for attempt in range(1, 4):
        raw = _invoke_with_response_format_fallback(
            runtime=runtime,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout_seconds=timeout_seconds,
            response_format=GRAPH_EXTRACTION_JSON_SCHEMA,
        )
        latest_raw = raw
        payload = _parse_json_payload(raw)
        if payload is None:
            raw = _repair_non_json_output(
                runtime=runtime,
                invalid_output=raw,
                timeout_seconds=timeout_seconds,
            )
            latest_raw = raw
            payload = _parse_json_payload(raw)
        if payload is not None:
            extraction = EpisodeGraphExtraction(
                entities=_coerce_entities(payload.get("entities", [])),
                facts=_coerce_facts(payload.get("facts", [])),
                extraction_mode="llm-assisted",
                provider_label=runtime.provider_label,
                raw_response=raw,
            )
            return extraction
        if attempt < 3:
            time.sleep(min(1.5, 0.35 * attempt))
    raise ValueError(f"llm extraction returned non-JSON content: {_clip_text(latest_raw)}")


def _build_system_prompt() -> str:
    return "\n".join(
        [
            "You extract Graphiti-style temporal knowledge graph updates from literary text.",
            "Treat the current paragraph as one canonical episode.",
            "Resolve mentions to stable entities when the text and known-entity list support it.",
            "Return strict JSON only. Do not use markdown fences.",
            'Use this schema: {"entities":[...],"facts":[...]}',
            "Each entity item must contain canonical_name, entity_type, aliases, resolution_hint, evidence, confidence.",
            "Each fact item must contain source, target, relation_type, state_family, directionality, fact, evidence, confidence.",
            "Only emit facts directly supported by the provided paragraph or immediate local context.",
            "Do not infer future events or hidden facts.",
            "Use directionality=directed only when source -> target matters.",
            'If there is no confident extraction, return {"entities":[],"facts":[]}.',
            "Preferred relation/state families:",
            "- LOCATED_IN -> location",
            "- MEMBER_OF -> membership",
            "- SPOKE_WITH -> interaction",
            "- CONFLICTS_WITH -> interaction",
            "- CARES_ABOUT -> sentiment",
            "- FAMILY_OF -> identity",
            "- OWNS / CARRIES / USES -> status or context depending on the sentence",
            "When unsure, omit the fact instead of hallucinating.",
        ]
    )


def _build_user_prompt(
    *,
    chunk: BookChunk,
    known_entities: list[KnownEntityCandidate],
    recent_episode_contexts: list[str],
) -> str:
    known_entity_lines = [
        (
            f"- {item.entity_id} | {item.canonical_name} | type={item.entity_type} "
            f"| aliases={','.join(item.aliases[:5])} | mentions={item.mention_count} "
            f"| last_seen=c{item.last_seen_chapter}/p{item.last_seen_paragraph}"
        )
        for item in known_entities[:25]
    ]
    recent_context_block = "\n".join(f"- {text}" for text in recent_episode_contexts[-3:] if text.strip())
    metadata = {
        "book_id": chunk.book_id,
        "chapter_id": chunk.chapter_id,
        "chapter_index": chunk.chapter_index,
        "paragraph_id": chunk.paragraph_id,
        "paragraph_index": chunk.paragraph_index,
        "candidate_characters": chunk.candidate_characters,
        "metadata": chunk.metadata,
    }
    return "\n".join(
        [
            "Current episode metadata:",
            json.dumps(metadata, ensure_ascii=False, indent=2),
            "",
            "Recent visible context before this episode:",
            recent_context_block or "- none",
            "",
            "Known entities already in the graph:",
            "\n".join(known_entity_lines) or "- none",
            "",
            "Current episode text:",
            chunk.text,
            "",
            "Extraction requirements:",
            "1. Normalize recurring mentions to stable canonical names when supported.",
            "2. Prefer known entities in the graph when the mention clearly matches one.",
            "3. Keep aliases short and exact.",
            "4. Return only JSON.",
        ]
    )


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_payload(raw: str) -> dict[str, Any]:
    cleaned = _strip_fences(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None


def _repair_non_json_output(
    *,
    runtime: GraphExtractorRuntime,
    invalid_output: str,
    timeout_seconds: int,
) -> str:
    repair_system_prompt = "\n".join(
        [
            "You are a JSON repair assistant.",
            "Convert the given extraction output into strict JSON only.",
            'Target schema: {"entities":[...],"facts":[...]}',
            "Do not add markdown fences, commentary, or explanations.",
            'If the content cannot be recovered, return {"entities":[],"facts":[]}.',
        ]
    )
    repair_user_prompt = "\n".join(
        [
            "Rewrite the following content into valid JSON matching the required schema.",
            "Return JSON only.",
            "",
            invalid_output,
        ]
    )
    return _invoke_with_response_format_fallback(
        runtime=runtime,
        messages=[
            {"role": "system", "content": repair_system_prompt},
            {"role": "user", "content": repair_user_prompt},
        ],
        timeout_seconds=timeout_seconds,
        response_format=GRAPH_EXTRACTION_JSON_OBJECT,
    )


def _invoke_with_response_format_fallback(
    *,
    runtime: GraphExtractorRuntime,
    messages: list[dict[str, str]],
    timeout_seconds: int,
    response_format: dict[str, Any],
) -> str:
    try:
        return _invoke_with_retries(
            runtime=runtime,
            messages=messages,
            timeout_seconds=timeout_seconds,
            response_format=response_format,
        )
    except RuntimeError as exc:
        if not _is_response_format_unsupported(exc):
            raise
    return _invoke_with_retries(
        runtime=runtime,
        messages=messages,
        timeout_seconds=timeout_seconds,
        response_format=None,
    )


def _is_response_format_unsupported(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    markers = [
        "response_format type is unavailable",
        "response_format is unavailable",
        "unsupported response_format",
        "response_format is not supported",
        "response format is unavailable",
        "response format is not supported",
    ]
    return any(marker in message for marker in markers)


def _invoke_with_retries(
    *,
    runtime: GraphExtractorRuntime,
    messages: list[dict[str, str]],
    timeout_seconds: int,
    response_format: dict[str, Any] | None,
    max_attempts: int = 3,
) -> str:
    last_exc: RuntimeError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return invoke_openai_compatible_messages(
                api_key=runtime.api_key,
                base_url=runtime.base_url,
                model_name=runtime.model_name,
                messages=messages,
                temperature=0.0,
                max_tokens=1200,
                timeout_seconds=timeout_seconds,
                response_format=response_format,
            )
        except RuntimeError as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_retryable_transport_error(exc):
                raise
            time.sleep(min(2.0, 0.5 * attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("llm invocation failed without an explicit exception")


def _is_retryable_transport_error(exc: RuntimeError) -> bool:
    message = str(exc).lower()
    markers = [
        "network timeout",
        "timed out",
        "temporarily unavailable",
        "connection reset",
        "connection aborted",
        "connection refused",
        "remote end closed connection",
    ]
    return any(marker in message for marker in markers)


def _coerce_entities(rows: list[Any]) -> list[ExtractedEntityCandidate]:
    entities: list[ExtractedEntityCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        canonical_name = str(row.get("canonical_name") or row.get("name") or "").strip()
        if not canonical_name:
            continue
        entity_type = str(row.get("entity_type") or "character").strip().lower()
        if entity_type not in ALLOWED_ENTITY_TYPES:
            entity_type = "unknown"
        aliases = [
            str(alias).strip()
            for alias in row.get("aliases", [])
            if isinstance(alias, str) and str(alias).strip()
        ]
        entities.append(
            ExtractedEntityCandidate(
                canonical_name=canonical_name,
                entity_type=entity_type,  # type: ignore[arg-type]
                aliases=aliases,
                resolution_hint=str(row.get("resolution_hint") or row.get("resolved_as") or "").strip(),
                evidence=str(row.get("evidence") or "").strip(),
                confidence=_coerce_confidence(row.get("confidence")),
            )
        )
    return entities


def _coerce_facts(rows: list[Any]) -> list[ExtractedFactCandidate]:
    facts: list[ExtractedFactCandidate] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "").strip()
        target = str(row.get("target") or "").strip()
        relation_type = str(row.get("relation_type") or "").strip()
        fact = str(row.get("fact") or "").strip()
        if not source or not target or not relation_type or not fact:
            continue
        state_family = str(row.get("state_family") or "context").strip().lower()
        if state_family not in ALLOWED_STATE_FAMILIES:
            state_family = "context"
        directionality = str(row.get("directionality") or "undirected").strip().lower()
        if directionality not in ALLOWED_DIRECTIONALITIES:
            directionality = "undirected"
        facts.append(
            ExtractedFactCandidate(
                source=source,
                target=target,
                relation_type=relation_type.upper(),
                state_family=state_family,
                directionality=directionality,  # type: ignore[arg-type]
                fact=fact,
                evidence=str(row.get("evidence") or "").strip(),
                confidence=_coerce_confidence(row.get("confidence")),
            )
        )
    return facts


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(confidence, 1.0))


def _clip_text(text: str, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
