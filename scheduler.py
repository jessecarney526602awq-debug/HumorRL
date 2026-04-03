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
# 每轮总周期（分钟）= 生成时长 + 战略师总结时间，默认 40（30生成+10总结）
CYCLE_INTERVAL_MINUTES = int(os.getenv("CYCLE_INTERVAL_MINUTES", "40"))
# 单轮生成窗口（分钟），窗口内循环调用 API 尽可能多生成
GENERATE_WINDOW_MINUTES = int(os.getenv("GENERATE_WINDOW_MINUTES", "28"))
# 每次 API 调用生成几条候选（并行评分后全存）
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5"))
# 今日训练的内容类型，对应 ContentType 枚举值，如 text_joke / standup / cold_joke 等
DAILY_CONTENT_TYPE = os.getenv("DAILY_CONTENT_TYPE", "text_joke")


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


def job_training_cycle():
    """
    完整训练周期（每 CYCLE_INTERVAL_MINUTES 分钟执行一次）：
      1. [GENERATE_WINDOW_MINUTES 分钟内] 循环生成 DAILY_CONTENT_TYPE 类型，全量存入
      2. 生成窗口结束后，战略师强制复盘，下发下一轮指令
    """
    from contract import ContentType
    from strategist import incremental_review

    try:
        content_type = ContentType(DAILY_CONTENT_TYPE)
    except ValueError:
        logger.error(f"DAILY_CONTENT_TYPE='{DAILY_CONTENT_TYPE}' 不是有效的 ContentType，跳过")
        db.upsert_job_status("batch_generate", "error", {"error": f"invalid type: {DAILY_CONTENT_TYPE}"})
        return

    logger.info(f"=== 训练周期开始 | 类型={content_type.value} | 窗口={GENERATE_WINDOW_MINUTES}分钟 ===")
    db.upsert_job_status("batch_generate", "running")

    # ── 阶段一：生成窗口 ──────────────────────────────────────────────
    alert = monitor.detect_reward_hacking()
    if alert.level >= 2:
        logger.warning(f"Reward Hacking L{alert.level}，本轮跳过生成：{alert.message}")
        db.upsert_job_status("batch_generate", "success", {"skipped": f"hacking_l{alert.level}"})
        return

    rank_quality = monitor.check_rank_quality()
    if rank_quality.sample_count >= 5 and rank_quality.avg_anchor_accuracy < 0.5:
        logger.warning(
            "Rank 锚点准确率 %.3f 过低，跳过本轮生成：%s",
            rank_quality.avg_anchor_accuracy,
            rank_quality.interpretation,
        )
        db.upsert_job_status("batch_generate", "success", {"skipped": "rank_quality_low"})
        return

    total_saved = 0
    total_score = 0.0
    round_num = 0
    deadline = time.time() + GENERATE_WINDOW_MINUTES * 60

    while time.time() < deadline:
        if db.get_stop_flag():
            logger.info("收到手动停止指令，提前结束生成窗口")
            db.set_stop_flag(False)
            break
        if not _check_daily_budget():
            logger.warning("token 预算耗尽，提前结束生成窗口")
            break
        round_num += 1
        try:
            req = GenerationRequest(content_type=content_type, n=BATCH_SIZE)
            jokes, group_result = humor_engine.generate_and_rank_all(req)
            saved_ids = []
            for joke in jokes:
                saved_id = db.save_joke(joke)
                saved_ids.append(saved_id)
                total_score += joke.effective_reward
                total_saved += 1
            if saved_ids:
                ranking_order = [
                    saved_ids[pos.text_index]
                    for pos in sorted(group_result.positions, key=lambda pos: pos.rank)
                    if 0 <= pos.text_index < len(saved_ids)
                ]
                funny_flags = [
                    jokes[pos.text_index].is_funny
                    for pos in sorted(group_result.positions, key=lambda pos: pos.rank)
                    if 0 <= pos.text_index < len(jokes)
                ]
                anchor_ids = [
                    int(pos.candidate_id)
                    for pos in group_result.anchor_positions
                    if str(pos.candidate_id).isdigit()
                ]
                db.save_rank_comparison(
                    content_type=content_type.value,
                    joke_ids=saved_ids,
                    ranking_order=ranking_order,
                    funny_flags=[bool(flag) for flag in funny_flags],
                    anchor_ids=anchor_ids,
                    anchor_accuracy=group_result.anchor_accuracy,
                    model=group_result.model,
                    raw_response=group_result.raw_response,
                )
            avg_r = total_score / total_saved if total_saved else 0
            logger.info(
                f"  第{round_num}轮完成，本轮{len(jokes)}条，累计{total_saved}条，"
                f"平均奖励{avg_r:.2f}，锚点准确率={group_result.anchor_accuracy:.2f}"
            )
        except Exception as exc:
            logger.error(f"  第{round_num}轮生成失败：{exc}", exc_info=True)
            time.sleep(10)  # 出错后稍等再试

    avg_score = total_score / total_saved if total_saved else 0.0
    logger.info(f"生成窗口结束：共 {round_num} 轮，{total_saved} 条，平均奖励 {avg_score:.2f}")

    db.upsert_job_status("batch_generate", "success", {
        "saved": total_saved, "rounds": round_num, "avg_score": round(avg_score, 2),
        "type": content_type.value,
    })

    # ── 阶段二：战略师强制复盘 ─────────────────────────────────────────
    if total_saved == 0:
        logger.warning("本轮无新内容，跳过战略师复盘")
        return

    logger.info("=== 战略师复盘开始 ===")
    db.upsert_job_status("daily_report", "running")
    try:
        last_id = db.get_last_strategist_joke_id()
        result = incremental_review(since_joke_id=last_id)
        if result.get("skipped"):
            logger.info(f"战略师复盘跳过：{result.get('reason')}")
        else:
            n_rules = len(result.get("humor_rules", []))
            n_genes = len(result.get("new_genes", []))
            directive = result.get("next_directive", "")
            logger.info(f"战略师复盘完成 | 规律={n_rules} 基因={n_genes}")
            logger.info(f"下轮生成指令：{directive[:80]}")
        db.upsert_job_status("daily_report", "success", {"preview": str(result.get("insight", ""))[:80]})
    except Exception as exc:
        logger.error(f"战略师复盘失败：{exc}", exc_info=True)
        db.upsert_job_status("daily_report", "error", {"error": str(exc)})

    logger.info(f"=== 训练周期结束，下一轮将在 {CYCLE_INTERVAL_MINUTES - GENERATE_WINDOW_MINUTES} 分钟后开始 ===")


def job_health_check():
    """定时健康检查（每6小时执行一次）。"""
    logger.info("=== 健康检查 ===")
    db.upsert_job_status("health_check", "running")
    try:
        diversity = monitor.compute_diversity()
        logger.info(f"多样性熵：{diversity.entropy:.3f}（{diversity.interpretation}）")

        alert = monitor.detect_reward_hacking()
        logger.info(f"Reward Hacking Level={alert.level}，{alert.message}")

        rank_quality = monitor.check_rank_quality()
        logger.info(
            "Rank 质量：anchor_acc=%.3f not_funny=%.1f%%（%s）",
            rank_quality.avg_anchor_accuracy,
            rank_quality.not_funny_ratio * 100,
            rank_quality.interpretation,
        )

        cost = db.get_cost_stats(days=1)
        logger.info(f"今日 token 用量：{cost['total_tokens']:,} / {DAILY_TOKEN_LIMIT:,}")

        db.upsert_job_status("health_check", "success", {
            "diversity": round(diversity.entropy, 3),
            "hacking_level": alert.level,
            "tokens_today": cost["total_tokens"],
            "anchor_accuracy": rank_quality.avg_anchor_accuracy,
            "not_funny_ratio": rank_quality.not_funny_ratio,
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


def job_weekly_calibration():
    """每周一凌晨 3 点运行 Judge 校准。"""
    from calibration import run_calibration, run_rank_calibration

    logger.info("=== Judge 校准任务开始 ===")
    db.upsert_job_status("calibration", "running")

    if not _check_daily_budget():
        db.upsert_job_status("calibration", "success", {"skipped": "budget"})
        return

    try:
        result = run_calibration()
        rank_result = run_rank_calibration()
        logger.info(
            "点分校准完成 | Spearman=%.3f 好笑识别=%.1f%% 不好笑识别=%.1f%%",
            result["overall_spearman"],
            result["classification_accuracy"]["funny_identified"] * 100,
            result["classification_accuracy"]["not_funny_identified"] * 100,
        )
        logger.info(
            "排序校准完成 | Spearman=%.3f 好笑识别=%.1f%% 不好笑识别=%.1f%% 锚点=%.1f%%",
            rank_result["overall_spearman"],
            rank_result["classification_accuracy"]["funny_identified"] * 100,
            rank_result["classification_accuracy"]["not_funny_identified"] * 100,
            rank_result["classification_accuracy"]["avg_anchor_accuracy"] * 100,
        )
        db.upsert_job_status(
            "calibration",
            "success",
            {
                "spearman": round(result["overall_spearman"], 3),
                "rank_spearman": round(rank_result["overall_spearman"], 3),
                "lessons_count": len(result["lessons"]),
            },
        )
    except Exception as exc:
        logger.error(f"Judge 校准失败：{exc}", exc_info=True)
        db.upsert_job_status("calibration", "error", {"error": str(exc)})

    logger.info("=== Judge 校准任务结束 ===")


def main():
    db.init_db()
    try:
        from strategist import export_memory_snapshot

        export_memory_snapshot()
    except Exception as exc:
        logger.warning(f"初始化战略师记忆文件失败：{exc}")
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    scheduler.add_job(job_heartbeat, "interval", minutes=1)
    # 核心训练周期：生成窗口 + 战略师复盘，串行在一个 job 里
    scheduler.add_job(job_training_cycle, "interval", minutes=CYCLE_INTERVAL_MINUTES)
    scheduler.add_job(job_health_check, "cron", hour="0,6,12,18", minute=5)
    scheduler.add_job(job_evolution, "cron", hour=2, minute=0)
    scheduler.add_job(job_daily_report, "cron", hour=23, minute=55)
    scheduler.add_job(job_weekly_calibration, "cron", day_of_week="mon", hour=3, minute=0)

    logger.info("调度器启动，按 Ctrl+C 退出")
    logger.info(f"今日训练类型：{DAILY_CONTENT_TYPE}")
    logger.info(f"周期：{GENERATE_WINDOW_MINUTES}分钟生成 + ~{CYCLE_INTERVAL_MINUTES - GENERATE_WINDOW_MINUTES}分钟战略师复盘，总间隔={CYCLE_INTERVAL_MINUTES}分钟")
    logger.info(f"每次 API 调用：{BATCH_SIZE} 条候选")
    logger.info(f"每日 token 上限：{DAILY_TOKEN_LIMIT:,}")
    logger.info("Judge 校准：每周一 03:00")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
