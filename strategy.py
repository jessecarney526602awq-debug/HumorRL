"""
HumorRL — 内容类型选择策略
使用 UCB1（Upper Confidence Bound）算法，
根据历史评分自动选择最优内容类型进行下一次生成。
"""

import math

import db
from contract import CONTENT_TYPE_LABELS, ContentType


def _type_stats_map(db_path: str = db.DB_PATH) -> dict[str, dict[str, float]]:
    with db._connect(db_path) as conn:
        rows = conn.execute(
            "SELECT content_type, COUNT(*) as plays, AVG(COALESCE(rank_score, score_total, 5.0)) as avg_score "
            "FROM jokes GROUP BY content_type"
        ).fetchall()
    return {
        row["content_type"]: {
            "plays": int(row["plays"]),
            "avg_score": float(row["avg_score"] or 5.0),
        }
        for row in rows
    }


def ucb1_select_content_type(
    db_path: str = db.DB_PATH,
    exploration_weight: float = 1.41,
) -> ContentType:
    """
    UCB1 算法选择下一次最应该生成的内容类型。

    UCB1 公式：score(i) = avg_reward(i) + C * sqrt(ln(total_plays) / plays(i))
    其中：
      avg_reward(i) = 该类型的历史平均训练奖励（优先 rank_score，回退 score_total，归一化到 0-1：除以 10）
      plays(i)      = 该类型的历史生成次数
      total_plays   = 所有类型的总生成次数
      C             = exploration_weight

    冷启动处理：
      - 如果某类型从未生成过（plays=0），优先选择这类型（保证每种类型至少尝试一次）
      - 如果多个类型都未生成过，按 ContentType 枚举顺序选第一个

    从 DB 的 jokes 表取数据：按 content_type GROUP BY，取 COUNT 和 AVG(COALESCE(rank_score, score_total))。
    rank_score / score_total 都为 NULL 的记录视为 avg_reward=0.5（中性）。

    返回选中的 ContentType。
    """
    stats_map = _type_stats_map(db_path=db_path)

    for content_type in ContentType:
        if content_type.value not in stats_map:
            return content_type

    total_plays = sum(int(item["plays"]) for item in stats_map.values())
    best_type = ContentType.STANDUP
    best_value = float("-inf")

    for content_type in ContentType:
        item = stats_map[content_type.value]
        plays = int(item["plays"])
        avg_reward = float(item["avg_score"]) / 10.0
        ucb1_value = avg_reward + exploration_weight * math.sqrt(math.log(total_plays) / plays)
        if ucb1_value > best_value:
            best_type = content_type
            best_value = ucb1_value

    return best_type


def get_type_performance_summary(
    db_path: str = db.DB_PATH,
) -> list[dict]:
    """
    返回各类型的 UCB1 状态摘要，供监控页展示。
    格式：[{
        "content_type": str,
        "label": str,
        "plays": int,
        "avg_score": float,
        "ucb1_value": float,
        "recommended": bool,
    }]
    按 ucb1_value 降序排列。
    """
    stats_map = _type_stats_map(db_path=db_path)
    total_plays = sum(int(item["plays"]) for item in stats_map.values())
    recommended_type = ucb1_select_content_type(db_path=db_path)

    summary = []
    for content_type in ContentType:
        item = stats_map.get(content_type.value, {"plays": 0, "avg_score": 5.0})
        plays = int(item["plays"])
        avg_score = float(item["avg_score"])

        if plays == 0:
            ucb1_value = float("inf")
        elif total_plays <= 1:
            ucb1_value = avg_score / 10.0
        else:
            ucb1_value = (avg_score / 10.0) + 1.41 * math.sqrt(math.log(total_plays) / plays)

        summary.append(
            {
                "content_type": content_type.value,
                "label": CONTENT_TYPE_LABELS[content_type],
                "plays": plays,
                "avg_score": avg_score,
                "ucb1_value": ucb1_value,
                "recommended": content_type == recommended_type,
            }
        )

    return sorted(summary, key=lambda item: item["ucb1_value"], reverse=True)
