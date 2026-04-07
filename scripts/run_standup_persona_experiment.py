"""
呼兰等 persona-first stand-up 长稿实验

目标：
1. 生成接近指定时长的 stand-up 初稿
2. 连续运行固定轮数（默认 5 轮）
3. 每轮都展示：
   - 当前正文
   - Judge 评价
   - 需要修改的意见
   - 战略师意见
   - 改写结果与是否采纳
4. 输出 JSON + Markdown，方便直接人工审阅
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from json import JSONDecodeError
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "data" / "standup_persona_experiment.json"
DEFAULT_OUTPUT_MD = PROJECT_ROOT / "data" / "standup_persona_experiment.md"
DEFAULT_PROFILES = PROJECT_ROOT / "data" / "standup_actor_profiles.example.json"
STRATEGIST_PROMPT_PATH = PROJECT_ROOT / "prompts" / "strategist" / "standup_revision.txt"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import humor_engine
import standup_blackboard
import standup_persona
from scripts import generate_standup_set, judge_standup_sets, rewrite_standup_set, segment_standup_sets


def _segment_outline(segmentation: dict[str, Any]) -> str:
    lines: list[str] = []
    for segment in segmentation.get("segments", []):
        lines.append(
            f"[{segment.get('segment_index')}] {segment.get('role')} "
            f"({segment.get('start_paragraph')}-{segment.get('end_paragraph')}): "
            f"{segment.get('summary', '')}"
        )
    return "\n".join(lines) or "（暂无）"


def _history_summary(rounds: list[dict[str, Any]]) -> str:
    if not rounds:
        return "（暂无历史轮次）"
    lines: list[str] = []
    for row in rounds[-3:]:
        lines.append(
            f"Round {row['round_index']}: score={row['judgment']['set_score']:.1f}, "
            f"persona={row['judgment']['persona_consistency']:.1f}, "
            f"issue={row['judgment']['structure_issue']}"
        )
    return "\n".join(lines)


def _joined_guidance(rounds: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rounds[-3:]:
        advice = row.get("strategist_advice") or {}
        guidance = str(advice.get("judge_guidance", "")).strip()
        if guidance:
            lines.append(f"Round {row['round_index']}：{guidance}")
    return "\n".join(lines) or "（暂无）"


def _all_fix_issues(advice: dict[str, Any] | None) -> list[str]:
    advice = advice or {}
    merged: list[str] = []
    for key in ["must_fix", "reality_issues", "persona_issues", "audience_issues", "logic_issues", "structure_issues"]:
        value = advice.get(key) or []
        if not isinstance(value, list):
            continue
        for item in value:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


def _clean_json_payload(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):].strip()
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


def _fallback_rewrite_tasks(
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
) -> list[dict[str, Any]]:
    weakest = judgment.get("weakest_segment", {}) or {}
    paragraph_index = int(weakest.get("paragraph_index", 0) or 0)
    weakest_reason = str(weakest.get("reason", "")).strip()
    structure_issue = str(judgment.get("structure_issue", "")).strip()

    start = paragraph_index
    end = paragraph_index
    role = "segment"
    for segment in segmentation.get("segments", []):
        seg_start = int(segment.get("start_paragraph", 0) or 0)
        seg_end = int(segment.get("end_paragraph", 0) or 0)
        if seg_start <= paragraph_index <= seg_end:
            start = seg_start
            end = seg_end
            role = str(segment.get("role", "segment")).strip() or "segment"
            break

    issue_type = "closer" if role == "closer" else "structure"
    tasks = [
        {
            "task_id": "T1",
            "priority": "high",
            "issue_type": issue_type,
            "target_paragraphs": list(range(start, end + 1)),
            "problem": weakest_reason or "当前最弱段没有形成有效收束和递进。",
            "rewrite_goal": "保留当前稿件里已经成立的观察点，把最弱段改得更像这个人会说的话，并让它更好承接前后文。",
            "acceptance_check": "改完后，这一段更符合人物口吻，信息更真实，且不再只是观点说明或重复吐槽。",
        }
    ]

    segments = segmentation.get("segments", [])
    build_segments = [seg for seg in segments if str(seg.get("role", "")).strip() == "build"]
    closer_segment = next((seg for seg in segments if str(seg.get("role", "")).strip() == "closer"), None)

    if any(keyword in structure_issue for keyword in ("中段", "重复", "递进")) and build_segments:
        candidate = next(
            (
                seg for seg in build_segments
                if int(seg.get("start_paragraph", 0) or 0) <= paragraph_index <= int(seg.get("end_paragraph", 0) or 0)
            ),
            build_segments[min(len(build_segments) - 1, 1)] if len(build_segments) > 1 else build_segments[0],
        )
        build_range = list(range(int(candidate.get("start_paragraph", 0) or 0), int(candidate.get("end_paragraph", 0) or 0) + 1))
        tasks.append(
            {
                "task_id": "T2",
                "priority": "high",
                "issue_type": "structure",
                "target_paragraphs": build_range,
                "problem": structure_issue or "中段推进没有越讲越真、越讲越大，存在重复感。",
                "rewrite_goal": "把中段改成更明确的递进，不只是重复同一种尴尬，而是让舞台局面继续升级。",
                "acceptance_check": "改完后，中段至少多出一层新的误会、身份升级或责任升级，观众能感觉到局面在变大。",
            }
        )

    if any(keyword in structure_issue for keyword in ("结尾", "收尾", "回收", "余味")) and closer_segment:
        closer_range = list(
            range(
                int(closer_segment.get("start_paragraph", 0) or 0),
                int(closer_segment.get("end_paragraph", 0) or 0) + 1,
            )
        )
        tasks.append(
            {
                "task_id": "T3",
                "priority": "high",
                "issue_type": "closer",
                "target_paragraphs": closer_range,
                "problem": structure_issue or "结尾没有把前面的局面重新照亮，收束偏平。",
                "rewrite_goal": "把结尾改成更像这个人会说出的轻反讽或回扣，让前面的核心前提在最后再亮一下。",
                "acceptance_check": "改完后，结尾不只是总结心情，而是明确回到这篇的中心前提或 running thread，形成余味。",
            }
        )

    return tasks[:8]


def _default_strategist_advice(
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
) -> dict[str, Any]:
    weakest = judgment.get("weakest_segment", {}) or {}
    weakest_reason = str(weakest.get("reason", "")).strip()
    structure_issue = str(judgment.get("structure_issue", "")).strip()
    issue = weakest_reason or structure_issue or "当前稿件仍有一个需要优先修订的关键薄弱段。"
    tasks = _fallback_rewrite_tasks(judgment, segmentation)
    return {
        "round_summary": "战略师本轮输出异常，已降级为增强版修订建议，优先保留已成立的前提与口吻，并自动补出中段和结尾的施工任务。",
        "must_keep": ["保留当前稿件里已经成立的观察角度和人物口吻。"],
        "must_fix": [
            issue,
            *([structure_issue] if structure_issue and structure_issue != issue else []),
        ],
        "reality_issues": [],
        "persona_issues": [],
        "audience_issues": [],
        "logic_issues": [],
        "structure_issues": [structure_issue or issue],
        "judge_guidance": "下轮评分时，不要因为结构完整就虚高给分；若最弱段仍然只是在解释观点、缺少人物口吻或不够真实，应继续扣分。",
        "rewrite_brief": "先修当前最弱段，再补中段递进和结尾回收，目标不是讲得更对，而是让舞台局面更持续、更有升级、更像这个人会说的话。",
        "rewrite_tasks": tasks,
        "closer_advice": "如果结尾偏平，就把结尾改成更像这个人会说出的轻反讽收束，而不是价值判断总结。",
        "persona_watchout": "不要为了补包袱把稿子写成标签化表演，也不要把人物背景整段说透。",
    }


def _normalize_strategist_advice(
    data: dict[str, Any],
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
) -> dict[str, Any]:
    fallback = _default_strategist_advice(judgment, segmentation)

    def _string(key: str, default: str = "") -> str:
        value = data.get(key, default)
        return str(value).strip()

    def _list(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list):
            return []
        cleaned: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                cleaned.append(text)
        return cleaned

    tasks = rewrite_standup_set._normalize_rewrite_tasks(data.get("rewrite_tasks", []))
    if not tasks:
        tasks = fallback["rewrite_tasks"]

    normalized = {
        "round_summary": _string("round_summary") or fallback["round_summary"],
        "must_keep": _list("must_keep") or fallback["must_keep"],
        "must_fix": _list("must_fix") or fallback["must_fix"],
        "reality_issues": _list("reality_issues"),
        "persona_issues": _list("persona_issues"),
        "audience_issues": _list("audience_issues"),
        "logic_issues": _list("logic_issues"),
        "structure_issues": _list("structure_issues") or fallback["structure_issues"],
        "judge_guidance": _string("judge_guidance") or fallback["judge_guidance"],
        "rewrite_brief": _string("rewrite_brief") or fallback["rewrite_brief"],
        "rewrite_tasks": tasks[:8],
        "closer_advice": _string("closer_advice") or fallback["closer_advice"],
        "persona_watchout": _string("persona_watchout") or fallback["persona_watchout"],
    }
    return normalized


def _repair_strategist_json(raw: str, judgment: dict[str, Any], segmentation: dict[str, Any]) -> dict[str, Any]:
    prompt = (
        "把下面这段战略师输出修复成严格合法的 JSON，只保留这些字段："
        "`round_summary`、`must_keep`、`must_fix`、`reality_issues`、`persona_issues`、`audience_issues`、"
        "`logic_issues`、`structure_issues`、`judge_guidance`、`rewrite_brief`、"
        "`rewrite_tasks`、`closer_advice`、`persona_watchout`。"
        "\n要求："
        "\n- 所有 issues 字段必须是字符串数组。"
        "\n- rewrite_tasks 必须是对象数组，每个对象只保留 task_id, priority, issue_type, target_paragraphs, problem, rewrite_goal, acceptance_check。"
        "\n- priority 只能是 high/medium/low。"
        "\n- issue_type 只能是 reality/persona/logic/structure/closer。"
        "\n- target_paragraphs 必须是整数数组。"
        "\n- 只输出 JSON，不要解释。"
        "\n\n原始输出：\n"
        f"{raw}\n\n"
        "如果原始内容残缺，就基于现有信息尽量补成最小可用的修订建议。"
    )
    fixed = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215"),
        prompt,
        temperature=0.0,
        max_tokens=1600,
        role="strategist",
    )
    try:
        data = json.loads(_clean_json_payload(fixed))
    except JSONDecodeError:
        return _default_strategist_advice(judgment, segmentation)
    return _normalize_strategist_advice(data, judgment, segmentation)


def _strategist_advice(
    item: dict[str, Any],
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
    profiles: dict[str, Any],
    previous_rounds: list[dict[str, Any]],
) -> dict[str, Any]:
    prompt = (
        STRATEGIST_PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{performer}", item.get("performer", "未知演员"))
        .replace("{topic}", item.get("topic", ""))
        .replace("{title}", item.get("title", "未命名"))
        .replace(
            "{performer_profile_block}",
            standup_persona.build_profile_block(
                item.get("performer", ""),
                profiles,
                fallback="（暂无）",
                detailed=True,
            ),
        )
        .replace("{text}", item.get("clean_text", ""))
        .replace("{set_score}", f"{float(judgment.get('set_score', 0.0)):.1f}")
        .replace("{persona_consistency}", f"{float(judgment.get('persona_consistency', 0.0)):.1f}")
        .replace("{structure_issue}", str(judgment.get("structure_issue", "")))
        .replace(
            "{strongest_segment}",
            f"段落{judgment.get('strongest_segment', {}).get('paragraph_index', 0)}："
            f"{judgment.get('strongest_segment', {}).get('reason', '')}",
        )
        .replace(
            "{weakest_segment}",
            f"段落{judgment.get('weakest_segment', {}).get('paragraph_index', 0)}："
            f"{judgment.get('weakest_segment', {}).get('reason', '')}",
        )
        .replace("{segment_outline}", _segment_outline(segmentation))
        .replace("{history_summary}", _history_summary(previous_rounds))
    )
    raw = humor_engine._chat(
        humor_engine._strategist_client(),
        os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215"),
        prompt,
        temperature=0.2,
        max_tokens=1200,
        role="strategist",
    )
    try:
        data = json.loads(_clean_json_payload(raw))
    except JSONDecodeError:
        return _repair_strategist_json(raw, judgment, segmentation)
    return _normalize_strategist_advice(data, judgment, segmentation)


def _round_row(
    round_index: int,
    item: dict[str, Any],
    judgment: dict[str, Any],
    segmentation: dict[str, Any],
    strategist_advice: dict[str, Any],
    rewrite_result: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "round_index": round_index,
        "item": item,
        "judgment": judgment,
        "segmentation": segmentation,
        "strategist_advice": strategist_advice,
        "rewrite_result": rewrite_result,
    }


def _accepted_item(current_item: dict[str, Any], rewrite_result: dict[str, Any] | None) -> dict[str, Any]:
    if not rewrite_result:
        return current_item
    if rewrite_result.get("accepted"):
        return rewrite_result.get("rewritten_item", current_item)
    return current_item


def _accepted_summary(rewrite_result: dict[str, Any] | None) -> str:
    if not rewrite_result:
        return "本轮未执行改写"
    accepted = bool(rewrite_result.get("accepted"))
    delta = rewrite_result.get("score_delta", 0.0)
    persona_delta = rewrite_result.get("persona_delta", 0.0)
    note = rewrite_result.get("rewrite_note", "")
    target = rewrite_result.get("target_segment") or {}
    steps = rewrite_result.get("rewrite_steps") or []
    return (
        f"{'采纳' if accepted else '未采纳'}；"
        f"目标段={target.get('role', 'unknown')} {target.get('start_paragraph', '?')}-{target.get('end_paragraph', '?')}；"
        f"delta={delta}；persona_delta={persona_delta}；"
        f"steps={len(steps)}；策略={note}"
    )


def _normalize_rewrite_result(
    current_judgment: dict[str, Any],
    raw_result: dict[str, Any],
    improvement_threshold: float,
) -> dict[str, Any]:
    if "accepted" in raw_result and "rewrite_steps" in raw_result:
        return {
            "target_segment": raw_result.get("target_segment", {}),
            "rewrite_tasks": raw_result.get("rewrite_tasks", []),
            "rewrite_note": raw_result.get("rewrite_note", ""),
            "rewritten_paragraphs": raw_result.get("rewritten_paragraphs", []),
            "rewritten_item": raw_result.get("rewritten_item"),
            "candidate_judgment": raw_result.get("judgment", {}),
            "candidate_segmentation": raw_result.get("segmentation", {}),
            "accepted": bool(raw_result.get("accepted", False)),
            "score_delta": round(float(raw_result.get("score_delta", 0.0)), 2),
            "persona_delta": round(float(raw_result.get("persona_delta", 0.0)), 2),
            "resolved_target": bool(raw_result.get("resolved_target", False)),
            "rewrite_steps": raw_result.get("rewrite_steps", []),
        }

    current_score = float(current_judgment.get("set_score", 0.0))
    new_score = float(raw_result.get("judgment", {}).get("set_score", 0.0))
    delta = round(new_score - current_score, 2)
    accepted = delta >= improvement_threshold
    return {
        "target_segment": raw_result.get("target_segment", {}),
        "rewrite_tasks": raw_result.get("rewrite_tasks", []),
        "rewrite_note": raw_result.get("rewrite_note", ""),
        "rewritten_paragraphs": raw_result.get("rewritten_paragraphs", []),
        "rewritten_item": raw_result.get("rewritten_item"),
        "candidate_judgment": raw_result.get("judgment", {}),
        "candidate_segmentation": raw_result.get("segmentation", {}),
        "accepted": accepted,
        "score_delta": delta,
        "persona_delta": round(
            float(raw_result.get("judgment", {}).get("persona_consistency", 0.0))
            - float(current_judgment.get("persona_consistency", 0.0)),
            2,
        ),
        "resolved_target": False,
        "rewrite_steps": [],
    }


def _write_markdown(report: dict[str, Any], path: Path) -> None:
    lines: list[str] = []
    cfg = report["configuration"]
    lines.extend(
        [
            "# Persona Stand-up Experiment",
            "",
            f"- 演员/人设：{cfg['performer']}",
            f"- 主题：{cfg['topic']}",
            f"- 时长目标：约 {cfg['duration_minutes']} 分钟",
            f"- 轮数：{cfg['rounds']}",
            f"- 每轮最多串行改写：{cfg.get('rewrite_max_steps', 1)} 步",
            f"- 模型：生成={cfg['writer_model']} / 评价={cfg['judge_model']} / 战略师={cfg['strategist_model']}",
            "",
        ]
    )

    blackboard = report.get("blackboard") or {}
    if blackboard:
        premise = blackboard.get("premise_sheet") or {}
        diagnostics = blackboard.get("diagnostics") or {}
        lines.extend(
            [
                "## Blackboard",
                "",
                f"- central_premise：{premise.get('central_premise', '')}",
                f"- running_thread：{premise.get('running_thread', '')}",
                f"- material_issue：{diagnostics.get('material_issue', None)}",
                f"- writing_issue：{diagnostics.get('writing_issue', None)}",
                "",
            ]
        )

    training_assets = report.get("training_assets") or {}
    if training_assets:
        lines.extend(
            [
                "## Training Assets",
                "",
                f"- planning_episodes：{len(training_assets.get('planning_episodes', []))}",
                f"- draft_judgments：{len(training_assets.get('draft_judgments', []))}",
                f"- revision_episodes：{len(training_assets.get('revision_episodes', []))}",
                f"- critique_quality_records：{len(training_assets.get('critique_quality_records', []))}",
                "",
            ]
        )

    for row in report["rounds"]:
        j = row["judgment"]
        s = row.get("strategist_advice") or {}
        rr = row["rewrite_result"]
        lines.extend(
            [
                f"## Round {row['round_index']}",
                "",
                f"- 标题：{row['item'].get('title', '')}",
                f"- set_score：{j.get('set_score', 0.0)}",
                f"- persona_consistency：{j.get('persona_consistency', 0.0)}",
                f"- 主要问题：{j.get('structure_issue', '')}",
                f"- 最强段：第 {j.get('strongest_segment', {}).get('paragraph_index', 0)} 段",
                f"- 最弱段：第 {j.get('weakest_segment', {}).get('paragraph_index', 0)} 段",
                "",
                "### 正文",
                "",
                row["item"].get("clean_text", ""),
                "",
                "### 需要修改的点",
                "",
                f"- Judge 判断：{j.get('weakest_segment', {}).get('reason', '')}",
            ]
        )
        for issue in _all_fix_issues(s):
            lines.append(f"- {issue}")
        lines.extend(
            [
                "",
                "### 战略师意见",
                "",
                f"- 本轮总结：{s.get('round_summary', '')}",
            ]
        )
        for keep in s.get("must_keep", []):
            lines.append(f"- 保留：{keep}")
        for label, key in [
            ("现实校验", "reality_issues"),
            ("人设校验", "persona_issues"),
            ("观众校验", "audience_issues"),
            ("逻辑校验", "logic_issues"),
            ("结构校验", "structure_issues"),
        ]:
            for item in s.get(key, []):
                lines.append(f"- {label}：{item}")
        lines.extend(
            [
                f"- 评分修正规则：{s.get('judge_guidance', '')}",
                f"- 修订 brief：{s.get('rewrite_brief', '')}",
                f"- 结尾建议：{s.get('closer_advice', '')}",
                f"- 人设提醒：{s.get('persona_watchout', '')}",
                "",
                "### 改写结果",
                "",
                f"- {_accepted_summary(rr)}",
            ]
        )
        tasks = s.get("rewrite_tasks", [])
        if tasks:
            lines.append("")
            lines.append("改写任务清单：")
            lines.append("")
            for task in tasks:
                lines.append(
                    f"- [{task.get('task_id', 'TASK')}] "
                    f"priority={task.get('priority', 'medium')} "
                    f"type={task.get('issue_type', 'structure')} "
                    f"paragraphs={task.get('target_paragraphs', [])} "
                    f"问题：{task.get('problem', '')} "
                    f"目标：{task.get('rewrite_goal', '')} "
                    f"验收：{task.get('acceptance_check', '')}"
                )
        if rr:
            steps = rr.get("rewrite_steps") or []
            if steps:
                lines.append("")
                lines.append("改写步骤：")
                lines.append("")
                for step in steps:
                    target = step.get("target_segment", {}) or {}
                    candidate = step.get("candidate_judgment", {}) or {}
                    lines.append(
                        f"- Step {step.get('step_index', '?')}："
                        f"{'采纳' if step.get('accepted') else '未采纳'}；"
                        f"{'已复评；' if step.get('confirmed') else ''}"
                        f"目标段={target.get('role', 'unknown')} {target.get('start_paragraph', '?')}-{target.get('end_paragraph', '?')}；"
                        f"score_delta={step.get('score_delta', 0.0)}；"
                        f"persona_delta={step.get('persona_delta', 0.0)}；"
                        f"resolved_target={step.get('resolved_target', False)}；"
                        f"策略={step.get('rewrite_note', '')}"
                    )
                    if candidate:
                        lines.append(
                            f"  候选结果：set_score={candidate.get('set_score', 0.0)}；"
                            f"persona={candidate.get('persona_consistency', 0.0)}；"
                            f"问题={candidate.get('structure_issue', '')}"
                        )
            rewritten = rr.get("rewritten_paragraphs") or []
            if rewritten:
                lines.append("")
                lines.append("改写后的目标段：")
                lines.append("")
                lines.append("\n\n".join(rewritten))
                lines.append("")

    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def _config_payload(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "performer": args.performer,
        "topic": args.topic,
        "target_audience": args.target_audience,
        "tone": args.tone,
        "paragraph_target": args.paragraph_target,
        "duration_minutes": args.duration_minutes,
        "persona": args.persona or "",
        "rounds": args.rounds,
        "rewrite_max_steps": args.rewrite_max_steps,
        "writer_model": os.getenv("DOUBAO_WRITER_MODEL", ""),
        "judge_model": os.getenv("DOUBAO_JUDGE_MODEL", ""),
        "strategist_model": os.getenv("DOUBAO_STRATEGIST_MODEL", ""),
    }


def _build_report(
    *,
    args: argparse.Namespace,
    generation_payload: dict[str, Any],
    rounds: list[dict[str, Any]],
    blackboard: dict[str, Any],
    status: str,
    phase: str,
) -> dict[str, Any]:
    config = _config_payload(args)
    training_assets = standup_blackboard.build_training_assets(
        config=config,
        generation_payload=generation_payload,
        rounds=rounds,
        blackboard=blackboard,
    )
    return {
        "version": "2.1",
        "description": "Persona-first stand-up 实验：生成、评价、修订意见、战略师意见与黑板/训练资产全量展示",
        "status": status,
        "phase": phase,
        "configuration": config,
        "generation": generation_payload,
        "blackboard": blackboard,
        "training_assets": training_assets,
        "rounds": rounds,
    }


def _write_partial(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_markdown(report, md_path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--performer", default="呼兰")
    parser.add_argument("--target-audience", default="都市年轻打工人")
    parser.add_argument("--tone", default="观察、自嘲、克制、文本强")
    parser.add_argument("--paragraph-target", type=int, default=10)
    parser.add_argument("--duration-minutes", type=int, default=5)
    parser.add_argument("--persona", default="")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--reuse-json", type=Path, default=None, help="复用已有生成结果或实验报告里的 generation")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--improvement-threshold", type=float, default=0.4)
    parser.add_argument("--rewrite-max-steps", type=int, default=3)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    args = parser.parse_args()

    profiles = generate_standup_set._load_actor_profiles(args.profiles)
    if args.reuse_json and args.reuse_json.exists():
        reuse_payload = json.loads(args.reuse_json.read_text(encoding="utf-8"))
        generation_payload = reuse_payload.get("generation") or reuse_payload
        item = deepcopy(generation_payload.get("item") or generation_payload.get("standup_sets", [])[0])
        print(
            f"[generation] reused title={item.get('title','')} paragraphs={len(item.get('paragraphs', []))}",
            flush=True,
        )
    else:
        print("[generation] start...", flush=True)
        item, generation_payload = generate_standup_set.generate_item(
            topic=args.topic,
            performer=args.performer,
            target_audience=args.target_audience,
            tone=args.tone,
            paragraph_target=args.paragraph_target,
            duration_minutes=args.duration_minutes,
            persona_name=args.persona or None,
            profiles=profiles,
        )
        print(
            f"[generation] done title={item.get('title','')} paragraphs={len(item.get('paragraphs', []))}",
            flush=True,
        )

    rounds: list[dict[str, Any]] = []
    current_item = deepcopy(item)
    blackboard = standup_blackboard.build_initial_blackboard(
        performer=args.performer,
        topic=args.topic,
        target_audience=args.target_audience,
        tone=args.tone,
        paragraph_target=args.paragraph_target,
        duration_minutes=args.duration_minutes,
        persona_name=args.persona or "",
        generation_payload=generation_payload,
        profiles=profiles,
    )

    for round_index in range(1, args.rounds + 1):
        print(f"[round {round_index}/{args.rounds}] judge...", flush=True)
        judgment = judge_standup_sets.judge_set(
            current_item,
            profiles,
            judge_guidance=_joined_guidance(rounds),
        )
        print(
            f"[round {round_index}/{args.rounds}] judge done "
            f"score={float(judgment.get('set_score', 0.0)):.1f} "
            f"persona={float(judgment.get('persona_consistency', 0.0)):.1f}",
            flush=True,
        )
        print(f"[round {round_index}/{args.rounds}] segment...", flush=True)
        segmentation = segment_standup_sets.segment_set(current_item, profiles, {current_item["id"]: judgment})
        pre_strategy_row = _round_row(round_index, current_item, judgment, segmentation, None, None)
        pre_strategy_report = _build_report(
            args=args,
            generation_payload=generation_payload,
            rounds=rounds + [pre_strategy_row],
            blackboard=blackboard,
            status="in_progress",
            phase=f"round_{round_index}_strategy_pending",
        )
        _write_partial(pre_strategy_report, args.output_json, args.output_md)
        print(f"[round {round_index}/{args.rounds}] strategist...", flush=True)
        advice = _strategist_advice(current_item, judgment, segmentation, profiles, rounds)
        print(f"[round {round_index}/{args.rounds}] strategist done", flush=True)
        preview_row = _round_row(round_index, current_item, judgment, segmentation, advice, None)
        preview_report = _build_report(
            args=args,
            generation_payload=generation_payload,
            rounds=rounds + [preview_row],
            blackboard=blackboard,
            status="in_progress",
            phase=f"round_{round_index}_rewrite_pending",
        )
        _write_partial(preview_report, args.output_json, args.output_md)
        rewrite_result = None
        if round_index < args.rounds:
            print(f"[round {round_index}/{args.rounds}] rewrite...", flush=True)
            raw_rewrite = rewrite_standup_set.rewrite_task_sequence(
                current_item,
                judgment,
                segmentation,
                profiles,
                version_index=round_index,
                strategist_guidance=(
                    f"战略师总结：{advice.get('round_summary', '')}\n"
                    f"必须保留：{'；'.join(advice.get('must_keep', [])) or '（暂无）'}\n"
                    f"必须修复：{'；'.join(_all_fix_issues(advice)) or '（暂无）'}\n"
                    f"修订 brief：{advice.get('rewrite_brief', '')}\n"
                    f"结尾建议：{advice.get('closer_advice', '')}\n"
                    f"人设提醒：{advice.get('persona_watchout', '')}"
                ),
                rewrite_tasks=advice.get("rewrite_tasks", []),
                judge_guidance=advice.get("judge_guidance", ""),
                must_keep=advice.get("must_keep", []),
                improvement_threshold=args.improvement_threshold,
                max_steps=args.rewrite_max_steps,
            )
            rewrite_result = _normalize_rewrite_result(
                judgment,
                raw_rewrite,
                improvement_threshold=args.improvement_threshold,
            )
            print(
                f"[round {round_index}/{args.rounds}] rewrite done "
                f"{_accepted_summary(rewrite_result)}",
                flush=True,
            )
        rounds.append(_round_row(round_index, current_item, judgment, segmentation, advice, rewrite_result))
        blackboard = standup_blackboard.apply_round_to_blackboard(
            blackboard,
            round_index=round_index,
            item=current_item,
            judgment=judgment,
            segmentation=segmentation,
            strategist_advice=advice,
            rewrite_result=rewrite_result,
        )
        current_item = _accepted_item(current_item, rewrite_result)

        partial_report = _build_report(
            args=args,
            generation_payload=generation_payload,
            rounds=rounds,
            blackboard=blackboard,
            status="in_progress" if round_index < args.rounds else "completed",
            phase=f"round_{round_index}_done",
        )
        _write_partial(partial_report, args.output_json, args.output_md)
        print(f"[round {round_index}/{args.rounds}] partial saved", flush=True)

    report = _build_report(
        args=args,
        generation_payload=generation_payload,
        rounds=rounds,
        blackboard=blackboard,
        status="completed",
        phase="completed",
    )

    _write_partial(report, args.output_json, args.output_md)

    print(f"已生成 JSON：{args.output_json}")
    print(f"已生成 Markdown：{args.output_md}")
    for row in rounds:
        print(
            f"- Round {row['round_index']}: "
            f"score={float(row['judgment'].get('set_score', 0.0)):.1f}, "
            f"persona={float(row['judgment'].get('persona_consistency', 0.0)):.1f}, "
            f"rewrite={_accepted_summary(row['rewrite_result'])}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
