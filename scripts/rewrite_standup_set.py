"""
stand-up 最弱段局部改写循环

最小闭环：
1. 读取原始 standup set
2. 读取 set-level Judge + 粗拆段结果
3. 找到 weakest segment
4. 只改 weakest segment
5. 重跑 set-level Judge
6. 如有明显提升则保留；否则停止
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from json import JSONDecodeError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = PROJECT_ROOT / "data" / "standup_sets.json"
DEFAULT_JUDGMENTS = PROJECT_ROOT / "data" / "standup_set_judgments.json"
DEFAULT_SEGMENTS = PROJECT_ROOT / "data" / "standup_segments.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "standup_rewrites.json"
PROMPT_PATH = PROJECT_ROOT / "prompts" / "rewrite" / "standup_segment.txt"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import humor_engine
import standup_persona
from scripts import judge_standup_sets, segment_standup_sets


def _clean_json_payload(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def _repair_rewrite_json(raw: str) -> dict[str, Any]:
    prompt = (
        "把下面这段内容修复成严格合法的 JSON，只保留这两个字段："
        "`rewrite_note` 和 `rewritten_paragraphs`。"
        "`rewritten_paragraphs` 必须是字符串数组，不要解释。\n\n"
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


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_index(payload: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    rows = payload.get(key, [])
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("set_id"):
            index[str(row["set_id"])] = row
    return index


def _load_actor_profiles(path: Path | None) -> dict[str, Any]:
    return standup_persona.load_profiles(path)


def _build_performer_profile_block(performer: str, profiles: dict[str, Any]) -> str:
    profile = standup_persona.build_profile_block(
        performer,
        profiles,
        fallback="演员资料：暂无额外资料，请优先按文本逻辑强化。",
        detailed=False,
    )
    return f"演员资料（仅作辅助，优先做文本强化）：\n{profile}"


def _compact_profile_block(item: dict[str, Any], profiles: dict[str, Any]) -> str:
    snapshot = str(item.get("performer_profile_snapshot", "")).strip()
    if snapshot:
        return f"演员资料（精简版，只供局部修订参考）：\n{snapshot}"
    return _build_performer_profile_block(item.get("performer", ""), profiles)


def _find_target_segment(
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
) -> dict[str, Any] | None:
    weakest = judgment.get("weakest_segment", {})
    weakest_paragraph = int(weakest.get("paragraph_index", 0))
    segments = segmentation.get("segments", [])

    for segment in segments:
        start = int(segment.get("start_paragraph", 0))
        end = int(segment.get("end_paragraph", 0))
        if start <= weakest_paragraph <= end:
            return segment

    ranked = sorted(
        segments,
        key=lambda item: {"high": 0, "medium": 1, "low": 2}.get(str(item.get("rewrite_priority", "medium")), 1),
    )
    return ranked[0] if ranked else None


def _segment_outline(segmentation: dict[str, Any]) -> str:
    lines = []
    for segment in segmentation.get("segments", []):
        lines.append(
            f"[{segment.get('segment_index')}] {segment.get('role')} "
            f"({segment.get('start_paragraph')}-{segment.get('end_paragraph')}): "
            f"{segment.get('summary', '')}"
        )
    return "\n".join(lines) or "（暂无结构概览）"


def _context_block(paragraphs: list[str], start: int, end: int, before: bool) -> str:
    if before:
        slice_items = paragraphs[max(0, start - 3):start]
    else:
        slice_items = paragraphs[end + 1:end + 4]
    if not slice_items:
        return "（无）"
    return "\n\n".join(slice_items)


def _target_text(paragraphs: list[str], start: int, end: int) -> str:
    return "\n\n".join(paragraphs[start:end + 1]).strip()


def _normalize_rewrite_tasks(tasks: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    if not isinstance(tasks, list):
        return normalized
    for raw in tasks:
        if not isinstance(raw, dict):
            continue
        paragraphs = raw.get("target_paragraphs", [])
        if not isinstance(paragraphs, list):
            paragraphs = []
        clean_paragraphs = []
        for value in paragraphs:
            try:
                clean_paragraphs.append(int(value))
            except Exception:
                continue
        normalized.append(
            {
                "task_id": str(raw.get("task_id", "")).strip(),
                "priority": str(raw.get("priority", "medium")).strip() or "medium",
                "issue_type": str(raw.get("issue_type", "structure")).strip() or "structure",
                "target_paragraphs": clean_paragraphs,
                "problem": str(raw.get("problem", "")).strip(),
                "rewrite_goal": str(raw.get("rewrite_goal", "")).strip(),
                "acceptance_check": str(raw.get("acceptance_check", "")).strip(),
            }
        )
    return normalized


def _priority_rank(priority: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(str(priority).strip(), 1)


def _task_distance_to_paragraph(task: dict[str, Any], paragraph_index: int) -> int:
    paragraphs = task.get("target_paragraphs", [])
    if not paragraphs:
        return 999
    return min(abs(int(value) - paragraph_index) for value in paragraphs)


def _shrink_task_paragraphs(
    paragraphs: list[int],
    weakest_index: int,
    max_width: int = 3,
) -> list[int]:
    cleaned = sorted(dict.fromkeys(int(value) for value in paragraphs))
    if not cleaned:
        return []
    if len(cleaned) <= max_width:
        return cleaned

    best_window = cleaned[:max_width]
    best_score = (999, 999)
    for idx in range(0, len(cleaned) - max_width + 1):
        window = cleaned[idx:idx + max_width]
        span_center = sum(window) / len(window)
        score = (min(abs(value - weakest_index) for value in window), abs(span_center - weakest_index))
        if score < best_score:
            best_score = score
            best_window = window
    return best_window


def _select_focus_tasks(
    tasks: list[dict[str, Any]],
    judgment: dict[str, Any],
    max_scope_paragraphs: int = 3,
) -> list[dict[str, Any]]:
    if not tasks:
        return []

    weakest = judgment.get("weakest_segment", {}) or {}
    weakest_index = int(weakest.get("paragraph_index", 0) or 0)

    ranked = sorted(
        tasks,
        key=lambda item: (
            _priority_rank(item.get("priority", "medium")),
            _task_distance_to_paragraph(item, weakest_index),
            len(item.get("target_paragraphs", [])) or 999,
            str(item.get("task_id", "")),
        ),
    )
    primary = dict(ranked[0])
    primary["target_paragraphs"] = _shrink_task_paragraphs(
        primary.get("target_paragraphs", []),
        weakest_index=weakest_index,
        max_width=max_scope_paragraphs,
    )
    focused = [primary]

    used = set(primary.get("target_paragraphs", []))
    for candidate in ranked[1:]:
        paragraphs = _shrink_task_paragraphs(
            candidate.get("target_paragraphs", []),
            weakest_index=weakest_index,
            max_width=max_scope_paragraphs,
        )
        if not paragraphs:
            continue
        distance = min(abs(a - b) for a in used for b in paragraphs) if used else 999
        merged = sorted(set(used) | set(paragraphs))
        if distance <= 1 and len(merged) <= max_scope_paragraphs:
            copy_task = dict(candidate)
            copy_task["target_paragraphs"] = paragraphs
            focused.append(copy_task)
            used = set(merged)

    return focused


def _task_batches(
    tasks: list[dict[str, Any]],
    judgment: dict[str, Any],
    max_scope_paragraphs: int = 3,
    max_batches: int = 3,
) -> list[list[dict[str, Any]]]:
    normalized = _normalize_rewrite_tasks(tasks)
    if not normalized:
        return []

    weakest = judgment.get("weakest_segment", {}) or {}
    weakest_index = int(weakest.get("paragraph_index", 0) or 0)
    ranked = sorted(
        normalized,
        key=lambda item: (
            _priority_rank(item.get("priority", "medium")),
            _task_distance_to_paragraph(item, weakest_index),
            len(item.get("target_paragraphs", [])) or 999,
            str(item.get("task_id", "")),
        ),
    )

    batches: list[list[dict[str, Any]]] = []
    seen: set[tuple[Any, ...]] = set()
    for task in ranked:
        paragraphs = _shrink_task_paragraphs(
            task.get("target_paragraphs", []),
            weakest_index=weakest_index,
            max_width=max_scope_paragraphs,
        )
        if not paragraphs:
            continue
        copy_task = dict(task)
        copy_task["target_paragraphs"] = paragraphs
        key = (
            tuple(paragraphs),
            copy_task.get("issue_type", ""),
            copy_task.get("problem", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        batches.append([copy_task])
        if len(batches) >= max_batches:
            break
    return batches


def _rewrite_tasks_block(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "（暂无任务列表，按 weakest segment 修订）"
    lines: list[str] = []
    for task in tasks:
        lines.append(
            f"[{task.get('task_id') or 'TASK'}] priority={task.get('priority')} "
            f"type={task.get('issue_type')} paragraphs={task.get('target_paragraphs') or '[]'}"
        )
        if task.get("problem"):
            lines.append(f"- 问题：{task['problem']}")
        if task.get("rewrite_goal"):
            lines.append(f"- 目标：{task['rewrite_goal']}")
        if task.get("acceptance_check"):
            lines.append(f"- 验收：{task['acceptance_check']}")
    return "\n".join(lines)


def _must_keep_block(items: list[str] | None) -> str:
    cleaned = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not cleaned:
        return "（暂无）"
    return "\n".join(f"- {item}" for item in cleaned)


def _planning_guardrails_block(item: dict[str, Any]) -> str:
    plan = item.get("planning_note") or {}
    if not isinstance(plan, dict):
        return "（暂无）"

    lines: list[str] = []
    direct_fields = [
        ("讲述承诺", "narrative_contract"),
        ("幽默发动方式", "comedic_engine"),
        ("结尾目标", "closer_goal"),
    ]
    for label, key in direct_fields:
        value = str(plan.get(key, "")).strip()
        if value:
            lines.append(f"{label}：{value}")

    list_fields = [
        ("观众理解过滤规则", "audience_filters"),
        ("禁止浮在表面的写法", "forbidden_surfaces"),
        ("抱怨/碎碎念陷阱", "complaint_traps"),
        ("真实性检查", "reality_checks"),
        ("口吻边界", "voice_guardrails"),
    ]
    for label, key in list_fields:
        values = plan.get(key) or []
        if not isinstance(values, list):
            continue
        cleaned = [str(item).strip() for item in values if str(item).strip()]
        if cleaned:
            lines.append(f"{label}：\n" + "\n".join(f"- {item}" for item in cleaned))
    return "\n\n".join(lines) if lines else "（暂无）"


def _target_segment_from_tasks(
    tasks: list[dict[str, Any]],
    segmentation: dict[str, Any],
    judgment: dict[str, Any],
) -> dict[str, Any] | None:
    ranked_tasks = _select_focus_tasks(tasks, judgment)
    paragraph_indexes: list[int] = []
    for task in ranked_tasks:
        paragraph_indexes.extend(task.get("target_paragraphs", []))
    if not paragraph_indexes:
        return _find_target_segment(judgment, segmentation)

    start = min(paragraph_indexes)
    end = max(paragraph_indexes)
    segments = segmentation.get("segments", [])
    matched_roles = []
    for segment in segments:
        seg_start = int(segment.get("start_paragraph", 0))
        seg_end = int(segment.get("end_paragraph", 0))
        if seg_start <= end and seg_end >= start:
            matched_roles.append(str(segment.get("role", "build")))
    role = "+".join(dict.fromkeys(matched_roles)) if matched_roles else "custom"
    issue_types = ",".join(dict.fromkeys(task.get("issue_type", "") for task in ranked_tasks[:3] if task.get("issue_type")))
    return {
        "role": role,
        "summary": " / ".join(task.get("problem", "") for task in ranked_tasks[:2] if task.get("problem")),
        "function": "根据战略师任务列表做定向修订",
        "rewrite_priority": ranked_tasks[0].get("priority", "high"),
        "start_paragraph": start,
        "end_paragraph": end,
        "issue_types": issue_types,
    }


def _build_prompt(
    item: dict[str, Any],
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
    target_segment: dict[str, Any],
    profiles: dict[str, Any],
    strategist_guidance: str = "",
    rewrite_tasks: list[dict[str, Any]] | None = None,
    judge_guidance: str = "",
    must_keep: list[str] | None = None,
) -> str:
    paragraphs = item.get("paragraphs", [])
    start = int(target_segment.get("start_paragraph", 0))
    end = int(target_segment.get("end_paragraph", 0))
    strongest = judgment.get("strongest_segment", {})
    rewrite_tasks = rewrite_tasks or []

    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{performer}", item.get("performer", "未知演员"))
        .replace("{title}", item.get("title", "未命名段子"))
        .replace("{performer_profile_block}", _compact_profile_block(item, profiles))
        .replace("{planning_guardrails}", _planning_guardrails_block(item))
        .replace("{structure_issue}", judgment.get("structure_issue", "（暂无）"))
        .replace(
            "{persona_consistency_checks}",
            item.get("performer_profile_snapshot", "（暂无）") or "（暂无）",
        )
        .replace("{must_keep_block}", _must_keep_block(must_keep))
        .replace("{strategist_guidance}", strategist_guidance.strip() or "（暂无）")
        .replace("{rewrite_tasks_block}", _rewrite_tasks_block(rewrite_tasks))
        .replace("{judge_guidance}", judge_guidance.strip() or "（暂无）")
        .replace(
            "{strongest_segment}",
            f"段落{strongest.get('paragraph_index', 0)}：{strongest.get('reason', '（暂无）')}",
        )
        .replace("{segment_role}", str(target_segment.get("role", "build")))
        .replace("{segment_summary}", str(target_segment.get("summary", "")))
        .replace("{segment_function}", str(target_segment.get("function", "")))
        .replace("{rewrite_priority}", str(target_segment.get("rewrite_priority", "medium")))
        .replace("{weak_reason}", str(judgment.get("weakest_segment", {}).get("reason", "")))
        .replace("{segment_outline}", _segment_outline(segmentation))
        .replace("{previous_context}", _context_block(paragraphs, start, end, before=True))
        .replace("{target_text}", _target_text(paragraphs, start, end))
        .replace("{next_context}", _context_block(paragraphs, start, end, before=False))
    )


def _parse_rewrite(raw: str) -> tuple[str, list[str]]:
    try:
        data = json.loads(_clean_json_payload(raw))
    except JSONDecodeError:
        data = _repair_rewrite_json(raw)
    note = str(data.get("rewrite_note", "")).strip()
    paragraphs = data.get("rewritten_paragraphs", [])
    if not isinstance(paragraphs, list):
        paragraphs = []
    cleaned = [str(item).strip() for item in paragraphs if str(item).strip()]
    if not cleaned:
        raise ValueError("rewritten_paragraphs 为空")
    return note, cleaned[:4]


def _rebuild_item(base_item: dict[str, Any], new_paragraphs: list[str], version_index: int) -> dict[str, Any]:
    item = deepcopy(base_item)
    text = "\n\n".join(new_paragraphs).strip()
    item["id"] = f"{base_item['id']}__rewrite_{version_index}"
    item["full_text"] = text
    item["clean_text"] = text
    item["paragraphs"] = new_paragraphs
    item["markers"] = []
    item["reaction_summary"] = {"laugh_count": 0, "big_laugh_count": 0, "applause_count": 0}
    item["source_type"] = "rewritten_standup_set"
    return item


def _replace_segment(
    item: dict[str, Any],
    segment: dict[str, Any],
    rewritten_paragraphs: list[str],
    version_index: int,
) -> dict[str, Any]:
    paragraphs = item.get("paragraphs", [])
    start = int(segment.get("start_paragraph", 0))
    end = int(segment.get("end_paragraph", 0))
    new_paragraphs = paragraphs[:start] + rewritten_paragraphs + paragraphs[end + 1:]
    return _rebuild_item(item, new_paragraphs, version_index=version_index)


def _accept_candidate(
    current_judgment: dict[str, Any],
    candidate_judgment: dict[str, Any],
    focus_tasks: list[dict[str, Any]],
    improvement_threshold: float,
) -> dict[str, Any]:
    current_score = float(current_judgment.get("set_score", 0.0))
    new_score = float(candidate_judgment.get("set_score", 0.0))
    current_persona = float(current_judgment.get("persona_consistency", 0.0))
    new_persona = float(candidate_judgment.get("persona_consistency", 0.0))
    score_delta = round(new_score - current_score, 2)
    persona_delta = round(new_persona - current_persona, 2)

    target_paragraphs: set[int] = set()
    for task in focus_tasks:
        for value in task.get("target_paragraphs", []):
            try:
                target_paragraphs.add(int(value))
            except Exception:
                continue

    current_weakest = int((current_judgment.get("weakest_segment", {}) or {}).get("paragraph_index", 0) or 0)
    new_weakest = int((candidate_judgment.get("weakest_segment", {}) or {}).get("paragraph_index", 0) or 0)
    resolved_target = bool(target_paragraphs) and current_weakest in target_paragraphs and new_weakest not in target_paragraphs

    accepted = (
        score_delta >= improvement_threshold
        or (score_delta >= 0.0 and persona_delta >= 0.5)
        or (score_delta >= 0.0 and resolved_target)
    )
    return {
        "accepted": accepted,
        "score_delta": score_delta,
        "persona_delta": persona_delta,
        "resolved_target": resolved_target,
    }


def _needs_confirmation(decision: dict[str, Any], improvement_threshold: float) -> bool:
    return bool(
        decision.get("accepted")
        and float(decision.get("score_delta", 0.0)) < improvement_threshold
        and float(decision.get("persona_delta", 0.0)) < 0.5
    )


def _confirm_edge_acceptance(
    baseline_judgment: dict[str, Any],
    raw: dict[str, Any],
    profiles: dict[str, Any],
    improvement_threshold: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    confirmed_judgment, confirmed_segmentation = _judge_and_segment(raw.get("rewritten_item", {}), profiles)
    raw["judgment"] = confirmed_judgment
    raw["segmentation"] = confirmed_segmentation
    decision = _accept_candidate(
        baseline_judgment,
        confirmed_judgment,
        raw.get("rewrite_tasks", []),
        improvement_threshold=improvement_threshold,
    )
    decision["confirmed"] = True
    return raw, decision


def _judge_and_segment(
    item: dict[str, Any],
    profiles: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    judgment = judge_standup_sets.judge_set(item, profiles, quick_mode=True)
    segmentation = segment_standup_sets.segment_set(item, profiles, {item["id"]: judgment})
    return judgment, segmentation


def _write_progress_snapshot(
    path: Path | None,
    *,
    current_item: dict[str, Any],
    current_judgment: dict[str, Any],
    steps: list[dict[str, Any]],
    finished: bool,
) -> None:
    if not path:
        return
    payload = {
        "status": "completed" if finished else "in_progress",
        "current_score": current_judgment.get("set_score"),
        "current_persona": current_judgment.get("persona_consistency"),
        "current_structure_issue": current_judgment.get("structure_issue"),
        "current_title": current_item.get("title"),
        "current_text": "\n\n".join(current_item.get("paragraphs", [])).strip(),
        "steps": steps,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _segment_signature(segmentation: dict[str, Any], judgment: dict[str, Any]) -> str:
    target = _find_target_segment(judgment, segmentation)
    if not target:
        return "none"
    return (
        f"{target.get('role')}|{target.get('start_paragraph')}|{target.get('end_paragraph')}|"
        f"{judgment.get('weakest_segment', {}).get('paragraph_index', 0)}"
    )


def rewrite_iteration(
    current_item: dict[str, Any],
    current_judgment: dict[str, Any],
    current_segmentation: dict[str, Any],
    profiles: dict[str, Any],
    version_index: int,
    strategist_guidance: str = "",
    rewrite_tasks: list[dict[str, Any]] | None = None,
    judge_guidance: str = "",
    must_keep: list[str] | None = None,
) -> dict[str, Any]:
    normalized_tasks = _normalize_rewrite_tasks(rewrite_tasks)
    focus_tasks = _select_focus_tasks(normalized_tasks, current_judgment)
    target_segment = _target_segment_from_tasks(focus_tasks, current_segmentation, current_judgment)
    if not target_segment:
        raise ValueError("未找到可改写的目标 segment")

    prompt = _build_prompt(
        current_item,
        current_judgment,
        current_segmentation,
        target_segment,
        profiles,
        strategist_guidance=strategist_guidance,
        rewrite_tasks=focus_tasks,
        judge_guidance=judge_guidance,
        must_keep=must_keep,
    )
    raw = humor_engine._chat(
        humor_engine._writer_client(),
        os.getenv("DOUBAO_WRITER_MODEL", "doubao-seed-2-0-lite-260215"),
        prompt,
        temperature=0.75,
        max_tokens=1800,
        role="writer",
    )
    rewrite_note, rewritten_paragraphs = _parse_rewrite(raw)
    rewritten_item = _replace_segment(current_item, target_segment, rewritten_paragraphs, version_index=version_index)
    new_judgment, new_segmentation = _judge_and_segment(rewritten_item, profiles)

    return {
        "target_segment": target_segment,
        "rewrite_tasks": focus_tasks,
        "rewrite_note": rewrite_note,
        "rewritten_paragraphs": rewritten_paragraphs,
        "rewritten_item": rewritten_item,
        "judgment": new_judgment,
        "segmentation": new_segmentation,
    }


def rewrite_task_sequence(
    current_item: dict[str, Any],
    current_judgment: dict[str, Any],
    current_segmentation: dict[str, Any],
    profiles: dict[str, Any],
    version_index: int,
    strategist_guidance: str = "",
    rewrite_tasks: list[dict[str, Any]] | None = None,
    judge_guidance: str = "",
    must_keep: list[str] | None = None,
    improvement_threshold: float = 0.4,
    max_steps: int = 3,
    progress_path: Path | None = None,
) -> dict[str, Any]:
    task_batches = _task_batches(rewrite_tasks or [], current_judgment, max_batches=max_steps)
    if not task_batches:
        raw = rewrite_iteration(
            current_item,
            current_judgment,
            current_segmentation,
            profiles,
            version_index=version_index,
            strategist_guidance=strategist_guidance,
            rewrite_tasks=rewrite_tasks,
            judge_guidance=judge_guidance,
            must_keep=must_keep,
        )
        decision = _accept_candidate(
            current_judgment,
            raw.get("judgment", {}),
            raw.get("rewrite_tasks", []),
            improvement_threshold=improvement_threshold,
        )
        if _needs_confirmation(decision, improvement_threshold):
            raw, decision = _confirm_edge_acceptance(
                current_judgment,
                raw,
                profiles,
                improvement_threshold=improvement_threshold,
            )
        raw.update(decision)
        raw["rewrite_steps"] = [
            {
                "step_index": 1,
                "accepted": raw["accepted"],
                "score_delta": raw["score_delta"],
                "persona_delta": raw["persona_delta"],
                "resolved_target": raw["resolved_target"],
                "confirmed": bool(raw.get("confirmed", False)),
                "target_segment": raw.get("target_segment", {}),
                "rewrite_tasks": raw.get("rewrite_tasks", []),
                "rewrite_note": raw.get("rewrite_note", ""),
                "rewritten_paragraphs": raw.get("rewritten_paragraphs", []),
                "candidate_judgment": raw.get("judgment", {}),
            }
        ]
        _write_progress_snapshot(
            progress_path,
            current_item=raw.get("rewritten_item", current_item),
            current_judgment=raw.get("judgment", current_judgment),
            steps=raw["rewrite_steps"],
            finished=True,
        )
        return raw

    baseline_item = current_item
    baseline_judgment = current_judgment
    baseline_segmentation = current_segmentation
    accepted_any = False
    steps: list[dict[str, Any]] = []
    accepted_tasks: list[dict[str, Any]] = []
    last_raw: dict[str, Any] | None = None

    for step_index, batch in enumerate(task_batches, start=1):
        raw = rewrite_iteration(
            baseline_item,
            baseline_judgment,
            baseline_segmentation,
            profiles,
            version_index=version_index * 100 + step_index,
            strategist_guidance=strategist_guidance,
            rewrite_tasks=batch,
            judge_guidance=judge_guidance,
            must_keep=must_keep,
        )
        last_raw = raw
        decision = _accept_candidate(
            baseline_judgment,
            raw.get("judgment", {}),
            raw.get("rewrite_tasks", []),
            improvement_threshold=improvement_threshold,
        )
        if _needs_confirmation(decision, improvement_threshold):
            raw, decision = _confirm_edge_acceptance(
                baseline_judgment,
                raw,
                profiles,
                improvement_threshold=improvement_threshold,
            )
        step = {
            "step_index": step_index,
            "accepted": decision["accepted"],
            "score_delta": decision["score_delta"],
            "persona_delta": decision["persona_delta"],
            "resolved_target": decision["resolved_target"],
            "confirmed": bool(decision.get("confirmed", False)),
            "target_segment": raw.get("target_segment", {}),
            "rewrite_tasks": raw.get("rewrite_tasks", []),
            "rewrite_note": raw.get("rewrite_note", ""),
            "rewritten_paragraphs": raw.get("rewritten_paragraphs", []),
            "candidate_judgment": raw.get("judgment", {}),
        }
        steps.append(step)

        if decision["accepted"]:
            accepted_any = True
            accepted_tasks.extend(raw.get("rewrite_tasks", []))
            baseline_item = raw.get("rewritten_item", baseline_item)
            baseline_judgment = raw.get("judgment", baseline_judgment)
            baseline_segmentation = raw.get("segmentation", baseline_segmentation)

        _write_progress_snapshot(
            progress_path,
            current_item=baseline_item if accepted_any else raw.get("rewritten_item", baseline_item),
            current_judgment=baseline_judgment if accepted_any else raw.get("judgment", baseline_judgment),
            steps=steps,
            finished=False,
        )

    final_raw = last_raw or {}
    total_score_delta = round(float(baseline_judgment.get("set_score", 0.0)) - float(current_judgment.get("set_score", 0.0)), 2)
    total_persona_delta = round(float(baseline_judgment.get("persona_consistency", 0.0)) - float(current_judgment.get("persona_consistency", 0.0)), 2)
    accepted_count = sum(1 for step in steps if step.get("accepted"))
    total_count = len(steps)
    summary_note = f"串行改写 {accepted_count}/{total_count} 条任务"
    if accepted_tasks:
        ids = [task.get("task_id", "").strip() for task in accepted_tasks if task.get("task_id")]
        if ids:
            summary_note += f"，采纳任务：{', '.join(ids)}"

    result = {
        "target_segment": final_raw.get("target_segment", {}),
        "rewrite_tasks": accepted_tasks or final_raw.get("rewrite_tasks", []),
        "rewrite_note": summary_note,
        "rewritten_paragraphs": final_raw.get("rewritten_paragraphs", []),
        "rewritten_item": baseline_item if accepted_any else final_raw.get("rewritten_item"),
        "judgment": baseline_judgment if accepted_any else final_raw.get("judgment", current_judgment),
        "segmentation": baseline_segmentation if accepted_any else final_raw.get("segmentation", current_segmentation),
        "accepted": accepted_any,
        "score_delta": total_score_delta if accepted_any else round(float((final_raw.get("judgment", {}) or {}).get("set_score", 0.0)) - float(current_judgment.get("set_score", 0.0)), 2),
        "persona_delta": total_persona_delta if accepted_any else round(float((final_raw.get("judgment", {}) or {}).get("persona_consistency", 0.0)) - float(current_judgment.get("persona_consistency", 0.0)), 2),
        "resolved_target": any(bool(step.get("resolved_target")) for step in steps),
        "rewrite_steps": steps,
    }
    _write_progress_snapshot(
        progress_path,
        current_item=result.get("rewritten_item", current_item) or current_item,
        current_judgment=result.get("judgment", current_judgment) or current_judgment,
        steps=steps,
        finished=True,
    )
    return result


def rewrite_loop(
    item: dict[str, Any],
    initial_judgment: dict[str, Any],
    initial_segmentation: dict[str, Any],
    profiles: dict[str, Any],
    max_iterations: int = 3,
    improvement_threshold: float = 0.4,
    strategist_guidance: str = "",
) -> dict[str, Any]:
    versions: list[dict[str, Any]] = [
        {
            "version": 0,
            "set_id": item["id"],
            "set_score": initial_judgment.get("set_score", 5.0),
            "structure_issue": initial_judgment.get("structure_issue", ""),
            "weakest_segment": initial_judgment.get("weakest_segment", {}),
            "strongest_segment": initial_judgment.get("strongest_segment", {}),
            "segmentation_note": initial_segmentation.get("segmentation_note", ""),
            "segments": initial_segmentation.get("segments", []),
            "rewrite_action": None,
        }
    ]

    best_item = item
    best_judgment = initial_judgment
    best_segmentation = initial_segmentation
    current_item = item
    current_judgment = initial_judgment
    current_segmentation = initial_segmentation
    stagnant_signatures: list[str] = []

    for version_index in range(1, max_iterations + 1):
        result = rewrite_iteration(
            current_item,
            current_judgment,
            current_segmentation,
            profiles,
            version_index=version_index,
            strategist_guidance=strategist_guidance,
        )

        new_score = float(result["judgment"].get("set_score", 5.0))
        current_score = float(current_judgment.get("set_score", 5.0))
        improved = new_score - current_score
        accepted = improved >= improvement_threshold

        versions.append(
            {
                "version": version_index,
                "set_id": result["rewritten_item"]["id"],
                "set_score": new_score,
                "structure_issue": result["judgment"].get("structure_issue", ""),
                "weakest_segment": result["judgment"].get("weakest_segment", {}),
                "strongest_segment": result["judgment"].get("strongest_segment", {}),
                "segmentation_note": result["segmentation"].get("segmentation_note", ""),
                "segments": result["segmentation"].get("segments", []),
                "rewrite_action": {
                    "target_segment": result["target_segment"],
                    "rewrite_note": result["rewrite_note"],
                    "rewritten_paragraphs": result["rewritten_paragraphs"],
                    "accepted": accepted,
                    "score_delta": round(improved, 2),
                },
            }
        )

        signature = _segment_signature(result["segmentation"], result["judgment"])
        stagnant_signatures.append(signature)
        stagnant_signatures = stagnant_signatures[-2:]

        if accepted:
            current_item = result["rewritten_item"]
            current_judgment = result["judgment"]
            current_segmentation = result["segmentation"]
            if new_score > float(best_judgment.get("set_score", 5.0)):
                best_item = current_item
                best_judgment = current_judgment
                best_segmentation = current_segmentation
        else:
            break

        if len(stagnant_signatures) == 2 and stagnant_signatures[0] == stagnant_signatures[1]:
            break

    return {
        "original_set_id": item["id"],
        "best_set_id": best_item["id"],
        "best_score": best_judgment.get("set_score", 5.0),
        "final_structure_issue": best_judgment.get("structure_issue", ""),
        "versions": versions,
        "best_segments": best_segmentation.get("segments", []),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--judgments", type=Path, default=DEFAULT_JUDGMENTS)
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--profiles", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--set-id", type=str, default="")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--improvement-threshold", type=float, default=0.4)
    args = parser.parse_args()

    sets_payload = _load_json(args.input)
    judgment_index = _build_index(_load_json(args.judgments), "judgments")
    segmentation_index = _build_index(_load_json(args.segments), "segmentations")
    profiles = _load_actor_profiles(args.profiles)

    items = sets_payload.get("standup_sets", [])
    if args.set_id:
        items = [item for item in items if item.get("id") == args.set_id]
    elif args.limit and args.limit > 0:
        items = items[:args.limit]

    results = []
    for item in items:
        initial_judgment = judgment_index.get(item["id"])
        initial_segmentation = segmentation_index.get(item["id"])
        if not initial_judgment or not initial_segmentation:
            initial_judgment, initial_segmentation = _judge_and_segment(item, profiles)
        results.append(
            rewrite_loop(
                item,
                initial_judgment,
                initial_segmentation,
                profiles,
                max_iterations=args.max_iterations,
                improvement_threshold=args.improvement_threshold,
            )
        )

    output = {
        "version": "1.0",
        "description": "stand-up 最弱段局部改写结果",
        "source": str(args.input),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成：{args.output}")
    for item in results:
        print(
            f"- {item['original_set_id']} -> {item['best_set_id']} "
            f"best_score={float(item['best_score']):.1f} versions={len(item['versions'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
