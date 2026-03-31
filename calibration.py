"""
HumorRL — LLM Judge 校准模块
计算人工评分 vs LLM 评分的皮尔逊相关系数。
"""

import datetime
import math
import sqlite3
from dataclasses import dataclass
from typing import Optional

import db


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
