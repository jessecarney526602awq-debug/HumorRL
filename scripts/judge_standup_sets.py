"""
读取 standup_sets.json，做 set-level Judge，并记录预测笑声位置/强度。

默认输入：
    data/standup_sets.json

默认输出：
    data/standup_set_judgments.json

支持可选演员资料文件：
    {
      "付航": "表演强烈、肢体感强、热场能力强……",
      "呼兰": "文本稳定、冷静观察、节奏平稳……"
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "standup_sets.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "standup_set_judgments.json"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "evaluate" / "standup_set.txt"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import humor_engine
import standup_persona

ALLOWED_INTENSITIES = {"smile", "laugh", "big_laugh", "applause"}
STANDUP_SET_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "set_score": {"type": "NUMBER"},
        "persona_consistency": {"type": "NUMBER"},
        "structure_issue": {"type": "STRING"},
        "strongest_segment": {
            "type": "OBJECT",
            "properties": {
                "paragraph_index": {"type": "INTEGER"},
                "excerpt": {"type": "STRING"},
                "reason": {"type": "STRING"},
            },
            "required": ["paragraph_index", "excerpt", "reason"],
        },
        "weakest_segment": {
            "type": "OBJECT",
            "properties": {
                "paragraph_index": {"type": "INTEGER"},
                "excerpt": {"type": "STRING"},
                "reason": {"type": "STRING"},
            },
            "required": ["paragraph_index", "excerpt", "reason"],
        },
        "predicted_laughs": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "paragraph_index": {"type": "INTEGER"},
                    "intensity": {"type": "STRING"},
                    "reason": {"type": "STRING"},
                },
                "required": ["paragraph_index", "intensity", "reason"],
            },
        },
    },
    "required": [
        "set_score",
        "persona_consistency",
        "structure_issue",
        "strongest_segment",
        "weakest_segment",
        "predicted_laughs",
    ],
}
STANDUP_SET_SCHEMA_FALLBACK = {
    "type": "OBJECT",
    "properties": {
        "set_score": {"type": "NUMBER"},
        "persona_consistency": {"type": "NUMBER"},
        "structure_issue": {"type": "STRING"},
        "strongest_segment": {
            "type": "OBJECT",
            "properties": {
                "paragraph_index": {"type": "INTEGER"},
                "excerpt": {"type": "STRING"},
                "reason": {"type": "STRING"},
            },
            "required": ["paragraph_index", "excerpt", "reason"],
        },
        "weakest_segment": {
            "type": "OBJECT",
            "properties": {
                "paragraph_index": {"type": "INTEGER"},
                "excerpt": {"type": "STRING"},
                "reason": {"type": "STRING"},
            },
            "required": ["paragraph_index", "excerpt", "reason"],
        },
    },
    "required": ["set_score", "persona_consistency", "structure_issue", "strongest_segment", "weakest_segment"],
}


def _standup_set_provider() -> str:
    provider = os.getenv("STANDUP_SET_PROVIDER", os.getenv("JUDGE_PROVIDER", "doubao"))
    return humor_engine._normalize_provider(provider)


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
    return standup_persona.load_profiles(path)


def _build_performer_profile_block(performer: str, profiles: dict[str, Any]) -> str:
    profile = standup_persona.build_profile_block(
        performer,
        profiles,
        fallback="演员资料：暂无额外资料，请只根据文本结构做判断。",
        detailed=False,
    )
    return f"演员资料（可用于模拟表演风格和笑声放大效应）：\n{profile}"


def _build_prompt(
    item: dict[str, Any],
    profiles: dict[str, Any],
    judge_guidance: str = "",
    *,
    quick_mode: bool = False,
) -> str:
    paragraphs = item.get("paragraphs", [])
    paragraph_block = "\n".join(f"[{i}] {text}" for i, text in enumerate(paragraphs))
    prompt = (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{performer}", item.get("performer", "未知演员"))
        .replace("{title}", item.get("title", "未命名段子"))
        .replace("{performer_profile_block}", _build_performer_profile_block(item.get("performer", ""), profiles))
        .replace("{additional_judge_guidance}", judge_guidance.strip() or "（暂无额外修正规则）")
        .replace("{text}", paragraph_block or item.get("clean_text", ""))
    )
    if quick_mode:
        prompt += (
            "\n\n快速复评模式："
            "\n- 这次只做重写后快速判断。"
            "\n- 不需要 predicted_laughs。"
            "\n- 重点看 set_score、persona_consistency、structure_issue、strongest_segment、weakest_segment。"
            "\n- 只输出当前 schema 需要的合法 JSON。"
        )
    return prompt


def _normalize_paragraph_index(value: Any, paragraph_count: int) -> int:
    try:
        index = int(value)
    except Exception:
        return 0
    if paragraph_count <= 0:
        return 0
    return max(0, min(index, paragraph_count - 1))


def _normalize_predicted_laughs(items: Any, paragraph_count: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return results
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        intensity = str(item.get("intensity", "laugh")).strip()
        if intensity not in ALLOWED_INTENSITIES:
            intensity = "laugh"
        results.append(
            {
                "paragraph_index": _normalize_paragraph_index(item.get("paragraph_index", 0), paragraph_count),
                "intensity": intensity,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
    return results


def _default_result(item: dict[str, Any], reason: str) -> dict[str, Any]:
    paragraph_count = len(item.get("paragraphs", []))
    return {
        "set_id": item["id"],
        "performer": item["performer"],
        "title": item["title"],
        "set_score": 5.0,
        "persona_consistency": 5.0,
        "structure_issue": reason,
        "strongest_segment": {
            "paragraph_index": 0,
            "excerpt": item.get("paragraphs", [""])[0] if paragraph_count else "",
            "reason": "默认回退结果，尚未成功分析。",
        },
        "weakest_segment": {
            "paragraph_index": max(0, paragraph_count - 1),
            "excerpt": item.get("paragraphs", [""])[-1] if paragraph_count else "",
            "reason": "默认回退结果，尚未成功分析。",
        },
        "predicted_laughs": [],
        "reference_markers": item.get("markers", []),
        "reaction_summary": item.get("reaction_summary", {}),
    }


def _parse_result(item: dict[str, Any], raw: str) -> dict[str, Any]:
    paragraph_count = len(item.get("paragraphs", []))
    data = json.loads(_clean_json_payload(raw))

    strongest = data.get("strongest_segment") or {}
    weakest = data.get("weakest_segment") or {}

    result = {
        "set_id": item["id"],
        "performer": item["performer"],
        "title": item["title"],
        "set_score": max(0.0, min(10.0, round(float(data.get("set_score", 5.0)), 1))),
        "persona_consistency": max(0.0, min(10.0, round(float(data.get("persona_consistency", 5.0)), 1))),
        "structure_issue": str(data.get("structure_issue", "")).strip(),
        "strongest_segment": {
            "paragraph_index": _normalize_paragraph_index(strongest.get("paragraph_index", 0), paragraph_count),
            "excerpt": str(strongest.get("excerpt", "")).strip(),
            "reason": str(strongest.get("reason", "")).strip(),
        },
        "weakest_segment": {
            "paragraph_index": _normalize_paragraph_index(weakest.get("paragraph_index", 0), paragraph_count),
            "excerpt": str(weakest.get("excerpt", "")).strip(),
            "reason": str(weakest.get("reason", "")).strip(),
        },
        "predicted_laughs": _normalize_predicted_laughs(data.get("predicted_laughs"), paragraph_count),
        "reference_markers": item.get("markers", []),
        "reaction_summary": item.get("reaction_summary", {}),
    }
    return result


def judge_set(
    item: dict[str, Any],
    profiles: dict[str, Any],
    judge_guidance: str = "",
    *,
    quick_mode: bool = False,
) -> dict[str, Any]:
    prompt = _build_prompt(item, profiles, judge_guidance=judge_guidance, quick_mode=quick_mode)
    provider = _standup_set_provider()
    max_tokens = 1200 if provider == "vertex" else 1200
    errors: list[str] = []

    schemas = [STANDUP_SET_SCHEMA_FALLBACK] if quick_mode else [STANDUP_SET_SCHEMA]
    if provider == "vertex" and not quick_mode:
        schemas.append(STANDUP_SET_SCHEMA_FALLBACK)

    for index, schema in enumerate(schemas, start=1):
        try:
            raw = humor_engine._judge_json(
                prompt,
                schema,
                temperature=0.2,
                max_tokens=max_tokens,
                role="judge",
                provider=provider,
            )
            result = _parse_result(item, raw)
            if schema is STANDUP_SET_SCHEMA_FALLBACK and not result["predicted_laughs"]:
                result["structure_issue"] = (
                    f"{result['structure_issue']}（本轮使用简化 schema 回退，笑声预测暂时留空）"
                ).strip()
            return result
        except Exception as exc:
            errors.append(f"attempt {index}: {exc}")
            prompt += (
                "\n\n补充要求："
                "\n- strongest_segment 和 weakest_segment 的 paragraph_index 必须是整数。"
                "\n- 如果 schema 里需要 predicted_laughs，但你无法稳定判断，就返回空数组，不要输出 null。"
                "\n- 只输出合法 JSON。"
            )

    if provider == "vertex":
        try:
            raw = humor_engine._judge_json(
                prompt,
                STANDUP_SET_SCHEMA_FALLBACK if quick_mode else STANDUP_SET_SCHEMA,
                temperature=0.2,
                max_tokens=900 if quick_mode else 1200,
                role="judge",
                provider="doubao",
            )
            result = _parse_result(item, raw)
            result["structure_issue"] = (
                f"{result['structure_issue']}（Vertex 不稳定，本轮已自动回退到 Doubao set Judge）"
            ).strip()
            return result
        except Exception as exc:
            errors.append(f"doubao fallback: {exc}")

    return _default_result(item, f"set-level Judge 失败，已回退：{' | '.join(errors)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profiles", type=Path, default=None, help="演员资料 JSON")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 篇")
    args = parser.parse_args()

    payload = json.loads(args.input.read_text(encoding="utf-8"))
    items = payload.get("standup_sets", [])
    if args.limit and args.limit > 0:
        items = items[: args.limit]

    profiles = _load_actor_profiles(args.profiles)
    results = [judge_set(item, profiles) for item in items]

    out = {
        "version": "1.0",
        "description": "set-level stand-up Judge 结果，包含 strongest/weakest segment 与预测笑声分布",
        "source": str(args.input),
        "profiles": str(args.profiles) if args.profiles else None,
        "judgments": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成：{args.output}")
    for item in results[:5]:
        print(
            f"- {item['performer']} / {item['title']} "
            f"set_score={item['set_score']:.1f} "
            f"persona_consistency={item['persona_consistency']:.1f} "
            f"predicted_laughs={len(item['predicted_laughs'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
