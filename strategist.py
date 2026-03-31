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
from typing import Optional

import db
import humor_engine
from contract import ContentType, CONTENT_TYPE_LABELS


REVIEW_PROMPT_PATH = "prompts/strategist/review.txt"
SELF_LEARN_PROMPT_PATH = "prompts/strategist/self_learn.txt"
DAILY_REPORT_PROMPT_PATH = "prompts/strategist/daily_report.txt"
PERSONA_GEN_PROMPT_PATH = "prompts/strategist/persona_gen.txt"


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
        score_val = j.score.weighted_total if j.score else 0
        reasoning = j.score.reasoning if j.score else ""
        human = f"人工：{j.human_rating}分（{j.human_reaction}）" if j.human_rating else ""
        lines.append(f"[ID={j.id} 得分={score_val:.2f} {human}]\n{j.text}\n评审：{reasoning}")
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
            "SELECT * FROM jokes WHERE id > ? AND score_total IS NOT NULL ORDER BY id ASC",
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
    if len(jokes) < 10:
        return {"skipped": True, "reason": "数据不足"}

    high_score = [j for j in jokes if j.score and j.score.weighted_total >= 7.0]
    low_score = [j for j in jokes if j.score and j.score.weighted_total <= 4.0]
    human_feedback = [j for j in jokes if j.human_rating is not None]

    prompt = humor_engine._read_prompt(REVIEW_PROMPT_PATH).replace(
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

    latest_id = max(j.id for j in jokes if j.id is not None)
    db.set_last_strategist_joke_id(latest_id, db_path=db_path)

    return {
        "skipped": False,
        "processed_count": len(jokes),
        "success_patterns": saved_success,
        "failure_patterns": saved_failure,
        "humor_rules": saved_rules,
        "new_genes": saved_genes,
        "insight": insight,
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
            "SELECT COUNT(*) as total_count, AVG(score_total) as avg_score, "
            "MAX(score_total) as max_score, MIN(score_total) as min_score, "
            "SUM(CASE WHEN human_rating IS NOT NULL THEN 1 ELSE 0 END) as human_rated_count "
            "FROM jokes WHERE score_total IS NOT NULL"
        ).fetchone()

    prompt = humor_engine._read_prompt(SELF_LEARN_PROMPT_PATH).replace(
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

    return {
        "skipped": False,
        "meta_rules": saved_meta_rules,
        "contradictions": result.get("contradictions", []),
        "top_features": result.get("top_features", []),
        "evolution_direction": evolution_direction,
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
            "SELECT * FROM jokes WHERE substr(created_at, 1, 10) = ? AND score_total IS NOT NULL ORDER BY score_total DESC",
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
    avg_score = sum(j.score.weighted_total for j in jokes if j.score) / total_generated if total_generated else 0.0
    best_joke = jokes[0] if jokes else None
    max_score = best_joke.score.weighted_total if best_joke and best_joke.score else 0.0
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
    interval = int(os.getenv("STRATEGIST_TRIGGER_INTERVAL", "50"))
    last_id = db.get_last_strategist_joke_id(db_path=db_path)

    with db._connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM jokes WHERE score_total IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None

    latest_id = row["id"]
    if db.count_jokes_since(last_id, db_path=db_path) < interval:
        return None

    report = incremental_review(since_joke_id=last_id, db_path=db_path)

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
