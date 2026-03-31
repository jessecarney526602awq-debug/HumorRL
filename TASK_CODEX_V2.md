# Codex 任务单 V2 — 战略师 + 自主训练 + Persona AI 编辑

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
>
> **先读**：CLAUDE.md / humor_engine.py / db.py / app.py / contract.py

---

## 背景

P3 已完成（monitor.py / strategy.py / evolution.py / scheduler.py 都在）。
本次任务：
1. 实现战略师（strategist.py + DB 扩展）
2. 监控页增加「自主训练」按钮
3. Persona 页面升级为 AI 辅助创建 + 编辑流程

---

## 任务一：修改 `db.py` — 追加 knowledge_base + daily_reports 表

### SCHEMA 末尾追加（加入 SCHEMA 字符串）

```sql
CREATE TABLE IF NOT EXISTS knowledge_base (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT,
    entry_type      TEXT    NOT NULL,
    content         TEXT    NOT NULL,
    source_joke_ids TEXT    NOT NULL DEFAULT '',
    relevance_score REAL    NOT NULL DEFAULT 1.0,
    used_count      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_entry_type ON knowledge_base(entry_type);
CREATE INDEX IF NOT EXISTS idx_kb_ct         ON knowledge_base(content_type);
CREATE INDEX IF NOT EXISTS idx_kb_score      ON knowledge_base(relevance_score DESC);

CREATE TABLE IF NOT EXISTS daily_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date     TEXT    NOT NULL UNIQUE,
    total_generated INTEGER NOT NULL DEFAULT 0,
    avg_score       REAL    NOT NULL DEFAULT 0.0,
    new_patterns    INTEGER NOT NULL DEFAULT 0,
    best_joke_id    INTEGER,
    report_md       TEXT    NOT NULL,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date DESC);
```

### 追加函数

```python
def save_knowledge(
    entry_type: str,
    content: str,
    content_type: Optional[str] = None,
    source_joke_ids: list = None,
    relevance_score: float = 1.0,
    db_path: str = DB_PATH,
) -> int:
    now = _now()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_base "
            "(content_type, entry_type, content, source_joke_ids, relevance_score, used_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (content_type, entry_type, content,
             ",".join(str(i) for i in (source_joke_ids or [])),
             relevance_score, now, now),
        )
        return cur.lastrowid


def get_knowledge(
    entry_type: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 20,
    db_path: str = DB_PATH,
) -> list[dict]:
    conditions, params = ["1=1"], []
    if entry_type:
        conditions.append("entry_type = ?")
        params.append(entry_type)
    if content_type:
        conditions.append("(content_type = ? OR content_type IS NULL)")
        params.append(content_type)
    params.append(limit)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM knowledge_base WHERE {' AND '.join(conditions)} "
            f"ORDER BY relevance_score DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def get_dynamic_gene_pool(
    content_type: Optional[str] = None,
    limit: int = 30,
    db_path: str = DB_PATH,
) -> list[str]:
    rows = get_knowledge(entry_type="gene", content_type=content_type,
                         limit=limit, db_path=db_path)
    return [r["content"] for r in rows]


def increment_knowledge_used(knowledge_id: int, db_path: str = DB_PATH) -> None:
    now = _now()
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE knowledge_base SET used_count=used_count+1, updated_at=? WHERE id=?",
            (now, knowledge_id),
        )


def save_daily_report(
    report_date: str,
    total_generated: int,
    avg_score: float,
    new_patterns: int,
    best_joke_id: Optional[int],
    report_md: str,
    db_path: str = DB_PATH,
) -> int:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM daily_reports WHERE report_date = ?", (report_date,))
        cur = conn.execute(
            "INSERT INTO daily_reports "
            "(report_date, total_generated, avg_score, new_patterns, best_joke_id, report_md, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (report_date, total_generated, avg_score, new_patterns,
             best_joke_id, report_md, _now()),
        )
        return cur.lastrowid


def get_daily_reports(limit: int = 7, db_path: str = DB_PATH) -> list[dict]:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def count_jokes_since(since_id: int, db_path: str = DB_PATH) -> int:
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jokes WHERE id > ? AND score_total IS NOT NULL",
            (since_id,),
        ).fetchone()[0]


def get_last_strategist_joke_id(db_path: str = DB_PATH) -> int:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM knowledge_base WHERE entry_type='_checkpoint' LIMIT 1"
        ).fetchone()
    return int(row["content"]) if row else 0


def set_last_strategist_joke_id(joke_id: int, db_path: str = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM knowledge_base WHERE entry_type='_checkpoint'")
        conn.execute(
            "INSERT INTO knowledge_base (entry_type, content, source_joke_ids, "
            "relevance_score, created_at, updated_at) VALUES ('_checkpoint', ?, '', 0, ?, ?)",
            (str(joke_id), _now(), _now()),
        )


def update_persona(
    persona_id: int,
    name: str,
    description: str,
    style_prompt: str,
    db_path: str = DB_PATH,
) -> None:
    """更新 persona 信息（用于 AI 辅助编辑后保存）。"""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE personas SET name=?, description=?, style_prompt=? WHERE id=?",
            (name, description, style_prompt, persona_id),
        )


def delete_persona(persona_id: int, db_path: str = DB_PATH) -> None:
    """删除自定义 persona（仅非预设）。"""
    with _connect(db_path) as conn:
        conn.execute(
            "DELETE FROM personas WHERE id=? AND is_preset=0",
            (persona_id,),
        )
```

---

## 任务二：新建 Prompt 模板

### `prompts/strategist/review.txt`

```
你是 HumorRL 系统的战略顾问，专门分析中文幽默内容的生成规律。

## 已掌握的历史规律（知识库摘要）
{existing_knowledge}

## 本批次新数据（最近 {batch_size} 条，含评分）

### 高分内容（≥7.0分）
{high_score_cases}

### 低分内容（≤4.0分）
{low_score_cases}

### 人工标注反馈
{human_feedback}

## 分析任务
基于以上数据，在不重复已有规律的前提下，提炼新发现。

请严格输出以下 JSON，不要有其他文字：
{
  "success_patterns": ["新发现的成功规律，可直接指导创作，每条15-40字"],
  "failure_patterns": ["新发现的失败规律，说明如何避免，每条15-40字"],
  "humor_rules": ["发现的幽默底层规律，偏理论性，如'反差越大笑点越强'这类"],
  "new_genes": ["可直接加入创作要求的新bullet（15-30字）"],
  "insight": "本批次最重要的一个发现（一句话）",
  "best_joke_id": 最高分内容ID（整数，没有则为0）,
  "confidence": 0到1之间的置信度
}
```

### `prompts/strategist/self_learn.txt`

```
你是 HumorRL 的自学习模块。你需要基于已有知识库，提炼更高层次的规律。

## 当前知识库（按类型汇总）

### 成功规律
{success_patterns}

### 失败规律
{failure_patterns}

### 幽默底层规律
{humor_rules}

### 数据统计
- 总生成量：{total_count} 条
- 全局均分：{avg_score}
- 最高分：{max_score}，最低分：{min_score}
- 人工标注量：{human_rated_count} 条

## 自学习任务
1. 找出知识库中相互印证的规律，提炼更通用的原则
2. 找出矛盾或过时的规律（标记需要修正）
3. 基于数量最多的成功案例，总结共同特征

请输出 JSON：
{
  "meta_rules": ["从多条规律中提炼的更高层次原则，每条20-50字"],
  "contradictions": ["发现的矛盾规律描述（如有）"],
  "top_features": ["高分内容的共同特征，可操作"],
  "evolution_direction": "下阶段 Prompt 优化的核心方向（一句话）"
}
```

### `prompts/strategist/daily_report.txt`

```
你是 HumorRL 系统的项目报告员。请根据以下数据生成一份日报。

## 今日数据（{report_date}）

### 生成统计
- 总生成：{total_generated} 条
- 平均分：{avg_score}
- 最高分：{max_score}（ID={best_joke_id}）
- 各类型分布：{type_distribution}

### 今日最佳段子
{best_joke_text}

### 战略师今日新发现
- 新基因：{new_genes_count} 条
- 新规律：{new_patterns_count} 条
- 核心洞察：{daily_insight}

### 知识库累计
- 总规律数：{total_kb_entries} 条
- 幽默底层规律：{humor_rules_count} 条

## 报告要求
生成一份 Markdown 格式的日报，要求：
- 语气轻松，不要太正式
- 重点突出今日的新发现
- 如果发现了有趣的幽默规律，用通俗语言解释为什么好笑
- 末尾给出明天的生成建议（1-2条）
- 全文 300-500 字

直接输出 Markdown，不要 JSON。
```

### `prompts/strategist/persona_gen.txt`

```
你是 HumorRL 的人设设计师。用户提供了一个角色的基本背景，你需要将其转化为一个高质量的幽默风格人设。

## 用户输入

角色名称（可能为空）：{name_input}
背景描述：{background}

## 任务

根据背景描述，生成一个适合生成幽默内容的角色人设。

要求：
- style_prompt 必须描述这个角色「说话时的语气、口头禅、幽默风格、看待世界的角度」
- style_prompt 用2-4句话，第一句以"你是..."开头
- 幽默风格要有辨识度，不要太泛
- description 是一句话概括（≤20字）

请严格输出 JSON，不要有其他文字：
{
  "name": "角色名称（如用户已提供则保留，否则根据背景起一个）",
  "description": "一句话简介，≤20字",
  "style_prompt": "2-4句话的风格描述，供 LLM 扮演使用"
}
```

---

## 任务三：新建 `strategist.py`

完整实现以下函数（骨架已在下方，填充逻辑）：

```python
"""
HumorRL — 战略师
- 每50条新数据触发一次增量复盘
- 自学习：定期对知识库进行二次提炼
- 每日生成项目报告
- AI 辅助 Persona 生成
"""

import json
import os
import re
import datetime
from pathlib import Path
from typing import Optional

import db
import humor_engine
from contract import ContentType, CONTENT_TYPE_LABELS

PROJECT_ROOT = Path(__file__).resolve().parent
REVIEW_PROMPT_PATH       = "prompts/strategist/review.txt"
SELF_LEARN_PROMPT_PATH   = "prompts/strategist/self_learn.txt"
DAILY_REPORT_PROMPT_PATH = "prompts/strategist/daily_report.txt"
PERSONA_GEN_PROMPT_PATH  = "prompts/strategist/persona_gen.txt"


def _pro_chat(prompt: str, max_tokens: int = 2000) -> str:
    """调用豆包 pro，自动剥离 <think> 块。"""
    model = os.getenv("DOUBAO_STRATEGIST_MODEL", "doubao-seed-2.0-pro-250315")
    client = humor_engine._strategist_client()
    raw = humor_engine._chat(client, model, prompt,
                              temperature=0.3, max_tokens=max_tokens, role="strategist")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw


def _parse_json(raw: str) -> dict:
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(raw)


def _read_prompt(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def _format_cases(jokes: list, limit: int = 5) -> str:
    lines = []
    for j in jokes[:limit]:
        score_val = j.score.weighted_total if j.score else 0
        reasoning = j.score.reasoning if j.score else ""
        human = f"人工：{j.human_rating}分（{j.human_reaction}）" if j.human_rating else ""
        lines.append(
            f"[ID={j.id} 得分={score_val:.2f} {human}]\n{j.text}\n评审：{reasoning}"
        )
    return "\n---\n".join(lines) or "（暂无）"


def _knowledge_summary(content_type: Optional[str] = None, db_path: str = db.DB_PATH) -> str:
    sections = []
    for et, label in [
        ("success_pattern", "成功规律"),
        ("failure_pattern", "失败规律"),
        ("humor_rule",      "幽默底层规律"),
        ("insight",         "历史洞察"),
    ]:
        entries = db.get_knowledge(entry_type=et, content_type=content_type,
                                   limit=10, db_path=db_path)
        if entries:
            items = "\n".join(f"- {e['content']}" for e in entries)
            sections.append(f"### {label}\n{items}")
    return "\n\n".join(sections) or "（知识库尚为空）"


def incremental_review(since_joke_id: int, db_path: str = db.DB_PATH) -> dict:
    """
    增量复盘：只处理 id > since_joke_id 的新数据。
    实现逻辑：
    1. 用 db.get_jokes() 取最近数据，过滤 id > since_joke_id
    2. 高分组(>=7)、低分组(<=4)各取5条
    3. 总数据 < 10 条则 return {"skipped": True, "reason": "数据不足"}
    4. 取人工标注数据（human_rating IS NOT NULL）
    5. 读知识库摘要（_knowledge_summary）
    6. 填充 review.txt prompt → _pro_chat()
    7. 解析 JSON，分别存入知识库
       success_patterns → entry_type='success_pattern'
       failure_patterns → entry_type='failure_pattern'
       humor_rules      → entry_type='humor_rule'
       new_genes        → entry_type='gene'
       insight          → entry_type='insight'
    8. 返回解析结果 dict（含 insight / new_genes / best_joke_id 等）
    注意：不在这里更新 checkpoint，由 maybe_trigger 统一更新
    """
    # 取新数据（limit=200 覆盖50条以上场景）
    all_jokes = db.get_jokes(limit=200, db_path=db_path)
    new_jokes = [j for j in all_jokes if j.id and j.id > since_joke_id]

    if len(new_jokes) < 10:
        return {"skipped": True, "reason": f"数据不足（仅 {len(new_jokes)} 条，需>=10）"}

    high = sorted([j for j in new_jokes if j.score and j.score.weighted_total >= 7.0],
                  key=lambda j: j.score.weighted_total, reverse=True)
    low  = sorted([j for j in new_jokes if j.score and j.score.weighted_total <= 4.0],
                  key=lambda j: j.score.weighted_total)
    human_rated = [j for j in new_jokes if j.human_rating is not None]

    existing = _knowledge_summary(db_path=db_path)
    prompt = (
        _read_prompt(REVIEW_PROMPT_PATH)
        .replace("{existing_knowledge}", existing)
        .replace("{batch_size}", str(len(new_jokes)))
        .replace("{high_score_cases}", _format_cases(high))
        .replace("{low_score_cases}",  _format_cases(low))
        .replace("{human_feedback}",   _format_cases(human_rated, limit=3) if human_rated else "（暂无人工标注）")
    )

    raw = _pro_chat(prompt, max_tokens=2000)
    result = _parse_json(raw)

    best_id = result.get("best_joke_id") or (high[0].id if high else None)
    source_ids = [j.id for j in new_jokes if j.id]

    for text in result.get("success_patterns", []):
        db.save_knowledge("success_pattern", text, source_joke_ids=source_ids, db_path=db_path)
    for text in result.get("failure_patterns", []):
        db.save_knowledge("failure_pattern", text, source_joke_ids=source_ids, db_path=db_path)
    for text in result.get("humor_rules", []):
        db.save_knowledge("humor_rule", text, db_path=db_path)
    for text in result.get("new_genes", []):
        db.save_knowledge("gene", text, db_path=db_path)
    if result.get("insight"):
        db.save_knowledge("insight", result["insight"], db_path=db_path)

    result["best_joke_id"] = best_id
    return result


def self_learn(db_path: str = db.DB_PATH) -> dict:
    """
    二次自学习：对知识库进行元层次提炼。
    实现逻辑：
    1. 取所有非 _checkpoint 的知识库条目
    2. 条目 < 10 则 return {"skipped": True}
    3. 查全局 jokes 统计（total, avg, max, min, human_rated_count）
    4. 填充 self_learn.txt prompt → _pro_chat()
    5. meta_rules → entry_type='humor_rule'（relevance_score=1.5 标记为元规律）
    6. evolution_direction → entry_type='insight'
    7. 返回报告
    """
    all_kb = db.get_knowledge(limit=500, db_path=db_path)
    real_entries = [e for e in all_kb if e["entry_type"] != "_checkpoint"]
    if len(real_entries) < 10:
        return {"skipped": True, "reason": "知识库条目不足"}

    def _fmt_entries(et: str) -> str:
        items = [e["content"] for e in real_entries if e["entry_type"] == et]
        return "\n".join(f"- {t}" for t in items) if items else "（暂无）"

    with db._connect(db_path) as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt, AVG(score_total) as avg, "
            "MAX(score_total) as mx, MIN(score_total) as mn, "
            "SUM(CASE WHEN human_rating IS NOT NULL THEN 1 ELSE 0 END) as hr "
            "FROM jokes WHERE score_total IS NOT NULL"
        ).fetchone()

    prompt = (
        _read_prompt(SELF_LEARN_PROMPT_PATH)
        .replace("{success_patterns}", _fmt_entries("success_pattern"))
        .replace("{failure_patterns}", _fmt_entries("failure_pattern"))
        .replace("{humor_rules}",      _fmt_entries("humor_rule"))
        .replace("{total_count}",      str(row["cnt"] or 0))
        .replace("{avg_score}",        f"{row['avg'] or 0:.2f}")
        .replace("{max_score}",        f"{row['mx'] or 0:.2f}")
        .replace("{min_score}",        f"{row['mn'] or 0:.2f}")
        .replace("{human_rated_count}", str(row["hr"] or 0))
    )

    raw = _pro_chat(prompt, max_tokens=1500)
    result = _parse_json(raw)

    for text in result.get("meta_rules", []):
        db.save_knowledge("humor_rule", text, relevance_score=1.5, db_path=db_path)
    if result.get("evolution_direction"):
        db.save_knowledge("insight", result["evolution_direction"], relevance_score=1.2, db_path=db_path)

    return result


def generate_daily_report(
    report_date: Optional[str] = None,
    db_path: str = db.DB_PATH,
) -> str:
    """
    生成日报并存入 DB。
    实现逻辑：
    1. report_date 默认 datetime.date.today().isoformat()
    2. 查当天 jokes（created_at LIKE 'YYYY-MM-DD%'）统计
    3. 取最高分 joke 文本
    4. 查当天新增知识库条目数
    5. 各类型分布（GROUP BY content_type）
    6. 填充 daily_report.txt → _pro_chat(max_tokens=1000)
    7. db.save_daily_report() 保存
    8. 返回 Markdown 文本
    """
    if not report_date:
        report_date = datetime.date.today().isoformat()

    with db._connect(db_path) as conn:
        stats = conn.execute(
            "SELECT COUNT(*) as cnt, AVG(score_total) as avg, "
            "MAX(score_total) as mx, "
            "id as best_id "
            "FROM jokes WHERE created_at LIKE ? AND score_total IS NOT NULL",
            (f"{report_date}%",),
        ).fetchone()

        type_rows = conn.execute(
            "SELECT content_type, COUNT(*) as cnt FROM jokes "
            "WHERE created_at LIKE ? GROUP BY content_type",
            (f"{report_date}%",),
        ).fetchall()

        # 最高分 joke 文本
        best_row = conn.execute(
            "SELECT id, text FROM jokes WHERE created_at LIKE ? "
            "AND score_total IS NOT NULL ORDER BY score_total DESC LIMIT 1",
            (f"{report_date}%",),
        ).fetchone()

        # 今日新增知识库条目
        kb_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_base WHERE created_at LIKE ? "
            "AND entry_type != '_checkpoint'",
            (f"{report_date}%",),
        ).fetchone()

        # 今日新增基因数
        new_genes_today = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_base WHERE created_at LIKE ? "
            "AND entry_type='gene'",
            (f"{report_date}%",),
        ).fetchone()

        # 总知识库
        total_kb = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_base WHERE entry_type != '_checkpoint'"
        ).fetchone()

        humor_rules_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM knowledge_base WHERE entry_type='humor_rule'"
        ).fetchone()

    total_gen = stats["cnt"] or 0
    avg_sc = stats["avg"] or 0.0
    max_sc = stats["mx"] or 0.0
    best_joke_id = best_row["id"] if best_row else None
    best_joke_text = best_row["text"] if best_row else "（今日暂无生成）"

    type_dist = ", ".join(
        f"{r['content_type']}×{r['cnt']}" for r in type_rows
    ) if type_rows else "暂无"

    # 最新洞察
    insights = db.get_knowledge(entry_type="insight", limit=1, db_path=db_path)
    daily_insight = insights[0]["content"] if insights else "（暂无）"

    new_patterns_count = kb_today["cnt"] or 0
    new_genes_count = new_genes_today["cnt"] or 0

    prompt = (
        _read_prompt(DAILY_REPORT_PROMPT_PATH)
        .replace("{report_date}",       report_date)
        .replace("{total_generated}",   str(total_gen))
        .replace("{avg_score}",         f"{avg_sc:.2f}")
        .replace("{max_score}",         f"{max_sc:.2f}")
        .replace("{best_joke_id}",      str(best_joke_id or "无"))
        .replace("{type_distribution}", type_dist)
        .replace("{best_joke_text}",    best_joke_text[:300])
        .replace("{new_genes_count}",   str(new_genes_count))
        .replace("{new_patterns_count}", str(new_patterns_count))
        .replace("{daily_insight}",     daily_insight)
        .replace("{total_kb_entries}",  str(total_kb["cnt"] or 0))
        .replace("{humor_rules_count}", str(humor_rules_cnt["cnt"] or 0))
    )

    report_md = _pro_chat(prompt, max_tokens=1000)

    db.save_daily_report(
        report_date=report_date,
        total_generated=total_gen,
        avg_score=avg_sc,
        new_patterns=new_patterns_count,
        best_joke_id=best_joke_id,
        report_md=report_md,
        db_path=db_path,
    )
    return report_md


def maybe_trigger(db_path: str = db.DB_PATH) -> Optional[dict]:
    """
    检查是否需要触发战略师复盘。
    条件：distance上次运行后新增 >= STRATEGIST_TRIGGER_INTERVAL 条（默认50）。
    """
    interval = int(os.getenv("STRATEGIST_TRIGGER_INTERVAL", "50"))
    last_id = db.get_last_strategist_joke_id(db_path=db_path)

    if db.count_jokes_since(last_id, db_path=db_path) < interval:
        return None

    # 取最新 joke id 用于更新 checkpoint
    with db._connect(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM jokes WHERE score_total IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    latest_id = row["id"]

    report = incremental_review(since_joke_id=last_id, db_path=db_path)

    # 每5次触发一次自学习（通过知识库总条目数 mod 5 判断）
    kb_count = len(db.get_knowledge(limit=1000, db_path=db_path))
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
        _read_prompt(PERSONA_GEN_PROMPT_PATH)
        .replace("{name_input}", name_input.strip() or "（用户未提供）")
        .replace("{background}", background.strip())
    )
    raw = _pro_chat(prompt, max_tokens=600)
    result = _parse_json(raw)
    if not result.get("style_prompt"):
        raise RuntimeError("AI 未返回有效的 style_prompt")
    return {
        "name": result.get("name", name_input or "自定义角色"),
        "description": result.get("description", ""),
        "style_prompt": result["style_prompt"],
    }
```

---

## 任务四：修改 `scheduler.py`

### 4a. 在 `job_batch_generate()` 的 `db.save_joke(joke)` 后追加

```python
        saved_id = db.save_joke(joke)
        logger.info(f"已生成并存储，id={saved_id}，得分={joke.score.weighted_total:.2f}")

        # 检查是否触发战略师（每50条）
        try:
            from strategist import maybe_trigger
            result = maybe_trigger()
            if result and not result.get("skipped"):
                insight = result.get("insight", "")
                n_genes = len(result.get("new_genes", []))
                logger.info(f"战略师复盘完成 | 新基因={n_genes} | 洞察：{insight[:50]}")
        except Exception as exc:
            logger.warning(f"战略师触发检查失败（不影响主流程）：{exc}")
```

### 4b. 新增 `job_daily_report()` 并加到 `main()`

```python
def job_daily_report():
    """每天 23:55 生成日报。"""
    logger.info("=== 生成日报 ===")
    try:
        from strategist import generate_daily_report
        report_md = generate_daily_report()
        logger.info(f"日报生成完成：\n{report_md[:200]}...")
    except Exception as exc:
        logger.error(f"日报生成失败：{exc}", exc_info=True)

# 在 main() 中加：
# scheduler.add_job(job_daily_report, "cron", hour=23, minute=55)
```

---

## 任务五：修改 `evolution.py` — 动态基因池

将 `MUTATION_GENE_POOL` 重命名为 `_STATIC_GENE_POOL`（保持内容不变），新增：

```python
def _get_gene_pool(content_type=None, db_path=db.DB_PATH) -> list[str]:
    """优先从知识库取动态基因，不足时补充静态兜底。"""
    try:
        dynamic = db.get_dynamic_gene_pool(content_type=content_type, limit=30, db_path=db_path)
        if len(dynamic) >= 6:
            return dynamic
        return dynamic + _STATIC_GENE_POOL
    except Exception:
        return _STATIC_GENE_POOL
```

在 `mutate()` 签名加 `db_path: str = db.DB_PATH`，函数内 `rng.choice(MUTATION_GENE_POOL)` 改为：
```python
pool = _get_gene_pool(db_path=db_path)
replacement = rng.choice(pool)
```

同时把 `evaluate_variant()` 里的：
```python
model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
```
改为：
```python
model = os.getenv("DOUBAO_WRITER_MODEL", "doubao-seed-2.0-lite-250315")
```

---

## 任务六：修改 `app.py`

### 6a. 顶部 import 区新增

```python
from db import (
    ...现有导入...,
    get_cost_stats,
    get_knowledge,
    get_daily_reports,
    get_last_strategist_joke_id,
    update_persona,
    delete_persona,
)
```

### 6b. Session State 初始化追加

在 `_init_state()` 的 `defaults` dict 里加：
```python
"persona_creation_step": "input",   # "input" | "preview"
"persona_preview": None,             # dict: {name, description, style_prompt}
"persona_edit_id": None,             # 正在编辑的 persona id
```

### 6c. 监控页 `_page_monitor()` 末尾追加两个 expander

在 Prompt 进化 expander 之后：

```python
    # ── 知识库
    with st.expander("📚 知识库", expanded=False):
        kb_type = st.selectbox(
            "条目类型",
            ["全部", "success_pattern", "failure_pattern", "humor_rule", "gene", "insight"],
            format_func=lambda v: {
                "全部": "🔍 全部",
                "success_pattern": "✅ 成功规律",
                "failure_pattern": "❌ 失败规律",
                "humor_rule":      "🎭 幽默底层规律",
                "gene":            "🧬 基因",
                "insight":         "💡 洞察",
            }.get(v, v),
            key="kb_type_sel",
        )
        entries = get_knowledge(
            entry_type=None if kb_type == "全部" else kb_type,
            limit=50,
        )
        if not entries:
            st.info("知识库为空，等待战略师复盘后自动填充（每50条触发一次）。")
        else:
            st.markdown(
                f'<p style="color:var(--muted);font-size:13px">{len(entries)} 条</p>',
                unsafe_allow_html=True,
            )
            icons = {"success_pattern": "✅", "failure_pattern": "❌",
                     "humor_rule": "🎭", "gene": "🧬", "insight": "💡"}
            for e in entries:
                icon = icons.get(e["entry_type"], "📌")
                ct_tag = (f'<span class="badge badge-type">{e["content_type"]}</span>'
                          if e.get("content_type") else
                          '<span class="badge badge-time">通用</span>')
                st.markdown(f"""
                <div class="joke-card" style="padding:0.75rem 1rem;margin-bottom:6px">
                  <div style="display:flex;gap:12px;align-items:flex-start">
                    <div style="flex:1;font-size:13px;color:var(--text);line-height:1.7">
                      {icon} {e['content']}
                    </div>
                    <div style="text-align:right;flex-shrink:0">
                      {ct_tag}
                      <div style="font-size:11px;color:var(--muted);margin-top:4px">
                        ⭐{e['relevance_score']:.1f} 用{e['used_count']}次
                      </div>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

        col_kb1, col_kb2 = st.columns(2)
        with col_kb1:
            if st.button("🔬 立即复盘", key="btn_review"):
                with st.spinner("战略师深度分析中（约30-60秒）……"):
                    try:
                        from strategist import incremental_review
                        last_id = get_last_strategist_joke_id()
                        r = incremental_review(since_joke_id=last_id)
                        if r.get("skipped"):
                            st.warning(f"数据不足：{r.get('reason')}")
                        else:
                            st.success(
                                f"完成！新基因 {len(r.get('new_genes', []))} 条，"
                                f"洞察：{r.get('insight', '')}"
                            )
                            st.rerun()
                    except Exception as exc:
                        st.error(f"复盘失败：{exc}")
        with col_kb2:
            if st.button("🏋️ 自主训练", key="btn_self_learn"):
                with st.spinner("战略师正在对知识库进行自我提炼……"):
                    try:
                        from strategist import self_learn
                        r = self_learn()
                        if r.get("skipped"):
                            st.warning(f"跳过：{r.get('reason')}")
                        else:
                            n_meta = len(r.get("meta_rules", []))
                            st.success(
                                f"自主训练完成！提炼了 {n_meta} 条元规律。\n"
                                f"进化方向：{r.get('evolution_direction', '')}"
                            )
                            st.rerun()
                    except Exception as exc:
                        st.error(f"自主训练失败：{exc}")

    # ── 日报
    with st.expander("📰 项目日报", expanded=False):
        reports = get_daily_reports(limit=7)
        if not reports:
            st.info("暂无日报，每天 23:55 自动生成。")
        else:
            dates = [r["report_date"] for r in reports]
            sel_date = st.selectbox("选择日期", dates, key="report_date_sel")
            sel = next(r for r in reports if r["report_date"] == sel_date)
            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(f'<div class="stat-card"><div class="stat-num">{sel["total_generated"]}</div><div class="stat-lbl">当日生成</div></div>', unsafe_allow_html=True)
            with col2:
                st.markdown(f'<div class="stat-card"><div class="stat-num" style="color:var(--accent)">{sel["avg_score"]:.2f}</div><div class="stat-lbl">平均分</div></div>', unsafe_allow_html=True)
            with col3:
                st.markdown(f'<div class="stat-card"><div class="stat-num" style="color:var(--good)">{sel["new_patterns"]}</div><div class="stat-lbl">新规律</div></div>', unsafe_allow_html=True)
            st.markdown(sel["report_md"])

        if st.button("📝 立即生成今日日报", key="btn_daily_report"):
            with st.spinner("生成日报中……"):
                try:
                    from strategist import generate_daily_report
                    md = generate_daily_report()
                    st.success("日报已生成！")
                    st.rerun()
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
```

### 6d. 完全重写 `_page_persona()`

用以下实现替换现有的整个 `_page_persona()` 函数：

```python
def _page_persona():
    st.markdown("""
    <div class="page-header">
      <h1>Persona 管理</h1>
      <p>用 AI 设计独特的幽默角色风格，生成时自动代入</p>
    </div>""", unsafe_allow_html=True)

    personas = get_personas()
    preset   = [p for p in personas if p.is_preset]
    custom   = [p for p in personas if not p.is_preset]

    # ── Tab 切换：角色列表 / 创建角色
    tab_list, tab_create = st.tabs(["🃏 角色列表", "✨ 创建新角色"])

    # ────── Tab 1: 角色列表 ──────
    with tab_list:
        if not personas:
            st.markdown("""
            <div class="empty-state">
              <div class="empty-icon">👤</div>
              <h3>还没有任何角色</h3>
              <p>切换到「创建新角色」Tab 来添加</p>
            </div>""", unsafe_allow_html=True)
        else:
            for group_label, group in [("🎭 预设角色", preset), ("🎨 自定义角色", custom)]:
                if not group:
                    continue
                st.markdown(f"**{group_label}**")
                for p in group:
                    with st.expander(f"{p.name}  —  {p.description}", expanded=False):
                        col_info, col_actions = st.columns([3, 1])
                        with col_info:
                            st.markdown(f"""
                            <div style="font-size:13px;color:var(--text);line-height:1.8;
                                        background:var(--surface2);border-radius:8px;padding:12px">
                              {p.style_prompt}
                            </div>""", unsafe_allow_html=True)
                        with col_actions:
                            # 编辑按钮（预设和自定义都可编辑）
                            if st.button("✏️ 编辑", key=f"edit_btn_{p.id}",
                                         use_container_width=True):
                                st.session_state.persona_edit_id = p.id
                                st.session_state.persona_preview = {
                                    "name": p.name,
                                    "description": p.description,
                                    "style_prompt": p.style_prompt,
                                }
                                st.session_state.persona_creation_step = "edit"
                                st.rerun()
                            # 仅自定义角色可删除
                            if not p.is_preset:
                                if st.button("🗑️ 删除", key=f"del_btn_{p.id}",
                                             use_container_width=True):
                                    try:
                                        delete_persona(p.id)
                                        st.success(f"已删除「{p.name}」")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(f"删除失败：{exc}")

        # ── 内联编辑面板（点击编辑后在此展示）
        if st.session_state.get("persona_creation_step") == "edit" and st.session_state.get("persona_edit_id"):
            st.markdown("---")
            st.markdown("**编辑角色**")
            preview = st.session_state.persona_preview
            edit_name  = st.text_input("角色名称", value=preview["name"], key="edit_name")
            edit_desc  = st.text_input("一句话简介", value=preview["description"], key="edit_desc")
            edit_style = st.text_area("风格 Prompt", value=preview["style_prompt"],
                                      height=140, key="edit_style")

            col_save, col_ai, col_cancel = st.columns(3)
            with col_save:
                if st.button("💾 保存修改", use_container_width=True, key="edit_save"):
                    try:
                        update_persona(
                            st.session_state.persona_edit_id,
                            edit_name.strip(), edit_desc.strip(), edit_style.strip()
                        )
                        st.success("已保存！")
                        st.session_state.persona_creation_step = "input"
                        st.session_state.persona_edit_id = None
                        st.session_state.persona_preview = None
                        st.rerun()
                    except Exception as exc:
                        st.error(f"保存失败：{exc}")
            with col_ai:
                if st.button("🤖 AI 重新生成风格", use_container_width=True, key="edit_regen"):
                    with st.spinner("AI 重新分析中……"):
                        try:
                            from strategist import generate_persona_style
                            result = generate_persona_style(edit_name, edit_desc or edit_name)
                            st.session_state.persona_preview["style_prompt"] = result["style_prompt"]
                            st.session_state.persona_preview["description"] = result.get("description", edit_desc)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"AI 生成失败：{exc}")
            with col_cancel:
                if st.button("✕ 取消", use_container_width=True, key="edit_cancel"):
                    st.session_state.persona_creation_step = "input"
                    st.session_state.persona_edit_id = None
                    st.session_state.persona_preview = None
                    st.rerun()

    # ────── Tab 2: 创建新角色 ──────
    with tab_create:
        step = st.session_state.get("persona_creation_step", "input")

        # ── Step 1: 输入背景
        if step == "input":
            st.markdown("""
            <div style="background:var(--surface2);border-radius:12px;padding:1.25rem;margin-bottom:1rem">
              <div style="font-size:13px;color:var(--muted);margin-bottom:0.5rem">💡 怎么用</div>
              <div style="font-size:13px;color:var(--text);line-height:1.8">
                描述你想要的角色背景，AI 会自动生成完整的幽默风格。<br>
                例如：「一个90后程序员，996，爱摸鱼，对产品需求有无尽吐槽」
              </div>
            </div>""", unsafe_allow_html=True)

            name_input = st.text_input(
                "角色名称（可留空，AI 自动起名）",
                placeholder="例：厌世文青、摸鱼大师",
                key="new_persona_name",
            )
            background = st.text_area(
                "背景描述 *",
                placeholder="用自然语言描述这个角色是谁、有什么特点、说话风格大概是什么...",
                height=120,
                key="new_persona_bg",
            )

            col_ai_btn, col_manual_btn = st.columns([2, 1])
            with col_ai_btn:
                if st.button("🤖 AI 生成人设", use_container_width=True, key="btn_ai_gen"):
                    if not background.strip():
                        st.error("请先填写背景描述")
                    else:
                        with st.spinner("战略师正在分析角色特征，生成幽默风格……"):
                            try:
                                from strategist import generate_persona_style
                                result = generate_persona_style(name_input, background)
                                st.session_state.persona_preview = result
                                st.session_state.persona_creation_step = "preview"
                                st.rerun()
                            except Exception as exc:
                                st.error(f"AI 生成失败：{exc}")
            with col_manual_btn:
                if st.button("✍️ 手动填写", use_container_width=True, key="btn_manual"):
                    st.session_state.persona_preview = {
                        "name": name_input or "自定义角色",
                        "description": "",
                        "style_prompt": "",
                    }
                    st.session_state.persona_creation_step = "preview"
                    st.rerun()

        # ── Step 2: 预览 + 编辑 + 确认
        elif step == "preview":
            preview = st.session_state.persona_preview or {}

            st.markdown("**预览 & 微调**")
            st.markdown("""
            <div style="font-size:12px;color:var(--muted);margin-bottom:1rem">
              AI 生成的内容可以直接修改，满意后点击「确认创建」
            </div>""", unsafe_allow_html=True)

            final_name  = st.text_input("角色名称", value=preview.get("name", ""),
                                         key="preview_name")
            final_desc  = st.text_input("一句话简介", value=preview.get("description", ""),
                                         key="preview_desc")
            final_style = st.text_area(
                "风格 Prompt",
                value=preview.get("style_prompt", ""),
                height=160,
                key="preview_style",
                help="这段文字会在生成段子时注入给 AI，决定角色的说话方式",
            )

            # 实时预览卡片
            if final_name and final_style:
                st.markdown("**效果预览**")
                st.markdown(f"""
                <div class="joke-card">
                  <div style="font-size:16px;font-weight:700;color:var(--text);margin-bottom:4px">
                    {final_name}
                  </div>
                  <div style="font-size:12px;color:var(--muted);margin-bottom:10px">
                    {final_desc}
                  </div>
                  <div style="font-size:13px;color:var(--text);line-height:1.7;
                              background:var(--surface2);border-radius:8px;padding:10px">
                    {final_style}
                  </div>
                </div>""", unsafe_allow_html=True)

            col_confirm, col_regen, col_back = st.columns(3)
            with col_confirm:
                if st.button("✅ 确认创建", use_container_width=True, key="btn_confirm_create"):
                    if not final_name.strip() or not final_style.strip():
                        st.error("角色名称和风格 Prompt 不能为空")
                    else:
                        from contract import Persona as PersonaModel
                        try:
                            new_id = save_persona(PersonaModel(
                                id=None,
                                name=final_name.strip(),
                                description=final_desc.strip(),
                                style_prompt=final_style.strip(),
                                is_preset=False,
                            ))
                            st.success(f"✨ 角色「{final_name}」已创建！ID={new_id}")
                            st.session_state.persona_creation_step = "input"
                            st.session_state.persona_preview = None
                            st.rerun()
                        except Exception as exc:
                            st.error(f"创建失败：{exc}")
            with col_regen:
                if st.button("🔄 重新生成", use_container_width=True, key="btn_regen"):
                    st.session_state.persona_creation_step = "input"
                    st.session_state.persona_preview = None
                    st.rerun()
            with col_back:
                if st.button("← 返回", use_container_width=True, key="btn_back_to_input"):
                    st.session_state.persona_creation_step = "input"
                    st.session_state.persona_preview = None
                    st.rerun()
```

---

## 任务七：更新 `.env.example`

追加：
```
# 豆包 API
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_WRITER_MODEL=doubao-seed-2.0-lite-250315
DOUBAO_JUDGE_MODEL=doubao-seed-2.0-lite-250315
DOUBAO_STRATEGIST_MODEL=doubao-seed-2.0-pro-250315

# 战略师触发间隔（条数）
STRATEGIST_TRIGGER_INTERVAL=50
```

---

## 完成后执行

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add strategist.py db.py evolution.py scheduler.py app.py \
        prompts/strategist/ .env.example
git commit -m "feat: strategist + self-train + AI persona editor"
git push origin main
```

---

## 注意事项

1. `db.py` 的 SCHEMA 字符串追加到末尾，`init_db()` 会自动执行（`executescript(SCHEMA)` 已用 `IF NOT EXISTS`，幂等安全）
2. `app.py` 顶部 import 的 `get_cost_stats` 已在监控页局部 import，检查是否重复，避免两处 import 冲突
3. `_page_persona()` 用新版完整替换旧版，不要保留旧版代码
4. `step == "edit"` 这个分支放在 **Tab 1 里面**（在角色列表下方），不在 Tab 2 里
