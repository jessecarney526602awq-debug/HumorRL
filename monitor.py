"""
HumorRL — 监控模块
多样性熵计算 + Reward Hacking 检测 + 干预建议
"""

import math
from collections import Counter
from dataclasses import dataclass

import db
from contract import ContentType


@dataclass
class DiversityReport:
    """内容多样性报告"""

    entropy: float
    max_entropy: float
    diversity_ratio: float
    type_distribution: dict[str, int]
    interpretation: str


@dataclass
class RewardHackingAlert:
    """Reward Hacking 检测结果"""

    level: int
    score_trend: float
    repetition_rate: float
    message: str
    action: str


@dataclass
class RankQualityReport:
    avg_anchor_accuracy: float
    not_funny_ratio: float
    sample_count: int
    interpretation: str


def compute_diversity(
    recent_n: int = 100,
    db_path: str = db.DB_PATH,
) -> DiversityReport:
    """
    计算最近 recent_n 条内容的 Shannon 熵（按内容类型分布）。

    entropy = -sum(p_i * log2(p_i)) for each content_type
    max_entropy = log2(num_types)
    diversity_ratio = entropy / max_entropy

    interpretation 规则：
      diversity_ratio >= 0.8 → "内容分布均衡，多样性良好"
      diversity_ratio >= 0.5 → "内容分布中等，部分类型偏少"
      diversity_ratio < 0.5  → "内容分布集中，建议增加其他类型生成"
    """
    with db._connect(db_path) as conn:
        rows = conn.execute(
            "SELECT content_type FROM jokes ORDER BY created_at DESC LIMIT ?",
            (recent_n,),
        ).fetchall()

    distribution = {content_type.value: 0 for content_type in ContentType}
    for row in rows:
        distribution[row["content_type"]] = distribution.get(row["content_type"], 0) + 1

    total = sum(distribution.values())
    max_entropy = math.log2(len(ContentType)) if len(ContentType) > 1 else 0.0
    if total == 0 or max_entropy == 0:
        return DiversityReport(
            entropy=0.0,
            max_entropy=max_entropy,
            diversity_ratio=0.0,
            type_distribution=distribution,
            interpretation="暂无生成数据，暂时无法评估多样性",
        )

    entropy = 0.0
    for count in distribution.values():
        if count <= 0:
            continue
        p_i = count / total
        entropy -= p_i * math.log2(p_i)

    diversity_ratio = entropy / max_entropy if max_entropy > 0 else 0.0
    if diversity_ratio >= 0.8:
        interpretation = "内容分布均衡，多样性良好"
    elif diversity_ratio >= 0.5:
        interpretation = "内容分布中等，部分类型偏少"
    else:
        interpretation = "内容分布集中，建议增加其他类型生成"

    return DiversityReport(
        entropy=entropy,
        max_entropy=max_entropy,
        diversity_ratio=diversity_ratio,
        type_distribution=distribution,
        interpretation=interpretation,
    )


def detect_reward_hacking(
    recent_n: int = 50,
    db_path: str = db.DB_PATH,
) -> RewardHackingAlert:
    """
    检测 Reward Hacking：分数在上升，但内容开始趋同（重复）。

    算法：
    1. 取最近 recent_n 条（含评分）按时间排序
    2. score_trend = 后半段均分 - 前半段均分
    3. repetition_rate：取每条文本前 20 字，统计重复片段占比
       repetition_rate = 重复出现的前缀数 / total，重复定义为出现 ≥2 次的前缀

    告警级别规则：
      L0（正常）：score_trend <= 1.5 OR repetition_rate < 0.3
      L1（预警）：score_trend > 1.5 AND repetition_rate >= 0.3
                  action = "自动微调：下次生成 temperature +0.1（不超过 1.2）"
      L2（警告）：score_trend > 2.0 AND repetition_rate >= 0.5
                  action = "建议暂停自动生成，人工检查近期内容质量"
      L3（严重）：score_trend > 2.5 AND repetition_rate >= 0.7
                  action = "立即停止自动生成，回滚到上一个健康检查点的 Prompt"

    数据不足（< 10 条）时返回 level=0, message="数据不足，暂无检测结果"
    """
    with db._connect(db_path) as conn:
        rows = conn.execute(
            "SELECT text, COALESCE(rank_score, score_total) as reward, created_at FROM jokes "
            "WHERE COALESCE(rank_score, score_total) IS NOT NULL "
            "ORDER BY created_at DESC LIMIT ?",
            (recent_n,),
        ).fetchall()

    ordered_rows = list(reversed(rows))
    if len(ordered_rows) < 10:
        return RewardHackingAlert(
            level=0,
            score_trend=0.0,
            repetition_rate=0.0,
            message="数据不足，暂无检测结果",
            action="继续积累样本后再观察趋势",
        )

    midpoint = len(ordered_rows) // 2
    first_half = ordered_rows[:midpoint]
    second_half = ordered_rows[midpoint:]

    first_avg = sum(float(row["reward"]) for row in first_half) / len(first_half)
    second_avg = sum(float(row["reward"]) for row in second_half) / len(second_half)
    score_trend = second_avg - first_avg

    prefixes = [str(row["text"])[:20] for row in ordered_rows]
    prefix_counts = Counter(prefixes)
    repeated_items = sum(count for count in prefix_counts.values() if count >= 2)
    repetition_rate = repeated_items / len(prefixes)

    if score_trend > 2.5 and repetition_rate >= 0.7:
        level = 3
        message = "近期分数快速抬升，但文本前缀高度重复，疑似严重 Reward Hacking"
        action = "立即停止自动生成，回滚到上一个健康检查点的 Prompt"
    elif score_trend > 2.0 and repetition_rate >= 0.5:
        level = 2
        message = "近期分数上升明显，同时内容重复率较高，存在明显同质化风险"
        action = "建议暂停自动生成，人工检查近期内容质量"
    elif score_trend > 1.5 and repetition_rate >= 0.3:
        level = 1
        message = "近期分数在上升，但内容开始趋同，需要关注 Reward Hacking 早期迹象"
        action = "自动微调：下次生成 temperature +0.1（不超过 1.2）"
    else:
        level = 0
        message = "近期分数与内容重复率处于正常范围"
        action = "维持当前生成策略"

    return RewardHackingAlert(
        level=level,
        score_trend=score_trend,
        repetition_rate=repetition_rate,
        message=message,
        action=action,
    )


def check_rank_quality(
    recent_n: int = 50,
    db_path: str = db.DB_PATH,
) -> RankQualityReport:
    stats = db.get_rank_stats(recent_n=recent_n, db_path=db_path)
    sample_count = int(stats["count"])
    if sample_count == 0:
        return RankQualityReport(
            avg_anchor_accuracy=0.0,
            not_funny_ratio=0.0,
            sample_count=0,
            interpretation="暂无 group comparison 数据",
        )

    avg_anchor_accuracy = float(stats["avg_anchor_accuracy"])
    not_funny_ratio = float(stats["not_funny_ratio"])
    if avg_anchor_accuracy < 0.5:
        interpretation = "锚点准确率过低，Judge 可能漂移，建议暂停训练排查"
    elif avg_anchor_accuracy < 0.8:
        interpretation = "锚点准确率一般，建议继续观察并做人工抽检"
    elif not_funny_ratio < 0.2:
        interpretation = "Judge 仍偏宽松，不好笑内容比例偏低"
    elif not_funny_ratio > 0.6:
        interpretation = "Judge 偏苛刻，不好笑内容比例偏高"
    else:
        interpretation = "rank 质量正常，锚点准确率和区分度处于健康范围"

    return RankQualityReport(
        avg_anchor_accuracy=avg_anchor_accuracy,
        not_funny_ratio=not_funny_ratio,
        sample_count=sample_count,
        interpretation=interpretation,
    )
