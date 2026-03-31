"""
HumorRL — 数据库层
SQLite 建表 + CRUD，供 humor_engine.py 和 app.py 调用。
"""

import sqlite3
import json
import datetime
import os
from pathlib import Path
from typing import Optional
from contract import ContentType, Persona, ScoreResult, JokeRecord


_PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = str(_PROJECT_ROOT / "data" / "humor.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS personas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    description TEXT    NOT NULL DEFAULT '',
    style_prompt TEXT   NOT NULL DEFAULT '',
    is_preset   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS jokes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT    NOT NULL,
    text            TEXT    NOT NULL,
    persona_id      INTEGER REFERENCES personas(id),
    -- 自动评分（6维 + 总分 + 理由）
    score_structure     REAL,
    score_surprise      REAL,
    score_relatability  REAL,
    score_language      REAL,
    score_creativity    REAL,
    score_safety        REAL,
    score_total         REAL,
    score_reasoning     TEXT,
    -- 人工评分
    human_rating    INTEGER,
    human_reaction  TEXT,
    -- 改写链
    parent_id       INTEGER REFERENCES jokes(id),
    rewrite_round   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jokes_type  ON jokes(content_type);
CREATE INDEX IF NOT EXISTS idx_jokes_score ON jokes(score_total);

CREATE TABLE IF NOT EXISTS api_costs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model       TEXT    NOT NULL,
    role        TEXT    NOT NULL,
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_costs_created ON api_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_costs_model   ON api_costs(model);

CREATE TABLE IF NOT EXISTS prompt_variants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT    NOT NULL,
    generation      INTEGER NOT NULL DEFAULT 0,
    prompt_text     TEXT    NOT NULL,
    parent_ids      TEXT    NOT NULL DEFAULT '',
    uses            INTEGER NOT NULL DEFAULT 0,
    total_score     REAL    NOT NULL DEFAULT 0.0,
    avg_score       REAL    NOT NULL DEFAULT 0.0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variants_type ON prompt_variants(content_type);
CREATE INDEX IF NOT EXISTS idx_variants_gen  ON prompt_variants(generation);

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
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date    TEXT    NOT NULL UNIQUE,
    total_generated INTEGER NOT NULL DEFAULT 0,
    avg_score      REAL    NOT NULL DEFAULT 0.0,
    new_patterns   INTEGER NOT NULL DEFAULT 0,
    best_joke_id   INTEGER,
    report_md      TEXT    NOT NULL,
    created_at     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date DESC);

CREATE TABLE IF NOT EXISTS scheduler_jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name    TEXT    NOT NULL UNIQUE,
    last_run_at TEXT,
    last_status TEXT    NOT NULL DEFAULT 'idle',
    last_result TEXT,
    run_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT    NOT NULL
);
"""

PRESET_PERSONAS = [
    {
        "name": "毒舌大叔",
        "description": "40岁北京男人，说话刻薄但有道理，见过世面",
        "style_prompt": (
            "你是一个毒舌但幽默的中年北京大叔，说话直接、爱用反讽，"
            "观察生活细节特别犀利。语气带点老北京腔，喜欢说'您瞧瞧这事儿'、'搁以前哪儿有这出'。"
            "幽默是冷静的，不嬉皮。"
        ),
    },
    {
        "name": "社恐打工人",
        "description": "25岁互联网公司普通员工，内向、emo、对职场规则满腹牢骚",
        "style_prompt": (
            "你是一个社恐的互联网打工人，说话时带着打工人特有的疲惫感和自嘲。"
            "经常用'属实'、'麻了'、'班味'、'emo'这类词。"
            "幽默来自对职场荒诞的精准吐槽，不是活泼搞笑，是那种'笑着流泪'的共鸣感。"
        ),
    },
    {
        "name": "热心大妈",
        "description": "58岁退休阿姨，广场舞爱好者，爱管闲事但出发点都是好的",
        "style_prompt": (
            "你是一个热心肠的退休阿姨，思维方式和年轻人有代沟但自己不知道。"
            "语气热情、说话爱绕弯子，喜欢类比'我们那时候'。"
            "幽默来自无意识的代沟冲突和她真诚但错位的关心。"
        ),
    },
]


# ─────────────────────────────────────────
# 连接管理
# ─────────────────────────────────────────

def _connect(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.datetime.now().isoformat()


# ─────────────────────────────────────────
# 初始化
# ─────────────────────────────────────────

def init_db(db_path: str = DB_PATH) -> None:
    """建表（幂等）并写入预设 persona（如果 personas 表为空）。"""
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cols = [row[1] for row in conn.execute("PRAGMA table_info(jokes)").fetchall()]
        if "prompt_variant_id" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN prompt_variant_id INTEGER REFERENCES prompt_variants(id)"
            )
        row = conn.execute("SELECT COUNT(*) FROM personas").fetchone()
        if row[0] == 0:
            for p in PRESET_PERSONAS:
                conn.execute(
                    "INSERT INTO personas (name, description, style_prompt, is_preset, created_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (p["name"], p["description"], p["style_prompt"], _now()),
                )
    seed_prompt_variants(db_path)


# ─────────────────────────────────────────
# Persona CRUD
# ─────────────────────────────────────────

def save_persona(persona: Persona, db_path: str = DB_PATH) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO personas (name, description, style_prompt, is_preset, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (persona.name, persona.description, persona.style_prompt,
             int(persona.is_preset), _now()),
        )
        return cur.lastrowid


def get_personas(db_path: str = DB_PATH) -> list[Persona]:
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM personas ORDER BY is_preset DESC, id").fetchall()
    return [
        Persona(
            id=r["id"],
            name=r["name"],
            description=r["description"],
            style_prompt=r["style_prompt"],
            is_preset=bool(r["is_preset"]),
        )
        for r in rows
    ]


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


# ─────────────────────────────────────────
# Joke CRUD
# ─────────────────────────────────────────

def save_joke(joke: JokeRecord, db_path: str = DB_PATH) -> int:
    s = joke.score
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO jokes
               (content_type, text, persona_id,
                score_structure, score_surprise, score_relatability,
                score_language, score_creativity, score_safety,
                score_total, score_reasoning,
                human_rating, human_reaction,
                parent_id, rewrite_round, created_at)
               VALUES (?,?,?, ?,?,?, ?,?,?, ?,?, ?,?, ?,?,?)""",
            (
                joke.content_type.value,
                joke.text,
                joke.persona_id,
                s.structure    if s else None,
                s.surprise     if s else None,
                s.relatability if s else None,
                s.language     if s else None,
                s.creativity   if s else None,
                s.safety       if s else None,
                s.weighted_total if s else None,
                s.reasoning    if s else None,
                joke.human_rating,
                joke.human_reaction,
                joke.parent_id,
                joke.rewrite_round,
                joke.created_at.isoformat(),
            ),
        )
        return cur.lastrowid


def get_jokes(
    content_type: Optional[ContentType] = None,
    min_score: Optional[float] = None,
    unrated_only: bool = False,
    limit: int = 50,
    db_path: str = DB_PATH,
) -> list[JokeRecord]:
    conditions, params = [], []
    if content_type:
        conditions.append("content_type = ?")
        params.append(content_type.value)
    if min_score is not None:
        conditions.append("score_total >= ?")
        params.append(min_score)
    if unrated_only:
        conditions.append("human_rating IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jokes {where} ORDER BY score_total DESC NULLS LAST LIMIT ?",
            params,
        ).fetchall()

    result = []
    for r in rows:
        score = None
        if r["score_structure"] is not None:
            score = ScoreResult(
                structure=r["score_structure"],
                surprise=r["score_surprise"],
                relatability=r["score_relatability"],
                language=r["score_language"],
                creativity=r["score_creativity"],
                safety=r["score_safety"],
                reasoning=r["score_reasoning"] or "",
            )
        result.append(JokeRecord(
            id=r["id"],
            content_type=ContentType(r["content_type"]),
            text=r["text"],
            persona_id=r["persona_id"],
            score=score,
            human_rating=r["human_rating"],
            human_reaction=r["human_reaction"],
            created_at=datetime.datetime.fromisoformat(r["created_at"]),
            parent_id=r["parent_id"],
            rewrite_round=r["rewrite_round"],
        ))
    return result


def update_human_rating(
    joke_id: int,
    rating: int,
    reaction: str,
    db_path: str = DB_PATH,
) -> None:
    assert reaction in ("好笑", "一般", "不好笑"), "reaction 只接受 '好笑'|'一般'|'不好笑'"
    assert 1 <= rating <= 10, "rating 必须 1-10"
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE jokes SET human_rating=?, human_reaction=? WHERE id=?",
            (rating, reaction, joke_id),
        )


def get_stats(db_path: str = DB_PATH) -> dict:
    """返回简单统计，供 app.py 的统计页使用。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT content_type, COUNT(*) as cnt, AVG(score_total) as avg_score "
            "FROM jokes GROUP BY content_type"
        ).fetchall()
        recent = conn.execute(
            "SELECT score_total, created_at FROM jokes "
            "WHERE score_total IS NOT NULL ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return {
        "by_type": [
            {
                "type": r["content_type"],
                "count": r["cnt"],
                "avg_score": float(r["avg_score"] or 0.0),
            }
            for r in rows
        ],
        "recent_scores": [
            {"score": float(r["score_total"] or 0.0), "created_at": r["created_at"]}
            for r in recent
        ],
    }


def _row_to_joke_record(row: sqlite3.Row) -> JokeRecord:
    score = None
    if row["score_structure"] is not None:
        score = ScoreResult(
            structure=row["score_structure"],
            surprise=row["score_surprise"],
            relatability=row["score_relatability"],
            language=row["score_language"],
            creativity=row["score_creativity"],
            safety=row["score_safety"],
            reasoning=row["score_reasoning"] or "",
        )

    return JokeRecord(
        id=row["id"],
        content_type=ContentType(row["content_type"]),
        text=row["text"],
        persona_id=row["persona_id"],
        score=score,
        human_rating=row["human_rating"],
        human_reaction=row["human_reaction"],
        created_at=datetime.datetime.fromisoformat(row["created_at"]),
        parent_id=row["parent_id"],
        rewrite_round=row["rewrite_round"],
    )


def get_joke_by_id(joke_id: int, db_path: str = DB_PATH) -> Optional[JokeRecord]:
    """按 id 查单条，复用 get_jokes 中的行解析逻辑。不存在返回 None。"""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM jokes WHERE id = ?", (joke_id,)).fetchone()
    if row is None:
        return None
    return _row_to_joke_record(row)


def get_rewrite_chain(root_id: int, db_path: str = DB_PATH) -> list[JokeRecord]:
    """
    返回以 root_id 为根的完整改写链（含原始），按 rewrite_round 升序。
    用迭代（不用递归）：
      current_id = root_id
      while current_id:
          record = get_joke_by_id(current_id)
          chain.append(record)
          查找 parent_id = record.id 的下一条
    """
    chain: list[JokeRecord] = []
    current_id: Optional[int] = root_id

    while current_id:
        record = get_joke_by_id(current_id, db_path=db_path)
        if record is None:
            break
        chain.append(record)

        with _connect(db_path) as conn:
            next_row = conn.execute(
                "SELECT id FROM jokes WHERE parent_id = ? ORDER BY rewrite_round ASC, id ASC LIMIT 1",
                (record.id,),
            ).fetchone()
        current_id = next_row["id"] if next_row else None

    return chain


def log_api_cost(
    model: str,
    role: str,
    prompt_tokens: int,
    completion_tokens: int,
    db_path: str = DB_PATH,
) -> None:
    """记录一次 API 调用的 token 用量。"""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO api_costs (model, role, prompt_tokens, completion_tokens, total_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                model,
                role,
                prompt_tokens,
                completion_tokens,
                prompt_tokens + completion_tokens,
                _now(),
            ),
        )


def get_cost_stats(days: int = 7, db_path: str = DB_PATH) -> dict:
    """
    返回最近 N 天的 cost 统计。
    结果格式：
    {
        "total_tokens": int,
        "by_model": [{"model": str, "role": str, "total_tokens": int, "calls": int}],
        "daily": [{"date": str, "total_tokens": int}],
    }
    """
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    with _connect(db_path) as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM api_costs WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()[0]

        by_model = conn.execute(
            "SELECT model, role, SUM(total_tokens) as total_tokens, COUNT(*) as calls "
            "FROM api_costs WHERE created_at >= ? GROUP BY model, role",
            (cutoff,),
        ).fetchall()

        daily = conn.execute(
            "SELECT substr(created_at, 1, 10) as date, SUM(total_tokens) as total_tokens "
            "FROM api_costs WHERE created_at >= ? GROUP BY date ORDER BY date",
            (cutoff,),
        ).fetchall()

    return {
        "total_tokens": int(total),
        "by_model": [
            {
                "model": r["model"],
                "role": r["role"],
                "total_tokens": int(r["total_tokens"] or 0),
                "calls": int(r["calls"] or 0),
            }
            for r in by_model
        ],
        "daily": [{"date": r["date"], "total_tokens": int(r["total_tokens"] or 0)} for r in daily],
    }


def save_prompt_variant(
    content_type: str,
    prompt_text: str,
    generation: int,
    parent_ids: list[int],
    db_path: str = DB_PATH,
) -> int:
    """存入 prompt_variants，返回新 id。"""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO prompt_variants "
            "(content_type, generation, prompt_text, parent_ids, uses, total_score, avg_score, is_active, created_at) "
            "VALUES (?, ?, ?, ?, 0, 0.0, 0.0, 1, ?)",
            (
                content_type,
                generation,
                prompt_text,
                ",".join(str(i) for i in parent_ids),
                _now(),
            ),
        )
        return cur.lastrowid


def get_active_variants(
    content_type: str,
    db_path: str = DB_PATH,
) -> list[dict]:
    """
    返回该类型所有 is_active=1 的变体，按 avg_score 降序。
    每项格式：{"id": int, "prompt_text": str, "generation": int,
               "uses": int, "avg_score": float}
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, prompt_text, generation, uses, avg_score "
            "FROM prompt_variants WHERE content_type=? AND is_active=1 "
            "ORDER BY avg_score DESC",
            (content_type,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_variant_score(
    variant_id: int,
    score: float,
    db_path: str = DB_PATH,
) -> None:
    """在 jokes 生成后调用，更新变体的累计分和平均分。"""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE prompt_variants SET "
            "uses = uses + 1, "
            "total_score = total_score + ?, "
            "avg_score = (total_score + ?) / (uses + 1) "
            "WHERE id = ?",
            (score, score, variant_id),
        )


def seed_prompt_variants(db_path: str = DB_PATH) -> None:
    """
    将现有 5 个 .txt 文件作为第 0 代变体写入 DB（幂等：若该类型已有变体则跳过）。
    在 init_db() 末尾调用。
    """
    from contract import PROMPT_PATHS

    project_root = Path(__file__).resolve().parent
    with _connect(db_path) as conn:
        for ct, path in PROMPT_PATHS.items():
            existing = conn.execute(
                "SELECT COUNT(*) FROM prompt_variants WHERE content_type=?",
                (ct.value,),
            ).fetchone()[0]
            if existing == 0:
                text = (project_root / path).read_text(encoding="utf-8")
                conn.execute(
                    "INSERT INTO prompt_variants "
                    "(content_type, generation, prompt_text, parent_ids, uses, total_score, avg_score, is_active, created_at) "
                    "VALUES (?, 0, ?, '', 0, 0.0, 0.0, 1, ?)",
                    (ct.value, text, _now()),
                )


def save_knowledge(
    entry_type: str,
    content: str,
    content_type: Optional[str] = None,
    source_joke_ids: list[int] = None,
    relevance_score: float = 1.0,
    db_path: str = DB_PATH,
) -> int:
    """存入知识库。entry_type 见上方枚举。"""
    now = _now()
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO knowledge_base "
            "(content_type, entry_type, content, source_joke_ids, relevance_score, used_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
            (
                content_type,
                entry_type,
                content,
                ",".join(str(i) for i in (source_joke_ids or [])),
                relevance_score,
                now,
                now,
            ),
        )
        return cur.lastrowid


def get_knowledge(
    entry_type: Optional[str] = None,
    content_type: Optional[str] = None,
    limit: int = 20,
    db_path: str = DB_PATH,
) -> list[dict]:
    """按 relevance_score DESC 返回知识条目。"""
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
    """从知识库取 entry_type='gene' 的内容，供 evolution 使用。"""
    rows = get_knowledge(
        entry_type="gene",
        content_type=content_type,
        limit=limit,
        db_path=db_path,
    )
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
    """保存日报（upsert：同一天只保留最新一份）。"""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM daily_reports WHERE report_date = ?", (report_date,))
        cur = conn.execute(
            "INSERT INTO daily_reports "
            "(report_date, total_generated, avg_score, new_patterns, best_joke_id, report_md, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                report_date,
                total_generated,
                avg_score,
                new_patterns,
                best_joke_id,
                report_md,
                _now(),
            ),
        )
        return cur.lastrowid


def get_daily_reports(limit: int = 7, db_path: str = DB_PATH) -> list[dict]:
    """返回最近 limit 天的日报，按日期降序。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM daily_reports ORDER BY report_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def count_jokes_since(since_id: int, db_path: str = DB_PATH) -> int:
    """统计 id > since_id 的笑话数量，用于触发战略师。"""
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM jokes WHERE id > ? AND score_total IS NOT NULL",
            (since_id,),
        ).fetchone()[0]


def get_last_strategist_joke_id(db_path: str = DB_PATH) -> int:
    """返回上次战略师运行时最新的 joke id，用于增量复盘。存在 knowledge_base 的特殊记录里。"""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM knowledge_base WHERE entry_type='_checkpoint' LIMIT 1"
        ).fetchone()
    return int(row["content"]) if row else 0


def set_last_strategist_joke_id(joke_id: int, db_path: str = DB_PATH) -> None:
    """更新战略师检查点。"""
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM knowledge_base WHERE entry_type='_checkpoint'")
        conn.execute(
            "INSERT INTO knowledge_base (entry_type, content, source_joke_ids, relevance_score, created_at, updated_at) "
            "VALUES ('_checkpoint', ?, '', 0, ?, ?)",
            (str(joke_id), _now(), _now()),
        )


def upsert_job_status(
    job_name: str,
    status: str,
    result: dict = None,
    db_path: str = DB_PATH,
) -> None:
    """调度器每个 job 开始/结束时调用，幂等更新状态。"""
    import json as _json
    now = _now()
    result_str = _json.dumps(result, ensure_ascii=False) if result else None
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id, run_count FROM scheduler_jobs WHERE job_name=?", (job_name,)
        ).fetchone()
        if existing:
            new_count = existing["run_count"] + (1 if status == "success" else 0)
            conn.execute(
                "UPDATE scheduler_jobs SET last_run_at=?, last_status=?, last_result=?, "
                "run_count=?, updated_at=? WHERE job_name=?",
                (now, status, result_str, new_count, now, job_name),
            )
        else:
            conn.execute(
                "INSERT INTO scheduler_jobs (job_name, last_run_at, last_status, last_result, run_count, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_name, now, status, result_str, 1 if status == "success" else 0, now),
            )


def get_job_statuses(db_path: str = DB_PATH) -> list[dict]:
    """返回所有 job 的最新状态，供 API 读取。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM scheduler_jobs ORDER BY job_name"
        ).fetchall()
    return [dict(r) for r in rows]


def get_stop_flag(db_path: str = DB_PATH) -> bool:
    """返回是否有手动停止训练的请求。"""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT last_status FROM scheduler_jobs WHERE job_name='training_stop'"
        ).fetchone()
    return bool(row and row["last_status"] == "requested")


def set_stop_flag(requested: bool, db_path: str = DB_PATH) -> None:
    """设置或清除停止标志。"""
    status = "requested" if requested else "cleared"
    now = _now()
    with _connect(db_path) as conn:
        existing = conn.execute(
            "SELECT id FROM scheduler_jobs WHERE job_name='training_stop'"
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE scheduler_jobs SET last_status=?, updated_at=? WHERE job_name='training_stop'",
                (status, now),
            )
        else:
            conn.execute(
                "INSERT INTO scheduler_jobs (job_name, last_status, run_count, updated_at) VALUES (?,?,0,?)",
                ("training_stop", status, now),
            )


def get_current_directive(db_path: str = DB_PATH) -> str:
    """
    返回战略师最新下发的生成指令。
    指令以 entry_type='generation_directive' 存储在 knowledge_base 里。
    没有时返回空字符串（生成端按默认行为执行）。
    """
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM knowledge_base WHERE entry_type='generation_directive' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return row["content"] if row else ""
