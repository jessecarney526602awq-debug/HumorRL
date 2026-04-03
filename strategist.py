"""
HumorRL — 战略师
- 每50条新数据触发一次增量复盘
- 自学习：定期对知识库进行二次提炼
- 每日生成项目报告
"""

import datetime
import json
import os
import re
from pathlib import Path
from typing import Optional

import db
import humor_engine
from contract import ContentType, CONTENT_TYPE_LABELS


REVIEW_PROMPT_PATH = "prompts/strategist/review.txt"
SELF_LEARN_PROMPT_PATH = "prompts/strategist/self_learn.txt"
DAILY_REPORT_PROMPT_PATH = "prompts/strategist/daily_report.txt"
PERSONA_GEN_PROMPT_PATH = "prompts/strategist/persona_gen.txt"
THEORY_FOUNDATION_PATH = "prompts/strategist/theory_foundation.txt"
HUMOR_REFERENCE_PATH = "prompts/reference/humor_cases.txt"
PROJECT_ROOT = Path(__file__).resolve().parent
STRATEGIST_MEMORY_PATH = Path(
    os.getenv("STRATEGIST_MEMORY_PATH", str(PROJECT_ROOT / "data" / "strategist_memory.md"))
)
STRATEGIST_MANUAL_PATH = Path(
    os.getenv("STRATEGIST_MANUAL_PATH", str(PROJECT_ROOT / "data" / "strategist_manual.md"))
)
STRATEGIST_MANUAL_TEMPLATE = """# Strategist Manual Instructions

把这里当成“人工长期干预区”。
你后续想固定给战略师的规则、禁令、偏好、目标，都写在这里。

建议写法：
- 长期目标：比如“优先训练更贴近日常共鸣的文字幽默”
- 硬性禁令：比如“不要为了高分重复同一类老谐音”
- 人工观察：比如“最近职场题材更稳定，继续深挖”
- 临时策略：比如“未来几轮优先看旅行/租房/办公室”

说明：
- 这里的内容优先级高于战略师自己的临时判断
- 不想用了，直接删掉对应条目即可
"""


def _load_theory_foundation() -> str:
    """加载幽默底层理论参考，失败时静默返回空字符串。"""
    try:
        return humor_engine._read_prompt(THEORY_FOUNDATION_PATH)
    except Exception:
        return ""


def _load_humor_reference() -> str:
    """加载用户提供的幽默案例参考，失败时返回空字符串。"""
    try:
        return humor_engine._read_prompt(HUMOR_REFERENCE_PATH)
    except Exception:
        return "（暂无额外案例参考）"


def _ensure_manual_file() -> None:
    """确保人工固定指令文件存在，便于长期人工干预。"""
    STRATEGIST_MANUAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not STRATEGIST_MANUAL_PATH.exists():
        STRATEGIST_MANUAL_PATH.write_text(STRATEGIST_MANUAL_TEMPLATE, encoding="utf-8")


def load_manual_directives() -> str:
    """读取人工固定指令；文件不存在时自动创建模板。"""
    _ensure_manual_file()
    text = STRATEGIST_MANUAL_PATH.read_text(encoding="utf-8").strip()
    return text or "（暂无人工固定指令）"


def build_memory_markdown(db_path: str = db.DB_PATH) -> str:
    """把战略师经验导出成稳定的 Markdown 记忆文件。"""
    current_generation = db.get_current_directive(db_path=db_path) or "（暂无）"
    current_judge = db.get_current_judge_directive(db_path=db_path) or "（暂无）"
    latest_calibration = db.get_latest_calibration(db_path=db_path)
    latest_report = db.get_daily_reports(limit=1, db_path=db_path)
    latest_report_md = latest_report[0]["report_md"].strip() if latest_report else "（暂无）"

    sections = [
        "# Strategist Memory",
        f"- 导出时间：{datetime.datetime.now().isoformat(timespec='seconds')}",
        f"- 人工固定指令文件：{STRATEGIST_MANUAL_PATH}",
        "",
        "## Current Generation Directive",
        current_generation,
        "",
        "## Current Judge Directive",
        current_judge,
    ]

    if latest_calibration:
        sections.extend(
            [
                "",
                "## Latest Judge Calibration",
                f"- 运行日期：{latest_calibration.get('run_date', 'N/A')}",
                f"- 相关性：{latest_calibration.get('overall_correlation', 'N/A')}",
                f"- 分类准确率：{latest_calibration.get('classification_accuracy', {})}",
                "",
                str(latest_calibration.get("report_md", "（暂无）")).strip(),
            ]
        )

    for entry_type, title in [
        ("success_pattern", "Success Patterns"),
        ("failure_pattern", "Failure Patterns"),
        ("humor_rule", "Humor Rules"),
        ("writer_lesson", "Writer Lessons"),
        ("judge_lesson", "Judge Lessons"),
        ("gene", "Genes"),
        ("insight", "Insights"),
    ]:
        rows = db.get_knowledge(entry_type=entry_type, limit=12, db_path=db_path)
        sections.extend(["", f"## {title}"])
        if rows:
            sections.extend(f"- {row['content']}" for row in rows)
        else:
            sections.append("（暂无）")

    sections.extend(["", "## Latest Daily Report", latest_report_md])
    return "\n".join(sections).strip() + "\n"


def export_memory_snapshot(db_path: str = db.DB_PATH) -> str:
    """把战略师当前经验写入固定 Markdown 文件。"""
    STRATEGIST_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = build_memory_markdown(db_path=db_path)
    STRATEGIST_MEMORY_PATH.write_text(text, encoding="utf-8")
    return text


def load_memory_snapshot(db_path: str = db.DB_PATH) -> str:
    """优先读取已导出的经验文件；没有时现导出一份。"""
    if STRATEGIST_MEMORY_PATH.exists():
        text = STRATEGIST_MEMORY_PATH.read_text(encoding="utf-8").strip()
        if text:
            return text
    return export_memory_snapshot(db_path=db_path).strip()


def _pro_chat(prompt: str, max_tokens: int = 2000) -> str:
    """调用豆包 pro，自动剥离 <think> 块。"""
    model = os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2.0-pro-250315")
    client = humor_engine._strategist_client()
    raw = humor_engine._chat(
        client,
        model,
        prompt,
        temperature=0.3,
        max_tokens=max_tokens,
        role="strategist",
    )
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw


def _parse_json(raw: str) -> dict | list:
    """健壮的 JSON 解析，兼容 markdown 代码块。"""
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def _format_cases(jokes: list, limit: int = 5) -> str:
    lines = []
    for j in jokes[:limit]:
        score_val = j.effective_reward
        reasoning = j.score.reasoning if j.score else ""
        route = ""
        if j.score and (j.score.judge_shape or j.score.judge_subtype):
            route = (
                f"JudgeRoute={j.score.judge_shape or 'unknown'}"
                f"/{j.score.judge_subtype or 'general'}"
            )
        display = ""
        if j.score and j.score.display_score is not None:
            display = f" 展示分={j.score.display_score:.1f}（{j.score.display_band or '未分段'}）"
        structure = ""
        if j.score and j.score.structure_summary:
            structure = (
                f"\n结构摘要：{j.score.structure_summary}"
                f"\n最强点：{j.score.best_moment or '（暂无）'}"
                f"\n最弱点：{j.score.weakest_moment or '（暂无）'}"
            )
        rank = ""
        if j.rank_position is not None:
            funny_label = "好笑" if j.is_funny else "不好笑"
            rank = (
                f" 排名={j.rank_position}/{j.rank_group_size or '?'}"
                f" rank_reward={j.rank_score or 0:.2f} {funny_label}"
            )
        human = f"人工：{j.human_rating}分（{j.human_reaction}）" if j.human_rating else ""
        lines.append(
            f"[ID={j.id} 得分={score_val:.2f}{display}{rank} {route} {human}]\n"
            f"{j.text}\n评审：{reasoning}{structure}\n排序理由：{j.rank_justification or '（暂无）'}"
        )
    return "\n---\n".join(lines) or "（暂无）"


def _knowledge_summary(content_type: Optional[str] = None, db_path: str = db.DB_PATH) -> str:
    """把知识库已有规律格式化为 prompt 中的摘要文本。"""
    sections = []
    for et, label in [
        ("success_pattern", "成功规律"),
        ("failure_pattern", "失败规律"),
        ("humor_rule", "幽默底层规律"),
        ("insight", "历史洞察"),
    ]:
        entries = db.get_knowledge(entry_type=et, content_type=content_type, limit=10, db_path=db_path)
        if entries:
            items = "\n".join(f"- {e['content']}" for e in entries)
            sections.append(f"### {label}\n{items}")
    return "\n\n".join(sections) or "（知识库尚为空）"


def _load_scored_jokes_since(since_joke_id: int, db_path: str) -> list:
    with db._connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM jokes WHERE id > ? AND COALESCE(rank_score, score_total) IS NOT NULL ORDER BY id ASC",
            (since_joke_id,),
        ).fetchall()
    return [db._row_to_joke_record(row) for row in rows]


def incremental_review(
    since_joke_id: int,
    db_path: str = db.DB_PATH,
) -> dict:
    """
    增量复盘：只处理 id > since_joke_id 的新数据。
    对所有内容类型一起分析（跨类型规律更有价值）。
    """
    jokes = _load_scored_jokes_since(since_joke_id, db_path)
    if len(jokes) < 5:
        return {"skipped": True, "reason": "数据不足（最少需要5条）"}

    high_score = [j for j in jokes if j.effective_reward >= 7.0]
    low_score = [j for j in jokes if j.effective_reward <= 4.0]
    human_feedback = [j for j in jokes if j.human_rating is not None]

    prompt = humor_engine._read_prompt(REVIEW_PROMPT_PATH).replace(
        "{theory_foundation}",
        _load_theory_foundation(),
    ).replace(
        "{humor_reference}",
        _load_humor_reference(),
    ).replace(
        "{existing_knowledge}",
        _knowledge_summary(db_path=db_path),
    ).replace(
        "{batch_size}",
        str(len(jokes)),
    ).replace(
        "{high_score_cases}",
        _format_cases(high_score),
    ).replace(
        "{low_score_cases}",
        _format_cases(low_score),
    ).replace(
        "{human_feedback}",
        _format_cases(human_feedback),
    )
    prompt += (
        "\n\n### 战略师经验记忆（Markdown 快照）\n"
        f"{load_memory_snapshot(db_path=db_path)}"
        "\n\n### 人工固定指令（最高优先级，必须长期遵守）\n"
        f"{load_manual_directives()}"
    )

    result = _parse_json(_pro_chat(prompt))
    source_ids = [j.id for j in jokes if j.id is not None]

    existing = {entry["content"] for entry in db.get_knowledge(limit=1000, db_path=db_path)}

    def _save_many(entry_type: str, items: list[str], relevance_score: float = 1.0) -> list[str]:
        saved = []
        for item in items:
            item = str(item).strip()
            if not item or item in existing:
                continue
            db.save_knowledge(
                entry_type=entry_type,
                content=item,
                source_joke_ids=source_ids,
                relevance_score=relevance_score,
                db_path=db_path,
            )
            existing.add(item)
            saved.append(item)
        return saved

    saved_success = _save_many("success_pattern", result.get("success_patterns", []), 1.1)
    saved_failure = _save_many("failure_pattern", result.get("failure_patterns", []), 1.0)
    saved_rules = _save_many("humor_rule", result.get("humor_rules", []), 1.2)
    saved_genes = _save_many("gene", result.get("new_genes", []), 1.1)

    insight = str(result.get("insight", "")).strip()
    if insight and insight not in existing:
        db.save_knowledge(
            entry_type="insight",
            content=insight,
            source_joke_ids=source_ids,
            relevance_score=float(result.get("confidence", 0.8) or 0.8),
            db_path=db_path,
        )
        existing.add(insight)

    # 保存生成指令（战略师 → 生成端 的直接传递）
    next_directive = str(result.get("next_directive", "")).strip()
    if next_directive:
        db.save_knowledge(
            entry_type="generation_directive",
            content=next_directive,
            source_joke_ids=source_ids,
            relevance_score=1.5,
            db_path=db_path,
        )

    judge_directive = str(result.get("judge_directive", "")).strip()
    if judge_directive:
        db.save_knowledge(
            entry_type="judge_directive",
            content=judge_directive,
            source_joke_ids=source_ids,
            relevance_score=1.4,
            db_path=db_path,
        )

    for lesson in result.get("writer_lessons", []):
        lesson = str(lesson).strip()
        if lesson and lesson not in existing:
            db.save_knowledge(
                entry_type="writer_lesson",
                content=lesson,
                source_joke_ids=source_ids,
                relevance_score=1.2,
                db_path=db_path,
            )
            existing.add(lesson)

    for lesson in result.get("judge_lessons", []):
        lesson = str(lesson).strip()
        if lesson and lesson not in existing:
            db.save_knowledge(
                entry_type="judge_lesson",
                content=lesson,
                source_joke_ids=source_ids,
                relevance_score=1.3,
                db_path=db_path,
            )
            existing.add(lesson)

    latest_id = max(j.id for j in jokes if j.id is not None)
    db.set_last_strategist_joke_id(latest_id, db_path=db_path)
    export_memory_snapshot(db_path=db_path)

    return {
        "skipped": False,
        "processed_count": len(jokes),
        "success_patterns": saved_success,
        "failure_patterns": saved_failure,
        "humor_rules": saved_rules,
        "new_genes": saved_genes,
        "insight": insight,
        "next_directive": next_directive,
        "judge_directive": judge_directive,
        "writer_lessons": [str(item).strip() for item in result.get("writer_lessons", []) if str(item).strip()],
        "judge_lessons": [str(item).strip() for item in result.get("judge_lessons", []) if str(item).strip()],
        "best_joke_id": result.get("best_joke_id"),
        "confidence": float(result.get("confidence", 0.0) or 0.0),
    }


def self_learn(db_path: str = db.DB_PATH) -> dict:
    """
    二次自学习：对知识库进行元层次提炼。
    每运行5次 incremental_review 后触发一次（通过计数器控制）。
    """
    all_entries = db.get_knowledge(limit=1000, db_path=db_path)
    usable_entries = [entry for entry in all_entries if entry["entry_type"] != "_checkpoint"]
    if len(usable_entries) < 10:
        return {"skipped": True}

    success_patterns = "\n".join(f"- {e['content']}" for e in usable_entries if e["entry_type"] == "success_pattern") or "（暂无）"
    failure_patterns = "\n".join(f"- {e['content']}" for e in usable_entries if e["entry_type"] == "failure_pattern") or "（暂无）"
    humor_rules = "\n".join(f"- {e['content']}" for e in usable_entries if e["entry_type"] == "humor_rule") or "（暂无）"

    with db._connect(db_path) as conn:
        stats = conn.execute(
            "SELECT COUNT(*) as total_count, AVG(COALESCE(rank_score, score_total)) as avg_score, "
            "MAX(COALESCE(rank_score, score_total)) as max_score, MIN(COALESCE(rank_score, score_total)) as min_score, "
            "SUM(CASE WHEN human_rating IS NOT NULL THEN 1 ELSE 0 END) as human_rated_count "
            "FROM jokes WHERE COALESCE(rank_score, score_total) IS NOT NULL"
        ).fetchone()

    prompt = humor_engine._read_prompt(SELF_LEARN_PROMPT_PATH).replace(
        "{theory_foundation}", _load_theory_foundation()
    ).replace(
        "{humor_reference}", _load_humor_reference()
    ).replace(
        "{success_patterns}", success_patterns
    ).replace(
        "{failure_patterns}", failure_patterns
    ).replace(
        "{humor_rules}", humor_rules
    ).replace(
        "{total_count}", str(stats["total_count"] or 0)
    ).replace(
        "{avg_score}", f"{float(stats['avg_score'] or 0):.2f}"
    ).replace(
        "{max_score}", f"{float(stats['max_score'] or 0):.2f}"
    ).replace(
        "{min_score}", f"{float(stats['min_score'] or 0):.2f}"
    ).replace(
        "{human_rated_count}", str(stats["human_rated_count"] or 0)
    )
    prompt += (
        "\n\n### 战略师经验记忆（Markdown 快照）\n"
        f"{load_memory_snapshot(db_path=db_path)}"
        "\n\n### 人工固定指令（最高优先级，必须长期遵守）\n"
        f"{load_manual_directives()}"
    )

    result = _parse_json(_pro_chat(prompt))
    saved_meta_rules = []
    for item in result.get("meta_rules", []):
        item = str(item).strip()
        if item:
            db.save_knowledge("humor_rule", item, relevance_score=1.3, db_path=db_path)
            saved_meta_rules.append(item)

    evolution_direction = str(result.get("evolution_direction", "")).strip()
    if evolution_direction:
        db.save_knowledge("insight", evolution_direction, relevance_score=1.2, db_path=db_path)

    judge_focus = str(result.get("judge_focus", "")).strip()
    if judge_focus:
        db.save_knowledge("judge_directive", judge_focus, relevance_score=1.35, db_path=db_path)

    export_memory_snapshot(db_path=db_path)

    return {
        "skipped": False,
        "meta_rules": saved_meta_rules,
        "contradictions": result.get("contradictions", []),
        "top_features": result.get("top_features", []),
        "evolution_direction": evolution_direction,
        "judge_focus": judge_focus,
    }


def generate_daily_report(
    report_date: Optional[str] = None,
    db_path: str = db.DB_PATH,
) -> str:
    """
    生成日报并存入 DB。
    """
    report_date = report_date or datetime.date.today().isoformat()

    with db._connect(db_path) as conn:
        jokes_rows = conn.execute(
            "SELECT * FROM jokes WHERE substr(created_at, 1, 10) = ? "
            "AND COALESCE(rank_score, score_total) IS NOT NULL "
            "ORDER BY COALESCE(rank_score, score_total) DESC",
            (report_date,),
        ).fetchall()
        jokes = [db._row_to_joke_record(row) for row in jokes_rows]
        dist_rows = conn.execute(
            "SELECT content_type, COUNT(*) as cnt FROM jokes "
            "WHERE substr(created_at, 1, 10) = ? GROUP BY content_type",
            (report_date,),
        ).fetchall()
        kb_today = conn.execute(
            "SELECT * FROM knowledge_base WHERE substr(created_at, 1, 10) = ?",
            (report_date,),
        ).fetchall()
        kb_total = conn.execute("SELECT COUNT(*) FROM knowledge_base WHERE entry_type != '_checkpoint'").fetchone()[0]
        humor_rules_count = conn.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE entry_type = 'humor_rule'"
        ).fetchone()[0]

    total_generated = len(jokes)
    avg_score = sum(j.effective_reward for j in jokes) / total_generated if total_generated else 0.0
    best_joke = jokes[0] if jokes else None
    max_score = best_joke.effective_reward if best_joke else 0.0
    best_joke_id = best_joke.id if best_joke else None
    best_joke_text = best_joke.text if best_joke else "（今日暂无带评分内容）"
    type_distribution = {row["content_type"]: row["cnt"] for row in dist_rows}

    new_genes_count = sum(1 for row in kb_today if row["entry_type"] == "gene")
    new_patterns_count = sum(
        1 for row in kb_today if row["entry_type"] in {"success_pattern", "failure_pattern", "humor_rule"}
    )
    insight_rows = [row for row in kb_today if row["entry_type"] == "insight"]
    daily_insight = insight_rows[-1]["content"] if insight_rows else "（今日暂无新洞察）"

    prompt = humor_engine._read_prompt(DAILY_REPORT_PROMPT_PATH).format(
        report_date=report_date,
        total_generated=total_generated,
        avg_score=avg_score,
        max_score=max_score,
        best_joke_id=best_joke_id if best_joke_id is not None else "N/A",
        type_distribution=type_distribution,
        best_joke_text=best_joke_text,
        new_genes_count=new_genes_count,
        new_patterns_count=new_patterns_count,
        daily_insight=daily_insight,
        total_kb_entries=kb_total,
        humor_rules_count=humor_rules_count,
    )

    report_md = _pro_chat(prompt, max_tokens=2500)
    db.save_daily_report(
        report_date=report_date,
        total_generated=total_generated,
        avg_score=avg_score,
        new_patterns=new_patterns_count,
        best_joke_id=best_joke_id,
        report_md=report_md,
        db_path=db_path,
    )
    return report_md


def maybe_trigger(db_path: str = db.DB_PATH) -> Optional[dict]:
    """
    检查是否需要触发战略师复盘。
    条件：距上次运行后新增 >= STRATEGIST_TRIGGER_INTERVAL 条（默认50）。
    """
    interval = max(int(os.getenv("STRATEGIST_TRIGGER_INTERVAL", "5")), 5)
    last_id = db.get_last_strategist_joke_id(db_path=db_path)

    with db._connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM jokes WHERE COALESCE(rank_score, score_total) IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None

    latest_id = row["id"]
    if db.count_jokes_since(last_id, db_path=db_path) < interval:
        return None

    report = incremental_review(since_joke_id=last_id, db_path=db_path)
    if report.get("skipped"):
        return report

    kb_count = len([e for e in db.get_knowledge(limit=1000, db_path=db_path) if e["entry_type"] != "_checkpoint"])
    if kb_count > 0 and kb_count % 5 == 0:
        self_learn(db_path=db_path)

    db.set_last_strategist_joke_id(latest_id, db_path=db_path)
    return report


def generate_persona_style(
    name_input: str,
    background: str,
    db_path: str = db.DB_PATH,
) -> dict:
    """
    根据用户输入的背景描述，用战略师生成 Persona 的 style_prompt。
    返回 {"name": str, "description": str, "style_prompt": str}
    失败时抛出 RuntimeError。
    """
    prompt = (
        humor_engine._read_prompt(PERSONA_GEN_PROMPT_PATH)
        .replace("{name_input}", name_input.strip() or "（用户未提供）")
        .replace("{background}", background.strip())
    )
    result = _parse_json(_pro_chat(prompt, max_tokens=600))
    style_prompt = str(result.get("style_prompt", "")).strip()
    if not style_prompt:
        raise RuntimeError("AI 未返回有效的 style_prompt")
    return {
        "name": str(result.get("name", "")).strip() or name_input or "自定义角色",
        "description": str(result.get("description", "")).strip(),
        "style_prompt": style_prompt,
    }


_ensure_manual_file()
