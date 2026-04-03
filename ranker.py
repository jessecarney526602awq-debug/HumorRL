"""
HumorRL — Group Comparison 排序器

训练轨主奖励：
- 一组候选 + 两个锚点一起比较
- 输出严格排序、funny/not_funny 和 rank_score
- 仅对 Top2 + Bottom1 做 pointwise 诊断，保留给 Strategist
"""

from __future__ import annotations

import json
import os
import random
import re
from typing import Optional

import db
import humor_engine
import judge_router
from contract import (
    CONTENT_TYPE_LABELS,
    ContentType,
    GroupRankResult,
    JokeRecord,
    RankPosition,
)


RANK_PROMPT_PATH = "prompts/evaluate/rank_group.txt"
_RANDOM = random.Random(20260402)


def _strip_wrappers(raw: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return cleaned.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def select_anchors(content_type: ContentType, db_path: str = db.DB_PATH) -> list[dict]:
    calibration = db.load_calibration_set()
    same_type = [item for item in calibration if item["content_type"] == content_type.value]
    pool = same_type or calibration
    funny_pool = [item for item in pool if item["label"] == "funny"]
    bad_pool = [item for item in pool if item["label"] == "not_funny"]
    if not funny_pool or not bad_pool:
        raise ValueError("校准集缺少 funny / not_funny 锚点")
    return [_RANDOM.choice(funny_pool), _RANDOM.choice(bad_pool)]


def rank_score(position: int, total: int, is_funny: bool) -> float:
    if total <= 1:
        base = 10.0 if is_funny else 3.0
        return round(base, 2)
    score = 10.0 * (total - position) / (total - 1)
    if not is_funny:
        score = min(score, 3.0)
    return round(score, 2)


def _build_items_block(texts: list[str], anchors: list[dict]) -> str:
    lines = []
    for idx, text in enumerate(texts, start=1):
        lines.append(f"[C{idx}] {text}")
    for anchor in anchors:
        label = "好锚点" if anchor["label"] == "funny" else "坏锚点"
        lines.append(f"[A{anchor['id']}] {anchor['text']}  # {label}")
    return "\n".join(lines)


def _safe_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "funny", "好笑"}
    return bool(value)


def _parse_ranking(raw: str, all_ids: list[str], candidate_count: int, anchors: list[dict], model: str) -> GroupRankResult:
    data = json.loads(_strip_wrappers(raw))
    ranking = data.get("ranking", [])
    anchor_id_map = {f"A{item['id']}": item for item in anchors}

    seen: set[str] = set()
    parsed_positions: list[RankPosition] = []
    for rank, item in enumerate(ranking, start=1):
        candidate_id = str(item.get("id", "")).strip()
        if candidate_id not in all_ids or candidate_id in seen:
            continue
        seen.add(candidate_id)
        is_anchor = candidate_id.startswith("A")
        pos = RankPosition(
            text_index=(int(candidate_id[1:]) - 1) if candidate_id.startswith("C") else -1,
            rank=rank,
            is_funny=_safe_bool(item.get("funny", False)),
            justification=str(item.get("reason", "")).strip(),
            rank_score=0.0,
            is_anchor=is_anchor,
            candidate_id=candidate_id[1:] if is_anchor else candidate_id,
        )
        parsed_positions.append(pos)

    missing = [candidate_id for candidate_id in all_ids if candidate_id not in seen]
    start_rank = len(seen) + 1
    for offset, candidate_id in enumerate(missing):
        is_anchor = candidate_id.startswith("A")
        pos = RankPosition(
            text_index=(int(candidate_id[1:]) - 1) if candidate_id.startswith("C") else -1,
            rank=start_rank + offset,
            is_funny=False,
            justification="模型未返回该项，按保守策略视为靠后且偏不好笑。",
            rank_score=0.0,
            is_anchor=is_anchor,
            candidate_id=candidate_id[1:] if is_anchor else candidate_id,
        )
        parsed_positions.append(pos)

    parsed_positions.sort(key=lambda pos: pos.rank)
    positions: list[RankPosition] = []
    anchor_positions: list[RankPosition] = []
    candidate_rank = 0
    for pos in parsed_positions:
        if pos.is_anchor:
            anchor_positions.append(pos)
            continue
        candidate_rank += 1
        pos.rank = candidate_rank
        pos.rank_score = rank_score(candidate_rank, candidate_count, pos.is_funny)
        positions.append(pos)

    anchor_checks: list[bool] = []
    funny_anchor = next((pos for pos in anchor_positions if f"A{pos.candidate_id}" in anchor_id_map and anchor_id_map[f"A{pos.candidate_id}"]["label"] == "funny"), None)
    bad_anchor = next((pos for pos in anchor_positions if f"A{pos.candidate_id}" in anchor_id_map and anchor_id_map[f"A{pos.candidate_id}"]["label"] == "not_funny"), None)
    if funny_anchor is not None:
        anchor_checks.append(funny_anchor.is_funny)
    if bad_anchor is not None:
        anchor_checks.append(not bad_anchor.is_funny)
    if funny_anchor is not None and bad_anchor is not None:
        anchor_checks.append(funny_anchor.rank < bad_anchor.rank)
    anchor_accuracy = (sum(1 for ok in anchor_checks if ok) / len(anchor_checks)) if anchor_checks else 0.0

    return GroupRankResult(
        positions=positions,
        anchor_positions=anchor_positions,
        raw_response=raw,
        model=model,
        anchor_accuracy=round(anchor_accuracy, 4),
    )


def rank_group(texts: list[str], content_type: ContentType, anchors: list[dict]) -> GroupRankResult:
    all_ids = [f"C{i}" for i in range(1, len(texts) + 1)] + [f"A{item['id']}" for item in anchors]
    route = judge_router.route_judge("\n".join(texts[:2]), content_type)
    prompt = (
        humor_engine._read_prompt(RANK_PROMPT_PATH)
        .replace("{total_count}", str(len(all_ids)))
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{items_block}", _build_items_block(texts, anchors))
    )
    prompt += f"\n\nJudge 路由信息（必须遵守）：\n{route.prompt_block}"
    model = os.getenv("DOUBAO_JUDGE_MODEL", "doubao-seed-2.0-lite-250315")
    raw = humor_engine._chat(
        humor_engine._judge_client(),
        model,
        prompt,
        temperature=0.3,
        max_tokens=1024,
        role="judge",
    )
    return _parse_ranking(raw, all_ids, len(texts), anchors, model)


def rank_and_score_batch(
    texts: list[str],
    content_type: ContentType,
    persona_id: Optional[int] = None,
    db_path: str = db.DB_PATH,
) -> tuple[list[JokeRecord], GroupRankResult]:
    if not texts:
        return [], GroupRankResult([], [], "", "", 0.0)

    anchors = select_anchors(content_type, db_path=db_path)
    result = rank_group(texts, content_type, anchors)

    top_indexes = [pos.text_index for pos in result.positions[:2] if pos.text_index >= 0]
    bottom_indexes = [result.positions[-1].text_index] if result.positions else []
    diagnostic_indexes = sorted({idx for idx in top_indexes + bottom_indexes if idx >= 0})

    diagnostics = {}
    for idx in diagnostic_indexes:
        diagnostics[idx] = humor_engine.score(texts[idx], content_type)

    records: list[JokeRecord] = []
    group_size = len(texts)
    by_index = {pos.text_index: pos for pos in result.positions}
    for idx, text in enumerate(texts):
        pos = by_index[idx]
        score = diagnostics.get(idx)
        records.append(
            JokeRecord(
                id=None,
                content_type=content_type,
                text=text,
                persona_id=persona_id,
                score=score,
                human_rating=None,
                human_reaction=None,
                rank_score=pos.rank_score,
                rank_position=pos.rank,
                rank_group_size=group_size,
                is_funny=pos.is_funny,
                rank_justification=pos.justification,
            )
        )
    return records, result
