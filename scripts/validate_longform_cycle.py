"""
长稿主循环小批量验证（JSON 版）

目标：
1. 批量生成 stand-up 初稿
2. 跑 set-level Judge + segmentation + weakest segment rewrite loop
3. 汇总成稿率、提升率、结构问题分布、Judge 一致性
4. 产出人工 review 用 JSON 报告
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "longform_validation.sample.json"
DEFAULT_PROFILES = PROJECT_ROOT / "data" / "standup_actor_profiles.example.json"
DEFAULT_TOPICS = [
    "租房和房东",
    "地铁通勤",
    "周会汇报",
    "合租生活",
    "相亲",
]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import generate_standup_set, judge_standup_sets, rewrite_standup_set, segment_standup_sets


def _load_topics(topics: list[str], topics_file: Path | None) -> list[str]:
    values = [topic.strip() for topic in topics if topic.strip()]
    if values:
        return values

    if topics_file and topics_file.exists():
        raw = topics_file.read_text(encoding="utf-8").strip()
        if not raw:
            return DEFAULT_TOPICS
        if topics_file.suffix.lower() == ".json":
            data = json.loads(raw)
            if isinstance(data, list):
                return [str(item).strip() for item in data if str(item).strip()]
        return [line.strip() for line in raw.splitlines() if line.strip()]

    return DEFAULT_TOPICS


def _normalize_issue(text: str) -> str:
    normalized = (text or "").strip()
    if not normalized:
        return "（空）"
    for token in ("（", "(", "，", "。", ";", "；", "\n"):
        if token in normalized:
            normalized = normalized.split(token, 1)[0].strip()
            break
    return normalized or "（空）"


def _safe_mean(values: list[float]) -> float:
    return round(statistics.mean(values), 2) if values else 0.0


def _build_run_summary(
    topic: str,
    item: dict[str, Any],
    initial_judgment: dict[str, Any],
    initial_segmentation: dict[str, Any],
    rewrite_result: dict[str, Any],
    improvement_threshold: float,
    usable_threshold: float,
    max_iterations: int,
) -> dict[str, Any]:
    initial_score = float(initial_judgment.get("set_score", 0.0))
    best_score = float(rewrite_result.get("best_score", 0.0))
    score_delta = round(best_score - initial_score, 2)
    versions = rewrite_result.get("versions", [])
    first_target = rewrite_standup_set._find_target_segment(initial_judgment, initial_segmentation) or {}
    paragraph_count = len(item.get("paragraphs", []))
    usable_initial_draft = (
        initial_score >= usable_threshold
        and 5 <= paragraph_count <= 8
        and "回退" not in str(initial_judgment.get("structure_issue", ""))
    )
    visible_improvement = score_delta >= improvement_threshold
    accepted_rewrites = [
        version
        for version in versions[1:]
        if isinstance(version.get("rewrite_action"), dict) and version["rewrite_action"].get("accepted")
    ]
    stop_after_first_rewrite = len(versions) == 2
    hit_max_iterations = len(versions) >= max_iterations + 1
    no_visible_improvement = not visible_improvement

    return {
        "topic": topic,
        "performer": item.get("performer", ""),
        "title": item.get("title", ""),
        "set_id": item.get("id", ""),
        "paragraph_count": paragraph_count,
        "usable_initial_draft": usable_initial_draft,
        "initial_score": round(initial_score, 2),
        "best_score": round(best_score, 2),
        "score_delta": score_delta,
        "visible_improvement": visible_improvement,
        "accepted_rewrite_count": len(accepted_rewrites),
        "stop_after_first_rewrite": stop_after_first_rewrite,
        "hit_max_iterations": hit_max_iterations,
        "no_visible_improvement": no_visible_improvement,
        "initial_structure_issue": initial_judgment.get("structure_issue", ""),
        "final_structure_issue": rewrite_result.get("final_structure_issue", ""),
        "initial_weakest_role": first_target.get("role", ""),
        "version_count": len(versions),
        "artifacts": {
            "item": item,
            "initial_judgment": initial_judgment,
            "initial_segmentation": initial_segmentation,
            "rewrite_result": rewrite_result,
        },
    }


def _run_single_cycle(
    topic: str,
    performer: str,
    target_audience: str,
    tone: str,
    paragraph_target: int,
    persona_name: str | None,
    profiles: dict[str, str],
    max_iterations: int,
    improvement_threshold: float,
    usable_threshold: float,
) -> dict[str, Any]:
    item, _ = generate_standup_set.generate_item(
        topic=topic,
        performer=performer,
        target_audience=target_audience,
        tone=tone,
        paragraph_target=paragraph_target,
        persona_name=persona_name,
        profiles=profiles,
    )
    initial_judgment = judge_standup_sets.judge_set(item, profiles)
    initial_segmentation = segment_standup_sets.segment_set(item, profiles, {item["id"]: initial_judgment})
    rewrite_result = rewrite_standup_set.rewrite_loop(
        item,
        initial_judgment,
        initial_segmentation,
        profiles,
        max_iterations=max_iterations,
        improvement_threshold=improvement_threshold,
    )
    return _build_run_summary(
        topic=topic,
        item=item,
        initial_judgment=initial_judgment,
        initial_segmentation=initial_segmentation,
        rewrite_result=rewrite_result,
        improvement_threshold=improvement_threshold,
        usable_threshold=usable_threshold,
        max_iterations=max_iterations,
    )


def _judge_consistency(
    items: list[dict[str, Any]],
    profiles: dict[str, str],
    sample_size: int,
) -> dict[str, Any]:
    samples = []
    for item in items[:sample_size]:
        first = judge_standup_sets.judge_set(item, profiles)
        second = judge_standup_sets.judge_set(item, profiles)
        delta = round(abs(float(first.get("set_score", 0.0)) - float(second.get("set_score", 0.0))), 2)
        samples.append(
            {
                "set_id": item.get("id", ""),
                "title": item.get("title", ""),
                "first_score": round(float(first.get("set_score", 0.0)), 2),
                "second_score": round(float(second.get("set_score", 0.0)), 2),
                "delta": delta,
            }
        )

    deltas = [sample["delta"] for sample in samples]
    return {
        "sample_size": len(samples),
        "average_delta": _safe_mean(deltas),
        "max_delta": round(max(deltas), 2) if deltas else 0.0,
        "samples": samples,
    }


def _build_summary(
    runs: list[dict[str, Any]],
    consistency: dict[str, Any],
    improvement_threshold: float,
) -> dict[str, Any]:
    initial_scores = [run["initial_score"] for run in runs]
    best_scores = [run["best_score"] for run in runs]
    deltas = [run["score_delta"] for run in runs]
    initial_issue_counter = Counter(_normalize_issue(run["initial_structure_issue"]) for run in runs)
    final_issue_counter = Counter(_normalize_issue(run["final_structure_issue"]) for run in runs)
    weakest_role_counter = Counter(run["initial_weakest_role"] or "（空）" for run in runs)

    usable_count = sum(1 for run in runs if run["usable_initial_draft"])
    visible_improvement_count = sum(1 for run in runs if run["visible_improvement"])
    stop_after_first_count = sum(1 for run in runs if run["stop_after_first_rewrite"])
    hit_max_count = sum(1 for run in runs if run["hit_max_iterations"])
    no_improvement_count = sum(1 for run in runs if run["no_visible_improvement"])

    summary = {
        "total_runs": len(runs),
        "usable_initial_draft_rate": round(usable_count / len(runs), 3) if runs else 0.0,
        "average_initial_score": _safe_mean(initial_scores),
        "average_best_score": _safe_mean(best_scores),
        "average_improvement": _safe_mean(deltas),
        "visible_improvement_rate": round(visible_improvement_count / len(runs), 3) if runs else 0.0,
        "stop_after_first_rewrite_rate": round(stop_after_first_count / len(runs), 3) if runs else 0.0,
        "hit_max_iterations_rate": round(hit_max_count / len(runs), 3) if runs else 0.0,
        "no_visible_improvement_rate": round(no_improvement_count / len(runs), 3) if runs else 0.0,
        "most_common_initial_structure_issues": initial_issue_counter.most_common(5),
        "most_common_final_structure_issues": final_issue_counter.most_common(5),
        "most_common_initial_weakest_roles": weakest_role_counter.most_common(5),
        "judge_consistency": consistency,
        "acceptance_checks": {
            "usable_draft_rate_gte_0_5": round(usable_count / len(runs), 3) >= 0.5 if runs else False,
            "avg_best_gt_avg_initial": _safe_mean(best_scores) > _safe_mean(initial_scores),
            "visible_improvement_rate_gte_0_3": round(visible_improvement_count / len(runs), 3) >= 0.3 if runs else False,
            "judge_noise_lte_threshold": consistency.get("max_delta", 0.0) <= improvement_threshold,
        },
    }
    return summary


def _build_report(
    topics: list[str],
    runs: list[dict[str, Any]],
    consistency: dict[str, Any],
    performer: str,
    target_audience: str,
    tone: str,
    paragraph_target: int,
    persona_name: str | None,
    max_iterations: int,
    improvement_threshold: float,
    usable_threshold: float,
) -> dict[str, Any]:
    summary = _build_summary(runs, consistency, improvement_threshold)
    return {
        "version": "1.0",
        "description": "长稿 Phase 1 小批量验证报告（JSON 版）",
        "configuration": {
            "topics": topics,
            "performer": performer,
            "target_audience": target_audience,
            "tone": tone,
            "paragraph_target": paragraph_target,
            "persona": persona_name or "",
            "max_iterations": max_iterations,
            "improvement_threshold": improvement_threshold,
            "usable_threshold": usable_threshold,
            "providers": {
                "writer_provider": "doubao",
                "judge_provider": os.getenv("JUDGE_PROVIDER", "doubao"),
                "rank_provider": os.getenv("RANK_PROVIDER", os.getenv("JUDGE_PROVIDER", "doubao")),
                "standup_set_provider": os.getenv("STANDUP_SET_PROVIDER", os.getenv("JUDGE_PROVIDER", "doubao")),
            },
        },
        "summary": summary,
        "runs": runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", action="append", default=[], help="可重复传入多个主题")
    parser.add_argument("--topics-file", type=Path, default=None, help="每行一个主题，或 JSON 数组")
    parser.add_argument("--performer", default="呼兰", help="目标文本风格演员/人设")
    parser.add_argument("--target-audience", default="都市年轻打工人")
    parser.add_argument("--tone", default="观察、自嘲、克制、文本强")
    parser.add_argument("--paragraph-target", type=int, default=6)
    parser.add_argument("--persona", default="", help="可选 persona 名称或 id")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--improvement-threshold", type=float, default=0.4)
    parser.add_argument("--usable-threshold", type=float, default=6.0)
    parser.add_argument("--consistency-samples", type=int, default=3)
    parser.add_argument("--quiet", action="store_true", help="关闭逐条进度打印")
    args = parser.parse_args()

    topics = _load_topics(args.topic, args.topics_file)
    profiles = generate_standup_set._load_actor_profiles(args.profiles)

    runs = []
    generated_items = []
    for index, topic in enumerate(topics, start=1):
        if not args.quiet:
            print(f"[{index}/{len(topics)}] 开始：{topic}")
        run = _run_single_cycle(
            topic=topic,
            performer=args.performer,
            target_audience=args.target_audience,
            tone=args.tone,
            paragraph_target=args.paragraph_target,
            persona_name=args.persona or None,
            profiles=profiles,
            max_iterations=args.max_iterations,
            improvement_threshold=args.improvement_threshold,
            usable_threshold=args.usable_threshold,
        )
        runs.append(run)
        generated_items.append(run["artifacts"]["item"])
        if not args.quiet:
            print(
                f"[{index}/{len(topics)}] 完成：{topic} "
                f"initial={run['initial_score']:.2f} best={run['best_score']:.2f} "
                f"delta={run['score_delta']:.2f}"
            )

    if not args.quiet:
        print(f"[consistency] 开始：抽样 {max(0, min(args.consistency_samples, len(generated_items)))} 篇做重复 Judge")
    consistency = _judge_consistency(
        generated_items,
        profiles,
        sample_size=max(0, min(args.consistency_samples, len(generated_items))),
    )
    report = _build_report(
        topics=topics,
        runs=runs,
        consistency=consistency,
        performer=args.performer,
        target_audience=args.target_audience,
        tone=args.tone,
        paragraph_target=args.paragraph_target,
        persona_name=args.persona or None,
        max_iterations=args.max_iterations,
        improvement_threshold=args.improvement_threshold,
        usable_threshold=args.usable_threshold,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"已生成：{args.output}")
    print(f"- total_runs={summary['total_runs']}")
    print(f"- usable_initial_draft_rate={summary['usable_initial_draft_rate']:.3f}")
    print(f"- average_initial_score={summary['average_initial_score']:.2f}")
    print(f"- average_best_score={summary['average_best_score']:.2f}")
    print(f"- visible_improvement_rate={summary['visible_improvement_rate']:.3f}")
    print(f"- judge_average_delta={summary['judge_consistency']['average_delta']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
