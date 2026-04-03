"""
HumorRL — Judge 校准模块
支持两类能力：
1. 传统：用 DB 中的人工评分计算相关性
2. 新增：用校准数据集批量打分，生成 Judge 长期修正规则
"""

import datetime
import json
import logging
import math
import os
import random
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import db
import humor_engine
import ranker
from contract import ContentType


logger = logging.getLogger(__name__)
CALIBRATION_PROMPT_PATH = "prompts/strategist/calibration.txt"


@dataclass
class CalibrationReport:
    sample_size: int
    pearson_r: float
    p_value: float
    llm_mean: float
    llm_std: float
    human_mean: float
    human_std: float
    avg_gap: float
    interpretation: str
    generated_at: datetime.datetime


def _build_interpretation(sample_size: int, pearson_r: float, avg_gap: float) -> str:
    if sample_size < 10:
        text = f"样本不足（{sample_size}条），结论不可靠，建议先标注更多数据"
    elif pearson_r >= 0.7:
        text = f"LLM 评分与人工评分高度相关（r={pearson_r:.2f}），评分系统校准良好"
    elif pearson_r >= 0.4:
        text = f"LLM 评分与人工评分中度相关（r={pearson_r:.2f}），有一定参考价值"
    elif pearson_r >= 0:
        text = f"LLM 评分与人工评分弱相关（r={pearson_r:.2f}），建议检查评分 Prompt"
    else:
        text = f"LLM 评分与人工评分负相关（r={pearson_r:.2f}），评分标准可能存在系统偏差"

    if avg_gap > 1.5:
        text += f" 注意：LLM 评分系统性偏高 {avg_gap:.1f} 分"
    elif avg_gap < -1.5:
        text += f" 注意：LLM 评分系统性偏低 {abs(avg_gap):.1f} 分"
    return text


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _sample_std(values: list[float], mean_value: float) -> float:
    if len(values) < 2:
        return 0.0
    variance = sum((value - mean_value) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _pearson_with_numpy(llm_scores: list[float], human_scores: list[float]) -> tuple[float, float]:
    import numpy as np

    llm_array = np.asarray(llm_scores, dtype=float)
    human_array = np.asarray(human_scores, dtype=float)
    pearson_r = float(np.corrcoef(llm_array, human_array)[0, 1])
    return pearson_r, float("nan")


def _pearson(x: list[float], y: list[float]) -> float:
    n = len(x)
    if n < 3:
        return 0.0
    mean_x = sum(xi for xi in x) / n
    mean_y = sum(yi for yi in y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    std_x = sum((xi - mean_x) ** 2 for xi in x) ** 0.5
    std_y = sum((yi - mean_y) ** 2 for yi in y) ** 0.5
    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (std_x * std_y)


def _spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 3:
        return 0.0

    def _rank(values: list[float]) -> list[float]:
        sorted_pairs = sorted(enumerate(values), key=lambda item: item[1])
        ranks = [0.0] * len(values)
        for rank, (index, _) in enumerate(sorted_pairs, start=1):
            ranks[index] = float(rank)
        return ranks

    return _pearson(_rank(x), _rank(y))


def _load_humor_reference() -> str:
    path = Path(__file__).resolve().parent / "prompts" / "reference" / "humor_cases.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return "（暂无额外幽默案例参考）"


def _parse_json_block(raw: str) -> dict:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    cleaned = cleaned.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(cleaned)


def _format_misclassified(results: list[dict], label: str, direction: str, limit: int = 5) -> str:
    if direction == "high":
        filtered = [item for item in results if item["label"] == label and item["judge_score"] >= 6.0]
        filtered.sort(key=lambda item: item["judge_score"], reverse=True)
    else:
        filtered = [item for item in results if item["label"] == label and item["judge_score"] <= 6.0]
        filtered.sort(key=lambda item: item["judge_score"])

    lines = []
    for item in filtered[:limit]:
        lines.append(
            f"[ID={item['id']} 预期={item['expected_score']:.1f} Judge={item['judge_score']:.2f}] "
            f"{item['text'][:70].replace(chr(10), ' ')}\n"
            f"  Judge理由：{item['reasoning'][:120]}"
        )
    return "\n".join(lines) or "（无）"


def _save_unique_lessons(entry_type: str, lessons: list[str], db_path: str) -> list[str]:
    existing = {entry["content"] for entry in db.get_knowledge(entry_type=entry_type, limit=200, db_path=db_path)}
    saved = []
    for lesson in lessons:
        lesson = str(lesson).strip()
        if not lesson or lesson in existing:
            continue
        db.save_knowledge(entry_type=entry_type, content=lesson, relevance_score=1.3, db_path=db_path)
        existing.add(lesson)
        saved.append(lesson)
    return saved


def _save_calibration_guidance(result: dict, db_path: str) -> None:
    judge_directive = str(result.get("judge_directive", "")).strip()
    if judge_directive:
        db.save_knowledge(
            entry_type="judge_directive",
            content=judge_directive,
            relevance_score=1.45,
            db_path=db_path,
        )

    _save_unique_lessons("judge_lesson", result.get("judge_lessons", []), db_path=db_path)
    _save_unique_lessons("writer_lesson", result.get("writer_lessons", []), db_path=db_path)


def run_calibration(
    db_path: str = db.DB_PATH,
    calibration_path: Optional[str] = None,
) -> dict:
    """
    用 data/calibration_set.json 批量校准 Judge：
    - 批量评分
    - 计算 Pearson / Spearman
    - 提炼错判样本
    - 让 strategist 模型产出长期评分教训
    - 持久化到知识库
    """
    calibration_data = db.load_calibration_set(path=calibration_path)
    if not calibration_data:
        raise ValueError("校准数据集为空")

    logger.info("校准数据集加载完成，共 %s 条", len(calibration_data))

    def _score_one(item: dict) -> dict:
        content_type = ContentType(item["content_type"])
        score_result = humor_engine.score(item["text"], content_type)
        return {
            "id": int(item["id"]),
            "text": str(item["text"]),
            "label": str(item["label"]),
            "content_type": content_type.value,
            "expected_score": float(item["expected_score"]),
            "judge_score": float(score_result.weighted_total),
            "reasoning": score_result.reasoning,
            "dimensions": {
                "structure": score_result.structure,
                "surprise": score_result.surprise,
                "relatability": score_result.relatability,
                "language": score_result.language,
                "creativity": score_result.creativity,
                "safety": score_result.safety,
            },
        }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(12, max(1, len(calibration_data)))) as executor:
        futures = [executor.submit(_score_one, item) for item in calibration_data]
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["id"])
    expected_scores = [item["expected_score"] for item in results]
    judge_scores = [item["judge_score"] for item in results]
    overall_pearson = _pearson(expected_scores, judge_scores)
    overall_spearman = _spearman(expected_scores, judge_scores)
    avg_gap = _mean([judge - expected for judge, expected in zip(judge_scores, expected_scores)])

    funny_items = [item for item in results if item["label"] == "funny"]
    not_funny_items = [item for item in results if item["label"] == "not_funny"]
    funny_identified = (
        sum(1 for item in funny_items if item["judge_score"] >= 7.0) / len(funny_items)
        if funny_items else 0.0
    )
    not_funny_identified = (
        sum(1 for item in not_funny_items if item["judge_score"] <= 4.0) / len(not_funny_items)
        if not_funny_items else 0.0
    )

    dimension_biases = {
        "avg_gap": round(avg_gap, 4),
        "funny_mean": round(_mean([item["judge_score"] for item in funny_items]), 4) if funny_items else 0.0,
        "not_funny_mean": round(_mean([item["judge_score"] for item in not_funny_items]), 4) if not_funny_items else 0.0,
    }
    classification_accuracy = {
        "funny_identified": funny_identified,
        "not_funny_identified": not_funny_identified,
        "overall": (
            (
                sum(1 for item in funny_items if item["judge_score"] >= 7.0)
                + sum(1 for item in not_funny_items if item["judge_score"] <= 4.0)
            ) / len(results)
            if results else 0.0
        ),
    }

    prompt = (
        humor_engine._read_prompt(CALIBRATION_PROMPT_PATH)
        .replace("{theory_foundation}", (Path(__file__).resolve().parent / "prompts" / "strategist" / "theory_foundation.txt").read_text(encoding="utf-8"))
        .replace("{humor_reference}", _load_humor_reference())
        .replace("{sample_size}", str(len(results)))
        .replace("{overall_pearson}", f"{overall_pearson:.4f}")
        .replace("{overall_spearman}", f"{overall_spearman:.4f}")
        .replace("{avg_gap}", f"{avg_gap:.4f}")
        .replace("{funny_accuracy}", f"{funny_identified:.1%}")
        .replace("{not_funny_accuracy}", f"{not_funny_identified:.1%}")
        .replace("{high_false_positives}", _format_misclassified(results, "not_funny", "high"))
        .replace("{low_false_negatives}", _format_misclassified(results, "funny", "low"))
    )

    model = os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215")
    raw = humor_engine._chat(
        humor_engine._strategist_client(),
        model,
        prompt,
        temperature=0.3,
        max_tokens=1400,
        role="strategist",
    )
    result = _parse_json_block(raw)

    report_md = (
        "# Judge 校准报告\n\n"
        f"- 运行时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 样本量：{len(results)}\n"
        f"- Pearson：{overall_pearson:.4f}\n"
        f"- Spearman：{overall_spearman:.4f}\n"
        f"- 平均分差：{avg_gap:.4f}\n"
        f"- 好笑识别率：{funny_identified:.1%}\n"
        f"- 不好笑识别率：{not_funny_identified:.1%}\n\n"
        f"## 核心问题\n{result.get('summary', '（无）')}\n\n"
        "## 校准教训\n"
        + "\n".join(f"- {item}" for item in result.get("lessons", []))
        + "\n\n## Judge 长期规则\n"
        + str(result.get("judge_directive", "（无）"))
        + "\n"
    )

    db.save_calibration_run(
        run_date=datetime.date.today().isoformat(),
        overall_correlation=overall_spearman,
        dimension_biases=dimension_biases,
        classification_accuracy=classification_accuracy,
        report_md=report_md,
        db_path=db_path,
    )
    _save_calibration_guidance(result, db_path=db_path)
    try:
        import strategist

        strategist.export_memory_snapshot(db_path=db_path)
    except Exception:
        pass

    return {
        "sample_size": len(results),
        "overall_pearson": overall_pearson,
        "overall_spearman": overall_spearman,
        "avg_gap": avg_gap,
        "dimension_biases": dimension_biases,
        "classification_accuracy": classification_accuracy,
        "summary": result.get("summary", ""),
        "lessons": [str(item).strip() for item in result.get("lessons", []) if str(item).strip()],
        "judge_lessons": [str(item).strip() for item in result.get("judge_lessons", []) if str(item).strip()],
        "writer_lessons": [str(item).strip() for item in result.get("writer_lessons", []) if str(item).strip()],
        "judge_directive": str(result.get("judge_directive", "")).strip(),
        "results": results,
        "report_md": report_md,
    }


def run_rank_calibration(
    db_path: str = db.DB_PATH,
    calibration_path: Optional[str] = None,
    groups: int = 5,
    group_size: int = 5,
) -> dict:
    """
    用 group comparison 对校准集做排序验证。
    目标不是替代 pointwise calibration，而是验证训练轨的相对偏好质量。
    """
    calibration_data = db.load_calibration_set(path=calibration_path)
    if not calibration_data:
        raise ValueError("校准数据集为空")

    grouped: dict[str, list[dict]] = {}
    for item in calibration_data:
        grouped.setdefault(str(item["content_type"]), []).append(item)

    eligible_types = [ct for ct, items in grouped.items() if len(items) >= group_size]
    if not eligible_types:
        raise ValueError("没有足够样本可用于 rank calibration")

    rng = random.Random(20260402)
    group_runs: list[dict] = []
    for idx in range(groups):
        content_type_value = eligible_types[idx % len(eligible_types)]
        batch = rng.sample(grouped[content_type_value], group_size)
        content_type = ContentType(content_type_value)
        anchors = ranker.select_anchors(content_type, db_path=db_path)
        result = ranker.rank_group([item["text"] for item in batch], content_type, anchors)
        by_index = {pos.text_index: pos for pos in result.positions}
        for item_idx, item in enumerate(batch):
            pos = by_index[item_idx]
            group_runs.append(
                {
                    "id": int(item["id"]),
                    "text": str(item["text"]),
                    "label": str(item["label"]),
                    "content_type": content_type_value,
                    "expected_score": float(item["expected_score"]),
                    "judge_score": float(pos.rank_score),
                    "reasoning": pos.justification,
                    "is_funny": bool(pos.is_funny),
                    "rank_position": int(pos.rank),
                    "anchor_accuracy": float(result.anchor_accuracy),
                }
            )

    expected_scores = [item["expected_score"] for item in group_runs]
    judge_scores = [item["judge_score"] for item in group_runs]
    overall_pearson = _pearson(expected_scores, judge_scores)
    overall_spearman = _spearman(expected_scores, judge_scores)
    avg_gap = _mean([judge - expected for judge, expected in zip(judge_scores, expected_scores)])

    funny_items = [item for item in group_runs if item["label"] == "funny"]
    not_funny_items = [item for item in group_runs if item["label"] == "not_funny"]
    funny_identified = (
        sum(1 for item in funny_items if item["is_funny"]) / len(funny_items)
        if funny_items else 0.0
    )
    not_funny_identified = (
        sum(1 for item in not_funny_items if not item["is_funny"]) / len(not_funny_items)
        if not_funny_items else 0.0
    )
    avg_anchor_accuracy = _mean([item["anchor_accuracy"] for item in group_runs]) if group_runs else 0.0

    prompt = (
        humor_engine._read_prompt(CALIBRATION_PROMPT_PATH)
        .replace("{theory_foundation}", (Path(__file__).resolve().parent / "prompts" / "strategist" / "theory_foundation.txt").read_text(encoding="utf-8"))
        .replace("{humor_reference}", _load_humor_reference())
        .replace("{sample_size}", str(len(group_runs)))
        .replace("{overall_pearson}", f"{overall_pearson:.4f}")
        .replace("{overall_spearman}", f"{overall_spearman:.4f}")
        .replace("{avg_gap}", f"{avg_gap:.4f}")
        .replace("{funny_accuracy}", f"{funny_identified:.1%}")
        .replace("{not_funny_accuracy}", f"{not_funny_identified:.1%}")
        .replace("{high_false_positives}", _format_misclassified(group_runs, "not_funny", "high"))
        .replace("{low_false_negatives}", _format_misclassified(group_runs, "funny", "low"))
    )
    prompt += f"\n\n补充背景：本次是 group comparison 校准，平均锚点准确率={avg_anchor_accuracy:.1%}。"

    model = os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2-0-pro-260215")
    raw = humor_engine._chat(
        humor_engine._strategist_client(),
        model,
        prompt,
        temperature=0.3,
        max_tokens=1400,
        role="strategist",
    )
    result = _parse_json_block(raw)

    report_md = (
        "# Judge 排序校准报告\n\n"
        f"- 运行时间：{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 样本量：{len(group_runs)}\n"
        f"- Pearson：{overall_pearson:.4f}\n"
        f"- Spearman：{overall_spearman:.4f}\n"
        f"- 平均分差：{avg_gap:.4f}\n"
        f"- 好笑识别率：{funny_identified:.1%}\n"
        f"- 不好笑识别率：{not_funny_identified:.1%}\n"
        f"- 平均锚点准确率：{avg_anchor_accuracy:.1%}\n\n"
        f"## 核心问题\n{result.get('summary', '（无）')}\n\n"
        "## 校准教训\n"
        + "\n".join(f"- {item}" for item in result.get("lessons", []))
        + "\n\n## Judge 长期规则\n"
        + str(result.get("judge_directive", "（无）"))
        + "\n"
    )

    db.save_calibration_run(
        run_date=datetime.date.today().isoformat(),
        overall_correlation=overall_spearman,
        dimension_biases={"avg_gap": round(avg_gap, 4), "avg_anchor_accuracy": round(avg_anchor_accuracy, 4)},
        classification_accuracy={
            "funny_identified": funny_identified,
            "not_funny_identified": not_funny_identified,
            "overall": (
                (
                    sum(1 for item in funny_items if item["is_funny"])
                    + sum(1 for item in not_funny_items if not item["is_funny"])
                ) / len(group_runs)
                if group_runs else 0.0
            ),
            "avg_anchor_accuracy": avg_anchor_accuracy,
        },
        report_md=report_md,
        db_path=db_path,
    )
    _save_calibration_guidance(result, db_path=db_path)
    try:
        import strategist

        strategist.export_memory_snapshot(db_path=db_path)
    except Exception:
        pass

    return {
        "sample_size": len(group_runs),
        "overall_pearson": overall_pearson,
        "overall_spearman": overall_spearman,
        "avg_gap": avg_gap,
        "classification_accuracy": {
            "funny_identified": funny_identified,
            "not_funny_identified": not_funny_identified,
            "avg_anchor_accuracy": avg_anchor_accuracy,
        },
        "summary": result.get("summary", ""),
        "lessons": [str(item).strip() for item in result.get("lessons", []) if str(item).strip()],
        "judge_lessons": [str(item).strip() for item in result.get("judge_lessons", []) if str(item).strip()],
        "writer_lessons": [str(item).strip() for item in result.get("writer_lessons", []) if str(item).strip()],
        "judge_directive": str(result.get("judge_directive", "")).strip(),
        "results": group_runs,
        "report_md": report_md,
    }


def compute_calibration(
    content_type: Optional[str] = None,
    db_path: str = db.DB_PATH,
) -> CalibrationReport:
    """
    从 DB 取同时有 human_rating 和 score_total 的记录，计算皮尔逊相关。
    content_type：传 ContentType.value 字符串或 None（全类型）。
    sample_size < 2 时 raise ValueError("没有可用于校准的已标注数据")。

    interpretation 规则：
      sample_size < 10 → "样本不足（{n}条），结论不可靠，建议先标注更多数据"
      r >= 0.7  → "LLM 评分与人工评分高度相关（r={r:.2f}），评分系统校准良好"
      r >= 0.4  → "LLM 评分与人工评分中度相关（r={r:.2f}），有一定参考价值"
      r >= 0    → "LLM 评分与人工评分弱相关（r={r:.2f}），建议检查评分 Prompt"
      r < 0     → "LLM 评分与人工评分负相关（r={r:.2f}），评分标准可能存在系统偏差"
      avg_gap > 1.5  → 追加："注意：LLM 评分系统性偏高 {avg_gap:.1f} 分"
      avg_gap < -1.5 → 追加："注意：LLM 评分系统性偏低 {abs(avg_gap):.1f} 分"

    优先用 scipy.stats.pearsonr；不可用时用 numpy 手算，p_value=float('nan')。
    """
    params: list[object] = []
    query = (
        "SELECT score_total, human_rating FROM jokes "
        "WHERE score_total IS NOT NULL AND human_rating IS NOT NULL"
    )
    if content_type is not None:
        query += " AND content_type = ?"
        params.append(content_type)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    if len(rows) < 2:
        raise ValueError("没有可用于校准的已标注数据")

    llm_scores = [float(row[0]) for row in rows]
    human_scores = [float(row[1]) for row in rows]
    sample_size = len(rows)

    try:
        from scipy.stats import pearsonr

        pearson_r, p_value = pearsonr(llm_scores, human_scores)
        pearson_r = float(pearson_r)
        p_value = float(p_value)
    except Exception:
        pearson_r, p_value = _pearson_with_numpy(llm_scores, human_scores)

    llm_mean = _mean(llm_scores)
    human_mean = _mean(human_scores)
    llm_std = _sample_std(llm_scores, llm_mean)
    human_std = _sample_std(human_scores, human_mean)
    avg_gap = llm_mean - human_mean

    return CalibrationReport(
        sample_size=sample_size,
        pearson_r=pearson_r,
        p_value=p_value,
        llm_mean=llm_mean,
        llm_std=llm_std,
        human_mean=human_mean,
        human_std=human_std,
        avg_gap=avg_gap,
        interpretation=_build_interpretation(sample_size, pearson_r, avg_gap),
        generated_at=datetime.datetime.now(),
    )


def format_report_text(report: CalibrationReport) -> str:
    """
    格式化为 Markdown，包含：标题、生成时间、样本量、指标表格、结论。
    """
    p_value_text = "NaN" if math.isnan(report.p_value) else f"{report.p_value:.4f}"
    return (
        "# LLM Judge 校准报告\n\n"
        f"- 生成时间：{report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- 样本量：{report.sample_size}\n\n"
        "| 指标 | 数值 |\n"
        "| --- | --- |\n"
        f"| 皮尔逊相关系数 r | {report.pearson_r:.4f} |\n"
        f"| p-value | {p_value_text} |\n"
        f"| LLM 平均分 | {report.llm_mean:.4f} |\n"
        f"| LLM 标准差 | {report.llm_std:.4f} |\n"
        f"| 人工平均分 | {report.human_mean:.4f} |\n"
        f"| 人工标准差 | {report.human_std:.4f} |\n"
        f"| 平均分差 (LLM - 人工) | {report.avg_gap:.4f} |\n\n"
        f"## 结论\n{report.interpretation}\n"
    )
