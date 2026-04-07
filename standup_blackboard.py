"""
Stand-up v2.1 blackboard 与训练资产导出

目标：
- 为单篇 stand-up episode 提供共享 blackboard schema
- 将每轮 judge / strategist / rewrite 结果导出成可积累的训练资产
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import standup_persona


def _string(value: Any) -> str:
    return str(value).strip()


def _lines(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _default_judge_rubric(plan: dict[str, Any]) -> dict[str, Any]:
    premise_hint = _string(plan.get("central_premise", "")) or _string(plan.get("narrative_contract", ""))
    thread_hint = _string(plan.get("running_thread", "")) or _string(plan.get("theme_angle", ""))
    return {
        "dimensions": [
            "premise_strength",
            "running_thread_integrity",
            "escalation_density",
            "persona_fidelity",
            "audience_readability",
            "reality_logic",
            "closer_quality",
        ],
        "current_focus": [
            "不要把真实经历误判成 stand-up 成稿",
            "不要把结构工整误判成幽默成立",
            "要重点看 central premise、running thread、closer 是否工作",
        ],
        "premise_hint": premise_hint,
        "thread_hint": thread_hint,
    }


def _build_beat_outline(plan: dict[str, Any]) -> list[dict[str, Any]]:
    beats: list[dict[str, Any]] = []
    opening = _string(plan.get("opening_move", ""))
    if opening:
        beats.append({"beat_type": "opening", "content": opening})

    premise = _string(plan.get("central_premise", ""))
    if premise:
        beats.append({"beat_type": "premise", "content": premise})

    for idx, item in enumerate(_lines(plan.get("escalation_outline", [])), start=1):
        beats.append({"beat_type": f"escalation_{idx}", "content": item})

    closer = _string(plan.get("closer_goal", ""))
    if closer:
        beats.append({"beat_type": "closer", "content": closer})
    return beats


def build_initial_blackboard(
    *,
    performer: str,
    topic: str,
    target_audience: str,
    tone: str,
    paragraph_target: int,
    duration_minutes: int,
    persona_name: str,
    generation_payload: dict[str, Any],
    profiles: dict[str, Any],
) -> dict[str, Any]:
    item = deepcopy(generation_payload.get("item") or {})
    plan = deepcopy(generation_payload.get("plan") or item.get("planning_note") or {})
    episode_id = _string(item.get("id", "")) or "standup_episode"
    central_premise = _string(plan.get("central_premise", "")) or _string(plan.get("narrative_contract", ""))
    running_thread = _string(plan.get("running_thread", "")) or _string(plan.get("theme_angle", ""))
    performer_profile_hidden = standup_persona.build_profile_block(
        performer,
        profiles,
        fallback="",
        detailed=True,
    )
    performer_profile_public = _string(item.get("performer_profile_snapshot", ""))

    blackboard = {
        "schema_version": "2.1",
        "episode_id": episode_id,
        "status": "drafted",
        "meta": {
            "performer": performer,
            "topic": topic,
            "target_audience": target_audience,
            "tone": tone,
            "paragraph_target": paragraph_target,
            "duration_minutes": duration_minutes,
            "persona": persona_name,
            "title": _string(item.get("title", "")),
        },
        "persona_card_public": {
            "performer": performer,
            "snapshot": performer_profile_public,
            "speaking_object": _string(plan.get("speaking_object", "")),
            "voice_guardrails": _lines(plan.get("voice_guardrails", [])),
            "theme_angle": _string(plan.get("theme_angle", "")),
        },
        "persona_iceberg_hidden": {
            "hidden_profile": performer_profile_hidden,
            "hidden_iceberg": _lines(plan.get("hidden_iceberg", [])),
            "should_not_surface": _lines(plan.get("forbidden_surfaces", [])),
        },
        "audience_contract": {
            "target_audience": target_audience,
            "speaking_object": _string(plan.get("speaking_object", "")),
            "audience_filters": _lines(plan.get("audience_filters", [])),
            "complaint_traps": _lines(plan.get("complaint_traps", [])),
            "confusion_risks": _lines(plan.get("audience_filters", [])),
        },
        "premise_sheet": {
            "title_hint": _string(plan.get("title_hint", "")),
            "theme_angle": _string(plan.get("theme_angle", "")),
            "opening_move": _string(plan.get("opening_move", "")),
            "narrative_contract": _string(plan.get("narrative_contract", "")),
            "comedic_engine": _string(plan.get("comedic_engine", "")),
            "central_premise": central_premise,
            "running_thread": running_thread,
            "closer_goal": _string(plan.get("closer_goal", "")),
            "callback_seeds": [],
        },
        "material_bank": {
            "reality_checks": _lines(plan.get("reality_checks", [])),
            "usable_observations": [],
            "usable_exaggerations": [],
            "risky_details": _lines(plan.get("audience_filters", [])),
            "forbidden_surfaces": _lines(plan.get("forbidden_surfaces", [])),
            "comedic_engine": _string(plan.get("comedic_engine", "")),
        },
        "beat_outline": _build_beat_outline(plan),
        "draft": {
            "title": _string(item.get("title", "")),
            "paragraphs": deepcopy(item.get("paragraphs", [])),
            "text": _string(item.get("clean_text", "")),
        },
        "judge_rubric": _default_judge_rubric(plan),
        "revision_queue": [],
        "revision_log": [],
        "round_snapshots": [],
        "learning_takeaways": [],
        "diagnostics": {
            "material_issue": None,
            "writing_issue": None,
            "top_failure_modes": [],
        },
    }
    return blackboard


def _infer_issue_split(
    judgment: dict[str, Any],
    advice: dict[str, Any] | None,
) -> dict[str, Any]:
    advice = advice or {}
    material_evidence: list[str] = []
    writing_evidence: list[str] = []

    for item in _lines(advice.get("reality_issues", [])):
        material_evidence.append(item)
    for item in _lines(advice.get("audience_issues", [])):
        material_evidence.append(item)

    for item in _lines(advice.get("logic_issues", [])):
        if any(keyword in item for keyword in ["设定", "细节", "真实", "关系", "不认识", "专有", "背景"]):
            material_evidence.append(item)
        else:
            writing_evidence.append(item)

    for item in _lines(advice.get("persona_issues", [])):
        if any(keyword in item for keyword in ["不像这个人", "这个人不会", "不该说", "人设素材"]):
            material_evidence.append(item)
        else:
            writing_evidence.append(item)

    for item in _lines(advice.get("structure_issues", [])):
        writing_evidence.append(item)

    for item in _lines(advice.get("must_fix", [])):
        if any(keyword in item for keyword in ["抱怨", "碎碎念", "说透", "结尾", "回忆录", "递进", "回收", "closer"]):
            writing_evidence.append(item)

    material_issue = len(material_evidence) > 0
    writing_issue = len(writing_evidence) > 0 or not material_issue

    top_failure_modes: list[str] = []
    if _string(judgment.get("structure_issue", "")):
        top_failure_modes.append(_string(judgment.get("structure_issue", "")))
    top_failure_modes.extend(material_evidence[:2])
    top_failure_modes.extend(writing_evidence[:2])

    if material_issue and writing_issue:
        diagnosis = "mixed"
    elif material_issue:
        diagnosis = "material"
    else:
        diagnosis = "writing"

    return {
        "material_issue": material_issue,
        "writing_issue": writing_issue,
        "diagnosis": diagnosis,
        "material_evidence": material_evidence,
        "writing_evidence": writing_evidence,
        "top_failure_modes": top_failure_modes[:5],
    }


def _build_learning_takeaway(
    round_index: int,
    judgment: dict[str, Any],
    advice: dict[str, Any] | None,
    issue_split: dict[str, Any],
) -> str:
    advice = advice or {}
    summary = _string(advice.get("round_summary", ""))
    structure_issue = _string(judgment.get("structure_issue", ""))
    diagnosis = _string(issue_split.get("diagnosis", "writing"))

    if summary and structure_issue:
        return f"Round {round_index}: {diagnosis} issue; {summary} 主要卡点是：{structure_issue}"
    if structure_issue:
        return f"Round {round_index}: {diagnosis} issue; 主要卡点是：{structure_issue}"
    return f"Round {round_index}: {diagnosis} issue"


def apply_round_to_blackboard(
    blackboard: dict[str, Any],
    *,
    round_index: int,
    item: dict[str, Any],
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
    strategist_advice: dict[str, Any] | None,
    rewrite_result: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = deepcopy(blackboard)
    issue_split = _infer_issue_split(judgment, strategist_advice)
    draft_item = item
    if rewrite_result and rewrite_result.get("accepted") and rewrite_result.get("rewritten_item"):
        draft_item = rewrite_result.get("rewritten_item") or item

    updated["draft"] = {
        "title": _string(draft_item.get("title", "")),
        "paragraphs": deepcopy(draft_item.get("paragraphs", [])),
        "text": _string(draft_item.get("clean_text", "")),
    }
    updated["judge_rubric"]["latest_guidance"] = _string((strategist_advice or {}).get("judge_guidance", ""))
    updated["revision_queue"] = deepcopy((strategist_advice or {}).get("rewrite_tasks", []))
    updated["diagnostics"] = {
        "material_issue": issue_split["material_issue"],
        "writing_issue": issue_split["writing_issue"],
        "top_failure_modes": issue_split["top_failure_modes"],
    }

    snapshot = {
        "round_index": round_index,
        "title": _string(item.get("title", "")),
        "set_score": float(judgment.get("set_score", 0.0)),
        "persona_consistency": float(judgment.get("persona_consistency", 0.0)),
        "structure_issue": _string(judgment.get("structure_issue", "")),
        "strongest_paragraph": int((judgment.get("strongest_segment") or {}).get("paragraph_index", 0) or 0),
        "weakest_paragraph": int((judgment.get("weakest_segment") or {}).get("paragraph_index", 0) or 0),
        "segment_count": len((segmentation or {}).get("segments", [])),
        "issue_split": issue_split,
    }
    updated["round_snapshots"].append(snapshot)

    if strategist_advice:
        updated["learning_takeaways"].append(
            _build_learning_takeaway(round_index, judgment, strategist_advice, issue_split)
        )

    if rewrite_result:
        steps = rewrite_result.get("rewrite_steps") or []
        if steps:
            for step in steps:
                candidate = step.get("candidate_judgment") or {}
                updated["revision_log"].append(
                    {
                        "round_index": round_index,
                        "step_index": int(step.get("step_index", 0) or 0),
                        "task_ids": [task.get("task_id", "") for task in step.get("rewrite_tasks", [])],
                        "issue_types": [task.get("issue_type", "") for task in step.get("rewrite_tasks", [])],
                        "before_score": float(step.get("before_judgment", {}).get("set_score", judgment.get("set_score", 0.0))),
                        "after_score": float(candidate.get("set_score", 0.0)),
                        "before_persona": float(
                            step.get("before_judgment", {}).get(
                                "persona_consistency",
                                judgment.get("persona_consistency", 0.0),
                            )
                        ),
                        "after_persona": float(candidate.get("persona_consistency", 0.0)),
                        "accepted": bool(step.get("accepted", False)),
                        "resolved_target": bool(step.get("resolved_target", False)),
                        "rewrite_note": _string(step.get("rewrite_note", "")),
                    }
                )
        else:
            candidate = rewrite_result.get("candidate_judgment") or {}
            updated["revision_log"].append(
                {
                    "round_index": round_index,
                    "step_index": 1,
                    "task_ids": [task.get("task_id", "") for task in rewrite_result.get("rewrite_tasks", [])],
                    "issue_types": [task.get("issue_type", "") for task in rewrite_result.get("rewrite_tasks", [])],
                    "before_score": float(judgment.get("set_score", 0.0)),
                    "after_score": float(candidate.get("set_score", 0.0)),
                    "before_persona": float(judgment.get("persona_consistency", 0.0)),
                    "after_persona": float(candidate.get("persona_consistency", 0.0)),
                    "accepted": bool(rewrite_result.get("accepted", False)),
                    "resolved_target": bool(rewrite_result.get("resolved_target", False)),
                    "rewrite_note": _string(rewrite_result.get("rewrite_note", "")),
                }
            )

    updated["status"] = "completed" if rewrite_result is None else "iterating"
    return updated


def build_training_assets(
    *,
    config: dict[str, Any],
    generation_payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    blackboard: dict[str, Any],
) -> dict[str, Any]:
    item = generation_payload.get("item") or {}
    episode_id = _string(item.get("id", "")) or _string(blackboard.get("episode_id", "standup_episode"))
    plan = generation_payload.get("plan") or item.get("planning_note") or {}

    planning_episodes = [
        {
            "episode_id": episode_id,
            "performer": _string(config.get("performer", "")),
            "topic": _string(config.get("topic", "")),
            "title": _string(item.get("title", "")),
            "central_premise": _string(plan.get("central_premise", "")),
            "running_thread": _string(plan.get("running_thread", "")),
            "theme_angle": _string(plan.get("theme_angle", "")),
            "speaking_object": _string(plan.get("speaking_object", "")),
            "closer_goal": _string(plan.get("closer_goal", "")),
            "best_score": max((float(row.get("judgment", {}).get("set_score", 0.0)) for row in rounds), default=0.0),
            "best_persona": max(
                (float(row.get("judgment", {}).get("persona_consistency", 0.0)) for row in rounds),
                default=0.0,
            ),
        }
    ]

    draft_judgments: list[dict[str, Any]] = []
    critique_quality_records: list[dict[str, Any]] = []
    for row in rounds:
        judgment = row.get("judgment", {}) or {}
        advice = row.get("strategist_advice") or {}
        issue_split = _infer_issue_split(judgment, advice)
        draft_judgments.append(
            {
                "episode_id": episode_id,
                "round_index": int(row.get("round_index", 0) or 0),
                "set_score": float(judgment.get("set_score", 0.0)),
                "persona_consistency": float(judgment.get("persona_consistency", 0.0)),
                "structure_issue": _string(judgment.get("structure_issue", "")),
                "strongest_paragraph": int((judgment.get("strongest_segment") or {}).get("paragraph_index", 0) or 0),
                "weakest_paragraph": int((judgment.get("weakest_segment") or {}).get("paragraph_index", 0) or 0),
                "material_issue": issue_split["material_issue"],
                "writing_issue": issue_split["writing_issue"],
                "top_failure_modes": issue_split["top_failure_modes"],
            }
        )
        critique_quality_records.append(
            {
                "episode_id": episode_id,
                "round_index": int(row.get("round_index", 0) or 0),
                "judge_issue": _string(judgment.get("structure_issue", "")),
                "judge_guidance": _string(advice.get("judge_guidance", "")),
                "rewrite_brief": _string(advice.get("rewrite_brief", "")),
                "rewrite_tasks_count": len(advice.get("rewrite_tasks", []) or []),
                "must_fix_count": len(_lines(advice.get("must_fix", []))),
                "accepted_after_round": bool((row.get("rewrite_result") or {}).get("accepted", False)),
            }
        )

    revision_episodes: list[dict[str, Any]] = []
    for row in rounds:
        rr = row.get("rewrite_result") or {}
        if not rr:
            continue
        steps = rr.get("rewrite_steps") or []
        if steps:
            for step in steps:
                candidate = step.get("candidate_judgment") or {}
                revision_episodes.append(
                    {
                        "episode_id": episode_id,
                        "round_index": int(row.get("round_index", 0) or 0),
                        "step_index": int(step.get("step_index", 0) or 0),
                        "task_ids": [task.get("task_id", "") for task in step.get("rewrite_tasks", [])],
                        "issue_types": [task.get("issue_type", "") for task in step.get("rewrite_tasks", [])],
                        "before_score": float(step.get("before_judgment", {}).get("set_score", 0.0)),
                        "after_score": float(candidate.get("set_score", 0.0)),
                        "before_persona": float(step.get("before_judgment", {}).get("persona_consistency", 0.0)),
                        "after_persona": float(candidate.get("persona_consistency", 0.0)),
                        "accepted": bool(step.get("accepted", False)),
                        "resolved_target": bool(step.get("resolved_target", False)),
                    }
                )
        else:
            candidate = rr.get("candidate_judgment") or {}
            revision_episodes.append(
                {
                    "episode_id": episode_id,
                    "round_index": int(row.get("round_index", 0) or 0),
                    "step_index": 1,
                    "task_ids": [task.get("task_id", "") for task in rr.get("rewrite_tasks", [])],
                    "issue_types": [task.get("issue_type", "") for task in rr.get("rewrite_tasks", [])],
                    "before_score": float(row.get("judgment", {}).get("set_score", 0.0)),
                    "after_score": float(candidate.get("set_score", 0.0)),
                    "before_persona": float(row.get("judgment", {}).get("persona_consistency", 0.0)),
                    "after_persona": float(candidate.get("persona_consistency", 0.0)),
                    "accepted": bool(rr.get("accepted", False)),
                    "resolved_target": bool(rr.get("resolved_target", False)),
                }
            )

    return {
        "schema_version": "2.1",
        "episode_id": episode_id,
        "planning_episodes": planning_episodes,
        "draft_judgments": draft_judgments,
        "revision_episodes": revision_episodes,
        "critique_quality_records": critique_quality_records,
        "learning_takeaways": deepcopy(blackboard.get("learning_takeaways", [])),
    }
