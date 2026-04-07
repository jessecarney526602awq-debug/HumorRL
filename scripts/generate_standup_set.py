"""
生成文本型 stand-up 初稿，并组装成可直接进入
judge -> segment -> rewrite 链路的 item dict。

默认输出：
    data/generated_standup_set.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "prompts" / "generate" / "standup_set.txt"
PLAN_PROMPT_PATH = PROJECT_ROOT / "prompts" / "generate" / "standup_plan.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "generated_standup_set.json"
DEFAULT_PROFILES = PROJECT_ROOT / "data" / "standup_actor_profiles.example.json"
HUMOR_REFERENCE_PATH = PROJECT_ROOT / "prompts" / "reference" / "humor_cases.txt"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import db
import humor_engine
import standup_persona


def _clean_json_payload(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def _load_actor_profiles(path: Path | None) -> dict[str, Any]:
    profiles = standup_persona.load_profiles(path)
    return profiles


def _build_persona_block(persona_name: str | None) -> str:
    if not persona_name:
        return ""
    for persona in db.get_personas():
        if persona.name == persona_name or str(persona.id) == str(persona_name):
            return f"你的角色设定：\n{persona.style_prompt}"
    return ""


def _build_performer_style_block(performer: str, profiles: dict[str, Any]) -> str:
    return standup_persona.build_profile_block(
        performer,
        profiles,
        fallback="暂无额外演员资料，请按文本型 stand-up 的稳定结构来写。",
        detailed=True,
    )


def _build_reference_block() -> str:
    parts: list[str] = []
    try:
        humor_reference = humor_engine._read_prompt(str(HUMOR_REFERENCE_PATH.relative_to(PROJECT_ROOT))).strip()
        if humor_reference:
            parts.append(humor_reference)
    except Exception:
        pass

    try:
        rows = db.get_knowledge(entry_type="humor_rule", limit=5)
        if rows:
            parts.append("历史沉淀的幽默规律：\n" + "\n".join(f"- {row['content']}" for row in rows))
    except Exception:
        pass

    return "\n\n".join(part for part in parts if part.strip()) or "（暂无额外参考）"


def _build_writer_lessons() -> str:
    try:
        rows = db.get_knowledge(entry_type="writer_lesson", limit=5)
    except Exception:
        rows = []
    if not rows:
        return "（暂无）"
    return "\n".join(f"- {row['content']}" for row in rows)


def _repair_plan_json(raw: str) -> dict[str, Any]:
    prompt = (
        "把下面这段内容修复成严格合法的 JSON，只保留这些字段："
        "`title_hint`、`theme_angle`、`speaking_object`、`opening_move`、"
        "`narrative_contract`、`comedic_engine`、`central_premise`、`running_thread`、`escalation_outline`、"
        "`closer_goal`、`hidden_iceberg`、`audience_filters`、`forbidden_surfaces`、"
        "`complaint_traps`、`reality_checks`、`voice_guardrails`。"
        "数组字段必须是字符串数组。不要解释。\n\n"
        f"{raw}"
    )
    fixed = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215"),
        prompt,
        temperature=0.0,
        max_tokens=1200,
        role="strategist",
    )
    return json.loads(_clean_json_payload(fixed))


def _parse_plan(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(_clean_json_payload(raw))
    except JSONDecodeError:
        data = _repair_plan_json(raw)

    def _lines(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    return {
        "title_hint": str(data.get("title_hint", "")).strip(),
        "theme_angle": str(data.get("theme_angle", "")).strip(),
        "speaking_object": str(data.get("speaking_object", "")).strip(),
        "opening_move": str(data.get("opening_move", "")).strip(),
        "narrative_contract": str(data.get("narrative_contract", "")).strip(),
        "comedic_engine": str(data.get("comedic_engine", "")).strip(),
        "central_premise": str(data.get("central_premise", "")).strip(),
        "running_thread": str(data.get("running_thread", "")).strip(),
        "escalation_outline": _lines("escalation_outline"),
        "closer_goal": str(data.get("closer_goal", "")).strip(),
        "hidden_iceberg": _lines("hidden_iceberg"),
        "audience_filters": _lines("audience_filters"),
        "forbidden_surfaces": _lines("forbidden_surfaces"),
        "complaint_traps": _lines("complaint_traps"),
        "reality_checks": _lines("reality_checks"),
        "voice_guardrails": _lines("voice_guardrails"),
    }


def _build_plan_block(plan: dict[str, Any]) -> str:
    sections: list[str] = []
    direct_fields = [
        ("标题方向", "title_hint"),
        ("主题角度", "theme_angle"),
        ("讲述对象", "speaking_object"),
        ("开场动作", "opening_move"),
        ("讲述承诺", "narrative_contract"),
        ("幽默发动方式", "comedic_engine"),
        ("核心 premise", "central_premise"),
        ("running thread", "running_thread"),
        ("结尾目标", "closer_goal"),
    ]
    for label, key in direct_fields:
        value = str(plan.get(key, "")).strip()
        if value:
            sections.append(f"{label}：{value}")

    list_fields = [
        ("递进大纲", "escalation_outline"),
        ("冰山下的信息（不要直接讲透）", "hidden_iceberg"),
        ("观众理解过滤规则", "audience_filters"),
        ("禁止浮在表面的写法", "forbidden_surfaces"),
        ("抱怨/碎碎念陷阱", "complaint_traps"),
        ("真实性检查", "reality_checks"),
        ("口吻边界", "voice_guardrails"),
    ]
    for label, key in list_fields:
        values = plan.get(key) or []
        if values:
            sections.append(f"{label}：\n" + "\n".join(f"- {item}" for item in values))
    return "\n\n".join(sections).strip() or "（暂无额外策划方案）"


def _plan_standup_set(
    topic: str,
    performer: str,
    target_audience: str,
    tone: str,
    duration_minutes: int | None,
    persona_name: str | None,
    profiles: dict[str, Any],
) -> dict[str, Any]:
    if duration_minutes and duration_minutes > 0:
        duration_block = f"约 {duration_minutes} 分钟口播时长。"
    else:
        duration_block = "未指定，按中等篇幅 stand-up 处理。"
    prompt = (
        PLAN_PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{persona_block}", _build_persona_block(persona_name))
        .replace("{performer_style_block}", _build_performer_style_block(performer, profiles))
        .replace("{target_audience}", target_audience)
        .replace("{tone}", tone)
        .replace("{duration_block}", duration_block)
        .replace("{reference_block}", _build_reference_block())
        .replace("{topic}", topic)
    )
    raw = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215"),
        prompt,
        temperature=0.4,
        max_tokens=1800,
        role="strategist",
    )
    return _parse_plan(raw)


def _build_prompt(
    topic: str,
    performer: str,
    target_audience: str,
    tone: str,
    paragraph_target: int,
    duration_minutes: int | None,
    persona_name: str | None,
    profiles: dict[str, Any],
    plan: dict[str, Any],
) -> str:
    strategy_context = db.get_current_directive() or "（战略师暂无特别指令，优先写出文本稳定、结构成立的 stand-up）"
    if duration_minutes and duration_minutes > 0:
        duration_block = f"约 {duration_minutes} 分钟口播时长。篇幅应明显大于短段子，允许更完整地展开 2-3 轮观察递进。"
    else:
        duration_block = "未指定，按目标段数自然控制。"
    prompt = humor_engine._read_prompt(str(PROMPT_PATH.relative_to(PROJECT_ROOT)))
    return (
        prompt.replace("{persona_block}", _build_persona_block(persona_name))
        .replace("{performer_style_block}", _build_performer_style_block(performer, profiles))
        .replace("{planning_block}", _build_plan_block(plan))
        .replace("{target_audience}", target_audience)
        .replace("{tone}", tone)
        .replace("{duration_block}", duration_block)
        .replace("{paragraph_target}", str(paragraph_target))
        .replace("{strategy_context}", strategy_context)
        .replace("{writer_lessons}", _build_writer_lessons())
        .replace("{reference_block}", _build_reference_block())
        .replace("{topic}", topic)
    )


def _repair_generation_json(raw: str) -> dict[str, Any]:
    prompt = (
        "把下面这段内容修复成严格合法的 JSON，只保留三个字段："
        "`title`、`generation_note`、`text`。"
        "`text` 必须是一个字符串，内部用 \\n\\n 表示段落分隔。不要解释。\n\n"
        f"{raw}"
    )
    fixed = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2.0-pro-260215"),
        prompt,
        temperature=0.0,
        max_tokens=1200,
        role="strategist",
    )
    return json.loads(_clean_json_payload(fixed))


def _parse_generation(raw: str) -> dict[str, str]:
    try:
        data = json.loads(_clean_json_payload(raw))
    except JSONDecodeError:
        data = _repair_generation_json(raw)

    title = str(data.get("title", "")).strip() or "未命名 stand-up 初稿"
    generation_note = str(data.get("generation_note", "")).strip()
    text = str(data.get("text", "")).strip()
    if not text:
        raise ValueError("生成结果缺少 text")
    return {"title": title, "generation_note": generation_note, "text": text}


def _paragraphs_from_text(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").strip()
    paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [part.strip() for part in re.split(r"\n+", text) if part.strip()]
    return paragraphs


def _build_item(
    performer: str,
    topic: str,
    generated: dict[str, str],
    profiles: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    text = generated["text"].strip()
    paragraphs = _paragraphs_from_text(text)
    normalized_text = "\n\n".join(paragraphs)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "topic"
    set_id = f"generated_standup_{timestamp}_{slug}"
    return {
        "id": set_id,
        "performer": performer,
        "section": "generated",
        "title": generated["title"],
        "source_file": None,
        "source_type": "generated_standup_set",
        "source_section_index": None,
        "full_text": normalized_text,
        "clean_text": normalized_text,
        "paragraphs": paragraphs,
        "markers": [],
        "reaction_summary": {
            "laugh_count": 0,
            "big_laugh_count": 0,
            "applause_count": 0,
        },
        "is_excerpt": False,
        "generation_note": generated["generation_note"],
        "planning_note": plan,
        "topic": topic,
        "performer_profile_snapshot": standup_persona.build_profile_block(
            performer,
            profiles,
            fallback="",
            detailed=False,
        ),
    }


def generate_item(
    topic: str,
    performer: str = "呼兰",
    target_audience: str = "都市年轻打工人",
    tone: str = "观察、自嘲、克制、文本强",
    paragraph_target: int = 6,
    duration_minutes: int | None = None,
    persona_name: str | None = None,
    profiles: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    profiles = profiles or {}
    plan = _plan_standup_set(
        topic=topic,
        performer=performer,
        target_audience=target_audience,
        tone=tone,
        duration_minutes=duration_minutes,
        persona_name=persona_name,
        profiles=profiles,
    )
    prompt = _build_prompt(
        topic=topic,
        performer=performer,
        target_audience=target_audience,
        tone=tone,
        paragraph_target=paragraph_target,
        duration_minutes=duration_minutes,
        persona_name=persona_name,
        profiles=profiles,
        plan=plan,
    )
    raw = humor_engine._chat(
        humor_engine._writer_client(),
        os.getenv("DOUBAO_WRITER_MODEL", "doubao-seed-2.0-lite-260215"),
        prompt,
        temperature=0.9,
        max_tokens=2600,
        role="writer",
    )
    generated = _parse_generation(raw)
    item = _build_item(performer, topic, generated, profiles, plan)
    payload = {
        "version": "1.0",
        "description": "文本型 stand-up 初稿生成结果，可直接进入 judge -> segment -> rewrite 链",
        "prompt_topic": topic,
        "performer": performer,
        "target_audience": target_audience,
        "tone": tone,
        "paragraph_target": paragraph_target,
        "duration_minutes": duration_minutes or 0,
        "plan": plan,
        "item": item,
        "standup_sets": [item],
    }
    return item, payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="本次 stand-up 的主题")
    parser.add_argument("--performer", default="呼兰", help="目标文本风格演员/人设")
    parser.add_argument("--target-audience", default="都市年轻打工人", help="目标受众")
    parser.add_argument("--tone", default="观察、自嘲、克制、文本强", help="语气和写作取向")
    parser.add_argument("--paragraph-target", type=int, default=6, help="目标段数")
    parser.add_argument("--duration-minutes", type=int, default=0, help="目标口播时长（分钟）")
    parser.add_argument("--persona", default="", help="可选 persona 名称或 id")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    profiles = _load_actor_profiles(args.profiles)
    item, payload = generate_item(
        topic=args.topic,
        performer=args.performer,
        target_audience=args.target_audience,
        tone=args.tone,
        paragraph_target=args.paragraph_target,
        duration_minutes=args.duration_minutes or None,
        persona_name=args.persona or None,
        profiles=profiles,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成：{args.output}")
    print(f"- title={item['title']}")
    print(f"- performer={item['performer']}")
    print(f"- paragraphs={len(item['paragraphs'])}")
    print(f"- id={item['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
