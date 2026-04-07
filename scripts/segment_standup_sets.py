"""
读取 standup_sets.json，做 stand-up 粗拆段，输出 5-7 个结构 segment。

默认输入：
    data/standup_sets.json

默认输出：
    data/standup_segments.json

支持可选：
- set-level Judge 结果
- 演员资料 JSON
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from json import JSONDecodeError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "standup_sets.json"
DEFAULT_JUDGMENTS = PROJECT_ROOT / "data" / "standup_set_judgments.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "standup_segments.json"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "evaluate" / "standup_segments.txt"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import humor_engine
import standup_persona

ALLOWED_ROLES = {"opening", "premise", "build", "punch", "closer"}
ALLOWED_PRIORITIES = {"low", "medium", "high"}


def _clean_json_payload(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def _repair_segment_json(raw: str) -> dict[str, Any]:
    prompt = (
        "把下面这段内容修复成严格合法的 JSON，只保留 `segmentation_note` 和 `segments`。"
        "`segments` 中每项必须包含：segment_index, role, start_paragraph, end_paragraph, summary, function, rewrite_priority。"
        "不要解释。\n\n"
        f"{raw}"
    )
    fixed = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2.0-pro-260215"),
        prompt,
        temperature=0.0,
        max_tokens=1400,
        role="strategist",
    )
    return json.loads(_clean_json_payload(fixed))


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_actor_profiles(path: Path | None) -> dict[str, Any]:
    return standup_persona.load_profiles(path)


def _build_performer_profile_block(performer: str, profiles: dict[str, Any]) -> str:
    profile = standup_persona.build_profile_block(
        performer,
        profiles,
        fallback="演员资料：暂无额外资料，请优先按文本结构拆段。",
        detailed=False,
    )
    return f"演员资料（仅作辅助，优先按文本结构判断）：\n{profile}"


def _build_judgment_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    judgments = payload.get("judgments", [])
    index: dict[str, dict[str, Any]] = {}
    for item in judgments:
        if isinstance(item, dict) and item.get("set_id"):
            index[str(item["set_id"])] = item
    return index


def _format_marker_hint(item: dict[str, Any], paragraph_index: int) -> str:
    markers = item.get("markers", [])
    names = [
        str(marker.get("marker", "")).strip()
        for marker in markers
        if isinstance(marker, dict) and int(marker.get("paragraph_index", -1)) == paragraph_index
    ]
    if not names:
        return ""
    return f"  <markers: {' / '.join(names)}>"


def _build_text_block(item: dict[str, Any]) -> str:
    paragraphs = item.get("paragraphs", [])
    lines = []
    for index, paragraph in enumerate(paragraphs):
        lines.append(f"[{index}] {paragraph}{_format_marker_hint(item, index)}")
    return "\n".join(lines)


def _build_set_judge_block(judgment: dict[str, Any] | None) -> str:
    if not judgment:
        return "暂无 set-level 判断。"
    strongest = judgment.get("strongest_segment", {})
    weakest = judgment.get("weakest_segment", {})
    return (
        f"set_score={judgment.get('set_score', 5.0)}\n"
        f"structure_issue={judgment.get('structure_issue', '')}\n"
        f"strongest_segment=段落{strongest.get('paragraph_index', 0)}: {strongest.get('reason', '')}\n"
        f"weakest_segment=段落{weakest.get('paragraph_index', 0)}: {weakest.get('reason', '')}"
    )


def _build_prompt(
    item: dict[str, Any],
    profiles: dict[str, Any],
    judgment: dict[str, Any] | None,
) -> str:
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{performer}", item.get("performer", "未知演员"))
        .replace("{title}", item.get("title", "未命名段子"))
        .replace("{performer_profile_block}", _build_performer_profile_block(item.get("performer", ""), profiles))
        .replace("{set_judge_block}", _build_set_judge_block(judgment))
        .replace("{text}", _build_text_block(item))
    )


def _normalize_index(value: Any, paragraph_count: int) -> int:
    try:
        index = int(value)
    except Exception:
        return 0
    if paragraph_count <= 0:
        return 0
    return max(0, min(index, paragraph_count - 1))


def _normalize_segments(raw_segments: Any, paragraph_count: int) -> list[dict[str, Any]]:
    if not isinstance(raw_segments, list):
        return []

    segments: list[dict[str, Any]] = []
    for fallback_index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role", "build")).strip()
        if role not in ALLOWED_ROLES:
            role = "build"
        rewrite_priority = str(raw.get("rewrite_priority", "medium")).strip()
        if rewrite_priority not in ALLOWED_PRIORITIES:
            rewrite_priority = "medium"

        start = _normalize_index(raw.get("start_paragraph", fallback_index), paragraph_count)
        end = _normalize_index(raw.get("end_paragraph", start), paragraph_count)
        if end < start:
            end = start

        segments.append(
            {
                "segment_index": len(segments),
                "role": role,
                "start_paragraph": start,
                "end_paragraph": end,
                "summary": str(raw.get("summary", "")).strip(),
                "function": str(raw.get("function", "")).strip(),
                "rewrite_priority": rewrite_priority,
            }
        )

    if not segments:
        return []

    segments.sort(key=lambda item: item["start_paragraph"])

    normalized: list[dict[str, Any]] = []
    current_start = 0
    last_segment = len(segments) - 1
    for index, segment in enumerate(segments):
        start = current_start
        end = max(start, segment["end_paragraph"])
        if index < last_segment:
            next_start = max(start + 1, segments[index + 1]["start_paragraph"])
            end = min(end, next_start - 1)
        else:
            end = paragraph_count - 1 if paragraph_count else 0

        normalized.append(
            {
                **segment,
                "segment_index": index,
                "start_paragraph": start,
                "end_paragraph": end,
            }
        )
        current_start = end + 1

    if normalized and paragraph_count:
        normalized[-1]["end_paragraph"] = paragraph_count - 1

    merged: list[dict[str, Any]] = []
    for segment in normalized:
        if segment["start_paragraph"] > segment["end_paragraph"]:
            continue
        if merged and segment["start_paragraph"] <= merged[-1]["end_paragraph"]:
            segment["start_paragraph"] = merged[-1]["end_paragraph"] + 1
        if segment["start_paragraph"] > segment["end_paragraph"]:
            continue
        merged.append(segment)
    return merged


def _build_excerpt(paragraphs: list[str], start: int, end: int) -> str:
    parts = paragraphs[start : end + 1]
    excerpt = " ".join(parts).strip()
    if len(excerpt) > 120:
        excerpt = excerpt[:117].rstrip() + "..."
    return excerpt


def _default_result(item: dict[str, Any], reason: str) -> dict[str, Any]:
    paragraphs = item.get("paragraphs", [])
    paragraph_count = len(paragraphs)
    if paragraph_count == 0:
        segments = []
    else:
        segments = [
            {
                "segment_index": 0,
                "role": "opening",
                "start_paragraph": 0,
                "end_paragraph": paragraph_count - 1,
                "summary": "默认回退：未能成功拆段。",
                "function": "暂时将全文视为一个整体。",
                "rewrite_priority": "medium",
                "excerpt": _build_excerpt(paragraphs, 0, paragraph_count - 1),
                "reaction_markers": item.get("reaction_summary", {}),
            }
        ]

    return {
        "set_id": item["id"],
        "performer": item["performer"],
        "title": item["title"],
        "segmentation_note": reason,
        "segments": segments,
    }


def _reaction_counts_for_range(item: dict[str, Any], start: int, end: int) -> dict[str, int]:
    counts = {"laugh_like": 0, "big_laugh_like": 0, "applause_like": 0}
    for marker in item.get("markers", []):
        if not isinstance(marker, dict):
            continue
        paragraph_index = int(marker.get("paragraph_index", -1))
        if not (start <= paragraph_index <= end):
            continue
        name = str(marker.get("marker", ""))
        if "掌声" in name:
            counts["applause_like"] += 1
        elif "爆笑" in name or "欢呼" in name:
            counts["big_laugh_like"] += 1
        elif "笑" in name:
            counts["laugh_like"] += 1
    return counts


def _parse_result(item: dict[str, Any], raw: str) -> dict[str, Any]:
    paragraphs = item.get("paragraphs", [])
    paragraph_count = len(paragraphs)
    try:
        data = json.loads(_clean_json_payload(raw))
    except JSONDecodeError:
        data = _repair_segment_json(raw)
    segments = _normalize_segments(data.get("segments"), paragraph_count)
    if not segments:
        return _default_result(item, "粗拆段返回为空，已回退。")

    enriched = []
    for segment in segments:
        start = segment["start_paragraph"]
        end = segment["end_paragraph"]
        enriched.append(
            {
                **segment,
                "excerpt": _build_excerpt(paragraphs, start, end),
                "reaction_markers": _reaction_counts_for_range(item, start, end),
            }
        )

    return {
        "set_id": item["id"],
        "performer": item["performer"],
        "title": item["title"],
        "segmentation_note": str(data.get("segmentation_note", "")).strip(),
        "segments": enriched,
    }


def segment_set(
    item: dict[str, Any],
    profiles: dict[str, Any],
    judgments: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    prompt = _build_prompt(item, profiles, judgments.get(item["id"]))
    try:
        raw = humor_engine._chat(
            humor_engine._strategist_client(),
            os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2.0-pro-260215"),
            prompt,
            temperature=0.1,
            max_tokens=1400,
            role="strategist",
        )
        return _parse_result(item, raw)
    except Exception as exc:
        return _default_result(item, f"粗拆段失败，已回退：{exc}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--judgments", type=Path, default=DEFAULT_JUDGMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--profiles", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    standup_payload = _load_json(args.input)
    judgment_payload = _load_json(args.judgments)
    profiles = _load_actor_profiles(args.profiles)
    judgment_index = _build_judgment_index(judgment_payload)

    items = standup_payload.get("standup_sets", [])
    if args.limit and args.limit > 0:
        items = items[: args.limit]

    results = [segment_set(item, profiles, judgment_index) for item in items]

    out = {
        "version": "1.0",
        "description": "stand-up 粗拆段结果，供 weakest segment 改写循环使用",
        "source": str(args.input),
        "judgments": str(args.judgments) if args.judgments else None,
        "profiles": str(args.profiles) if args.profiles else None,
        "segmentations": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成：{args.output}")
    for item in results[:5]:
        print(
            f"- {item['performer']} / {item['title']} "
            f"segments={len(item['segments'])} "
            f"note={item['segmentation_note'][:40]}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
