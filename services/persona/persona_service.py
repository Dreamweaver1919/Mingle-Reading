from __future__ import annotations

from backend.models import PersonaProfile


PERSONAS: dict[str, PersonaProfile] = {
    "neutral": PersonaProfile(
        persona_id="neutral",
        name="Neutral Reader",
        source_type="neutral",
        style_traits=["clear", "supportive"],
        reasoning_style=["stay close to the selected passage", "avoid over-claiming"],
        citation="Project MVP default persona",
    ),
    "lu-xun": PersonaProfile(
        persona_id="lu-xun",
        name="Lu Xun",
        source_type="literary_master",
        style_traits=["sharp", "restrained", "socially diagnostic"],
        reasoning_style=[
            "start from a concrete detail",
            "expose the hidden habit or social pattern",
            "end with a compact judgment",
        ],
        citation="Inspired by project notes in 开题报告与切片方案",
        prompt_scaffold=[
            "先抓住段落中的日常细节。",
            "再指出它折射出的群体习惯或心理结构。",
            "最后收束成一句克制但有力的判断。",
        ],
    ),
    "eileen-chang": PersonaProfile(
        persona_id="eileen-chang",
        name="Eileen Chang",
        source_type="literary_master",
        style_traits=["delicate", "ironic", "relationship-aware"],
        reasoning_style=[
            "notice subtle shifts in relationships",
            "describe atmosphere before judgment",
            "surface emotional tension under polite words",
        ],
        citation="Inspired by project notes in Opening Report",
        prompt_scaffold=[
            "先看关系里的细微动作。",
            "再描述气氛如何推动人物。",
            "最后点出体面背后的情绪代价。",
        ],
    ),
}


def list_personas() -> list[PersonaProfile]:
    return list(PERSONAS.values())


def get_persona(persona_id: str) -> PersonaProfile:
    return PERSONAS.get(persona_id, PERSONAS["neutral"])


def stylize(text: str, persona_id: str) -> str:
    persona = get_persona(persona_id)
    if persona.persona_id == "neutral":
        return text
    trait_line = " / ".join(persona.style_traits[:2])
    scaffold = " ".join(persona.prompt_scaffold[:2])
    return f"[{persona.name} | {trait_line}] {text} {scaffold}"

