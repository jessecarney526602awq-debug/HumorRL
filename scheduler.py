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


def job_heartbeat():
    """每分钟写一次心跳，前端用来判断调度器是否存活。"""
    db.upsert_job_status("heartbeat", "success")


def job_batch_generate():
    """定时批量生成任务（每小时执行一次）。"""
    logger.info("=== 批量生成任务开始 ===")
    db.upsert_job_status("batch_generate", "running")

    if not _check_daily_budget():
        db.upsert_job_status("batch_generate", "success", {"skipped": "budget"})
        return

    try:
        content_type = strategy.ucb1_select_content_type()
        logger.info(f"UCB1 选择类型：{content_type.value}")

        alert = monitor.detect_reward_hacking()
        if alert.level >= 2:
            logger.warning(f"Reward Hacking L{alert.level} 检测到，停止生成：{alert.message}")
            db.upsert_job_status("batch_generate", "success", {"skipped": f"hacking_l{alert.level}"})
            return

        req = GenerationRequest(content_type=content_type, n=3)
        joke = humor_engine.generate_and_pick_best(req)
        saved_id = db.save_joke(joke)
        score = joke.score.weighted_total if joke.score else 0
        logger.info(f"已生成并存储，id={saved_id}，得分={score:.2f}")

        try:
            from strategist import maybe_trigger
            result = maybe_trigger()
            if result and not result.get("skipped"):
                insight = result.get("insight", "")
                n_genes = len(result.get("new_genes", []))
                logger.info(f"战略师复盘完成 | 新基因={n_genes} | 洞察：{insight[:50]}")
        except Exception as exc:
            logger.warning(f"战略师触发检查失败（不影响主流程）：{exc}")

        if alert.level == 1:
            logger.warning(f"Reward Hacking L1 预警：{alert.action}")

        db.upsert_job_status("batch_generate", "success", {
            "saved_id": saved_id, "score": round(score, 2), "type": content_type.value
        })

    except Exception as exc:
        logger.error(f"批量生成任务失败：{exc}", exc_info=True)
        db.upsert_job_status("batch_generate", "error", {"error": str(exc)})

    logger.info("=== 批量生成任务结束 ===")


def job_health_check():
    """定时健康检查（每6小时执行一次）。"""
    logger.info("=== 健康检查 ===")
    db.upsert_job_status("health_check", "running")
    try:
        diversity = monitor.compute_diversity()
        logger.info(f"多样性熵：{diversity.entropy:.3f}（{diversity.interpretation}）")

        alert = monitor.detect_reward_hacking()
        logger.info(f"Reward Hacking Level={alert.level}，{alert.message}")

        cost = db.get_cost_stats(days=1)
        logger.info(f"今日 token 用量：{cost['total_tokens']:,} / {DAILY_TOKEN_LIMIT:,}")

        db.upsert_job_status("health_check", "success", {
            "diversity": round(diversity.entropy, 3),
            "hacking_level": alert.level,
            "tokens_today": cost["total_tokens"],
        })
    except Exception as exc:
        logger.error(f"健康检查失败：{exc}", exc_info=True)
        db.upsert_job_status("health_check", "error", {"error": str(exc)})


def job_evolution():
    """每天凌晨2点运行 Prompt 遗传算法。"""
    import datetime
    from contract import ContentType
    from evolution import run_evolution

    logger.info("=== Prompt 进化任务开始 ===")
    db.upsert_job_status("evolution", "running")

    if not _check_daily_budget():
        db.upsert_job_status("evolution", "success", {"skipped": "budget"})
        return

    weekday = datetime.datetime.now().weekday()
    content_type = list(ContentType)[weekday % len(list(ContentType))]
    logger.info(f"本次进化类型：{content_type.value}")

    try:
        report = run_evolution(content_type=content_type, population_size=6, generations=2, eval_n=2)
        logger.info(
            f"进化完成 | 最佳变体 id={report['best_variant_id']} "
            f"分数={report['best_score']:.2f} 提升={report['improvement']:+.2f}"
        )
        db.upsert_job_status("evolution", "success", {
            "type": content_type.value,
            "best_score": round(report["best_score"], 2),
            "improvement": round(report["improvement"], 2),
        })
    except Exception as exc:
        logger.error(f"Prompt 进化失败：{exc}", exc_info=True)
        db.upsert_job_status("evolution", "error", {"error": str(exc)})

    logger.info("=== Prompt 进化任务结束 ===")


def job_daily_report():
    """每天 23:55 生成项目日报。"""
    from strategist import generate_daily_report

    logger.info("=== 项目日报任务开始 ===")
    db.upsert_job_status("daily_report", "running")
    try:
        report = generate_daily_report()
        logger.info(f"项目日报生成完成：{report[:200]}")
        db.upsert_job_status("daily_report", "success", {"preview": report[:100]})
    except Exception as exc:
        logger.error(f"项目日报生成失败：{exc}", exc_info=True)
        db.upsert_job_status("daily_report", "error", {"error": str(exc)})
    logger.info("=== 项目日报任务结束 ===")


def main():
    db.init_db()
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    scheduler.add_job(job_heartbeat, "interval", minutes=1)
    scheduler.add_job(job_batch_generate, "cron", minute=0)
    scheduler.add_job(job_health_check, "cron", hour="0,6,12,18", minute=5)
    scheduler.add_job(job_evolution, "cron", hour=2, minute=0)
    scheduler.add_job(job_daily_report, "cron", hour=23, minute=55)

    logger.info("调度器启动，按 Ctrl+C 退出")
    logger.info(f"每日 token 上限：{DAILY_TOKEN_LIMIT:,}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
