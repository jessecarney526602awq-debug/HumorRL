"""
HumorRL — 自动调度器
APScheduler 定时批量生成、评分、Reward Hacking 检查。

启动方式：python scheduler.py
（独立进程，与 Streamlit app 并行运行）
"""

import logging
import os
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

import db
import humor_engine
import monitor
import strategy
from contract import GenerationRequest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "500000"))


def _check_daily_budget() -> bool:
    """检查今天的 token 用量是否超限。"""
    stats = db.get_cost_stats(days=1)
    used = stats["total_tokens"]
    if used >= DAILY_TOKEN_LIMIT:
        logger.warning(f"今日 token 用量 {used} 已达上限 {DAILY_TOKEN_LIMIT}，跳过本次生成")
        return False
    return True


def job_batch_generate():
    """
    定时批量生成任务（每小时执行一次）。
    流程：
    1. 检查每日 token 预算
    2. 用 UCB1 选择内容类型
    3. 生成 1 条最优内容（Best-of-3，节省 token）
    4. 存入 DB
    5. 检测 Reward Hacking，L2 及以上则停止本次生成
    """
    logger.info("=== 批量生成任务开始 ===")

    if not _check_daily_budget():
        return

    try:
        content_type = strategy.ucb1_select_content_type()
        logger.info(f"UCB1 选择类型：{content_type.value}")

        alert = monitor.detect_reward_hacking()
        if alert.level >= 2:
            logger.warning(f"Reward Hacking L{alert.level} 检测到，停止生成：{alert.message}")
            return

        req = GenerationRequest(content_type=content_type, n=3)
        joke = humor_engine.generate_and_pick_best(req)
        saved_id = db.save_joke(joke)
        logger.info(f"已生成并存储，id={saved_id}，得分={joke.score.weighted_total:.2f}")

        if alert.level == 1:
            logger.warning(f"Reward Hacking L1 预警：{alert.action}")

    except Exception as exc:
        logger.error(f"批量生成任务失败：{exc}", exc_info=True)

    logger.info("=== 批量生成任务结束 ===")


def job_health_check():
    """
    定时健康检查（每6小时执行一次）。
    - 输出多样性报告
    - 输出 Reward Hacking 检测结果
    - 输出今日 token 用量
    """
    logger.info("=== 健康检查 ===")
    try:
        diversity = monitor.compute_diversity()
        logger.info(f"多样性熵：{diversity.entropy:.3f}（{diversity.interpretation}）")

        alert = monitor.detect_reward_hacking()
        logger.info(f"Reward Hacking Level={alert.level}，{alert.message}")

        cost = db.get_cost_stats(days=1)
        logger.info(f"今日 token 用量：{cost['total_tokens']:,} / {DAILY_TOKEN_LIMIT:,}")
    except Exception as exc:
        logger.error(f"健康检查失败：{exc}", exc_info=True)


def job_evolution():
    """每天凌晨2点运行 Prompt 遗传算法（逐类型轮换，每次只进化一种类型节省成本）。"""
    import datetime

    from contract import ContentType
    from evolution import run_evolution

    logger.info("=== Prompt 进化任务开始 ===")

    if not _check_daily_budget():
        return

    weekday = datetime.datetime.now().weekday()
    types = list(ContentType)
    content_type = types[weekday % len(types)]
    logger.info(f"本次进化类型：{content_type.value}")

    try:
        report = run_evolution(
            content_type=content_type,
            population_size=6,
            generations=2,
            eval_n=2,
        )
        logger.info(
            f"进化完成 | 最佳变体 id={report['best_variant_id']} "
            f"分数={report['best_score']:.2f} "
            f"提升={report['improvement']:+.2f}"
        )
    except Exception as exc:
        logger.error(f"Prompt 进化失败：{exc}", exc_info=True)

    logger.info("=== Prompt 进化任务结束 ===")


def main():
    db.init_db()
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    scheduler.add_job(job_batch_generate, "cron", minute=0)
    scheduler.add_job(job_health_check, "cron", hour="0,6,12,18", minute=5)
    scheduler.add_job(job_evolution, "cron", hour=2, minute=0)

    logger.info("调度器启动，按 Ctrl+C 退出")
    logger.info(f"每日 token 上限：{DAILY_TOKEN_LIMIT:,}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
