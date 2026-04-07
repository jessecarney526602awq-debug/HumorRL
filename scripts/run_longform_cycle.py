"""
长稿主闭环 orchestration（JSON 版）

流程：
1. 生成 stand-up 初稿
2. 跑 set-level Judge
3. 跑 coarse segmentation
4. 跑 weakest segment 局部改写循环
5. 输出完整 JSON 版本历史
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "longform_cycle.sample.json"
DEFAULT_PROFILES = PROJECT_ROOT / "data" / "standup_actor_profiles.example.json"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import generate_standup_set, judge_standup_sets, rewrite_standup_set, segment_standup_sets


def _build_cycle_output(
    generation_payload: dict[str, Any],
    initial_judgment: dict[str, Any],
    initial_segmentation: dict[str, Any],
    rewrite_result: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": "1.0",
        "description": "长稿主闭环 JSON 版结果：generate -> judge -> segment -> rewrite -> judge",
        "generation": generation_payload,
        "initial_judgment": initial_judgment,
        "initial_segmentation": initial_segmentation,
        "rewrite_loop": rewrite_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True, help="stand-up 主题")
    parser.add_argument("--performer", default="呼兰", help="目标文本风格演员/人设")
    parser.add_argument("--target-audience", default="都市年轻打工人")
    parser.add_argument("--tone", default="观察、自嘲、克制、文本强")
    parser.add_argument("--paragraph-target", type=int, default=6)
    parser.add_argument("--persona", default="", help="可选 persona 名称或 id")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-iterations", type=int, default=3)
    parser.add_argument("--improvement-threshold", type=float, default=0.4)
    args = parser.parse_args()

    profiles = generate_standup_set._load_actor_profiles(args.profiles)

    item, generation_payload = generate_standup_set.generate_item(
        topic=args.topic,
        performer=args.performer,
        target_audience=args.target_audience,
        tone=args.tone,
        paragraph_target=args.paragraph_target,
        persona_name=args.persona or None,
        profiles=profiles,
    )

    initial_judgment = judge_standup_sets.judge_set(item, profiles)
    initial_segmentation = segment_standup_sets.segment_set(item, profiles, {item["id"]: initial_judgment})
    rewrite_result = rewrite_standup_set.rewrite_loop(
        item,
        initial_judgment,
        initial_segmentation,
        profiles,
        max_iterations=args.max_iterations,
        improvement_threshold=args.improvement_threshold,
    )

    payload = _build_cycle_output(
        generation_payload=generation_payload,
        initial_judgment=initial_judgment,
        initial_segmentation=initial_segmentation,
        rewrite_result=rewrite_result,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已生成：{args.output}")
    print(f"- title={item['title']}")
    print(f"- initial_score={float(initial_judgment.get('set_score', 0.0)):.1f}")
    print(f"- best_score={float(rewrite_result.get('best_score', 0.0)):.1f}")
    print(f"- versions={len(rewrite_result.get('versions', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
