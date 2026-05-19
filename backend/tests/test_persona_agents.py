from __future__ import annotations

from backend.common.models import PersonaPromptPreviewRequest, PersonaRAGQueryRequest
from backend.llm_memory.persona.persona_service import (
    build_persona_prompt_preview,
    get_persona_agent,
    get_persona_kb_manifest,
    list_persona_agents,
    resolve_persona_runtime,
    retrieve_persona_snippets,
)


def test_persona_agents_are_exposed_with_celebrity_skill_paths():
    agents = list_persona_agents()
    agent_ids = {agent.agent_id for agent in agents}
    assert {"neutral", "lu-xun", "mark-twain", "zhang-ailing"}.issubset(agent_ids)

    lu_xun = get_persona_agent("persona_lu_xun")
    assert "Celebrity-skill" in lu_xun.persona_pack_path
    assert "Celebrity-skill" in lu_xun.catalog_path
    assert lu_xun.catalog_summary.total_sources > 0
    assert lu_xun.catalog_summary.voice_sources > 0


def test_persona_kb_manifest_is_built_from_celebrity_skill_bundle():
    manifest = get_persona_kb_manifest("mark-twain")
    assert manifest["persona_id"] == "persona_mark_twain"
    assert manifest["source"] == "celebrity-skill"
    assert "MarkTwain-skill-main" in manifest["skill_root"]
    assert manifest["snippet_counts"]["total_snippets"] > 0
    assert manifest["document_counts"]["works"] > 0


def test_persona_snippet_retrieval_returns_ranked_hits_or_skill_fallback():
    hits = retrieve_persona_snippets(
        "zhang-ailing",
        PersonaRAGQueryRequest(query="都市 细节 关系 苍凉", top_k=3),
    )
    assert len(hits) >= 1
    assert hits[0].score > 0
    assert hits[0].source_category in {
        "works",
        "voice_sources",
        "biography_and_critical",
        "skill_rules",
        "overview",
    }


def test_persona_prompt_preview_contains_celebrity_skill_context():
    preview = build_persona_prompt_preview(
        "lu-xun",
        PersonaPromptPreviewRequest(
            book_context="一段关于围观、麻木与服从压力的文本。",
            question="这段体现了怎样的社会病理？",
            top_k=3,
        ),
    )
    assert preview.persona_id == "persona_lu_xun"
    assert "Celebrity-skill" in preview.system_prompt
    assert "鲁迅" in preview.system_prompt
    assert preview.retrieved_hits
    assert any(hit.source_category in {"skill_rules", "voice_sources"} for hit in preview.retrieved_hits)


def test_resolve_persona_runtime_requires_complete_env(monkeypatch):
    monkeypatch.delenv("LU_XUN_API_KEY", raising=False)
    monkeypatch.delenv("LU_XUN_BASE_URL", raising=False)
    monkeypatch.delenv("LU_XUN_MODEL_NAME", raising=False)
    try:
        resolve_persona_runtime("lu-xun")
    except RuntimeError as exc:
        assert "LU_XUN_API_KEY" in str(exc)
        assert "LU_XUN_BASE_URL" in str(exc)
        assert "LU_XUN_MODEL_NAME" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("resolve_persona_runtime should fail when env vars are missing")
