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
    score_critique      TEXT DEFAULT '',
    judge_shape         TEXT DEFAULT '',
    judge_subtype       TEXT DEFAULT '',
    judge_route_reason  TEXT DEFAULT '',
    display_score       REAL,
    display_band        TEXT DEFAULT '',
    benchmark_reason    TEXT DEFAULT '',
    rank_score          REAL,
    rank_position       INTEGER,
    rank_group_size     INTEGER,
    is_funny            INTEGER,
    rank_justification  TEXT DEFAULT '',
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
CREATE INDEX IF NOT EXISTS idx_jokes_rank_score ON jokes(rank_score);

CREATE TABLE IF NOT EXISTS rank_comparisons (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT    NOT NULL,
    joke_ids        TEXT    NOT NULL DEFAULT '',
    ranking_order   TEXT    NOT NULL DEFAULT '',
    funny_flags     TEXT    NOT NULL DEFAULT '',
    anchor_ids      TEXT    NOT NULL DEFAULT '',
    anchor_accuracy REAL    NOT NULL DEFAULT 0.0,
    model           TEXT    NOT NULL DEFAULT '',
    raw_response    TEXT    NOT NULL DEFAULT '',
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rank_cmp_created ON rank_comparisons(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_rank_cmp_type    ON rank_comparisons(content_type);

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
        if "score_critique" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN score_critique TEXT DEFAULT ''"
            )
        if "judge_shape" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN judge_shape TEXT DEFAULT ''"
            )
        if "judge_subtype" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN judge_subtype TEXT DEFAULT ''"
            )
        if "judge_route_reason" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN judge_route_reason TEXT DEFAULT ''"
            )
        if "display_score" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN display_score REAL"
            )
        if "display_band" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN display_band TEXT DEFAULT ''"
            )
        if "benchmark_reason" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN benchmark_reason TEXT DEFAULT ''"
            )
        if "rank_score" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN rank_score REAL"
            )
        if "rank_position" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN rank_position INTEGER"
            )
        if "rank_group_size" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN rank_group_size INTEGER"
            )
        if "is_funny" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN is_funny INTEGER"
            )
        if "rank_justification" not in cols:
            conn.execute(
                "ALTER TABLE jokes ADD COLUMN rank_justification TEXT DEFAULT ''"
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
    placeholders = ",".join(["?"] * 28)
    with _connect(db_path) as conn:
        cur = conn.execute(
            f"""INSERT INTO jokes
               (content_type, text, persona_id,
                score_structure, score_surprise, score_relatability,
                score_language, score_creativity, score_safety,
                score_total, score_reasoning, score_critique,
                judge_shape, judge_subtype, judge_route_reason,
                display_score, display_band, benchmark_reason,
                rank_score, rank_position, rank_group_size, is_funny, rank_justification,
                human_rating, human_reaction,
                parent_id, rewrite_round, created_at)
               VALUES ({placeholders})""",
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
                s.critique     if s else "",
                s.judge_shape  if s else "",
                s.judge_subtype if s else "",
                s.route_reason if s else "",
                s.display_score if s else None,
                s.display_band if s else "",
                s.benchmark_reason if s else "",
                joke.rank_score,
                joke.rank_position,
                joke.rank_group_size,
                int(joke.is_funny) if joke.is_funny is not None else None,
                joke.rank_justification,
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
        conditions.append("COALESCE(rank_score, score_total) >= ?")
        params.append(min_score)
    if unrated_only:
        conditions.append("human_rating IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM jokes {where} ORDER BY COALESCE(rank_score, score_total) DESC NULLS LAST LIMIT ?",
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
            critique=r["score_critique"] or "",
            judge_shape=r["judge_shape"] or "",
            judge_subtype=r["judge_subtype"] or "",
                route_reason=r["judge_route_reason"] or "",
                display_score=float(r["display_score"]) if r["display_score"] is not None else None,
                display_band=r["display_band"] or "",
                benchmark_reason=r["benchmark_reason"] or "",
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
            rank_score=float(r["rank_score"]) if r["rank_score"] is not None else None,
            rank_position=int(r["rank_position"]) if r["rank_position"] is not None else None,
            rank_group_size=int(r["rank_group_size"]) if r["rank_group_size"] is not None else None,
            is_funny=bool(r["is_funny"]) if r["is_funny"] is not None else None,
            rank_justification=r["rank_justification"] or "",
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
            "SELECT content_type, COUNT(*) as cnt, AVG(COALESCE(rank_score, score_total)) as avg_score "
            "FROM jokes GROUP BY content_type"
        ).fetchall()
        recent = conn.execute(
            "SELECT COALESCE(rank_score, score_total) as reward, created_at FROM jokes "
            "WHERE COALESCE(rank_score, score_total) IS NOT NULL ORDER BY created_at DESC LIMIT 100"
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
            {"score": float(r["reward"] or 0.0), "created_at": r["created_at"]}
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
            critique=row["score_critique"] or "",
            judge_shape=row["judge_shape"] or "",
            judge_subtype=row["judge_subtype"] or "",
            route_reason=row["judge_route_reason"] or "",
            display_score=float(row["display_score"]) if row["display_score"] is not None else None,
            display_band=row["display_band"] or "",
            benchmark_reason=row["benchmark_reason"] or "",
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
        rank_score=float(row["rank_score"]) if row["rank_score"] is not None else None,
        rank_position=int(row["rank_position"]) if row["rank_position"] is not None else None,
        rank_group_size=int(row["rank_group_size"]) if row["rank_group_size"] is not None else None,
        is_funny=bool(row["is_funny"]) if row["is_funny"] is not None else None,
        rank_justification=row["rank_justification"] or "",
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


def save_rank_comparison(
    content_type: str,
    joke_ids: list[int],
    ranking_order: list[int],
    funny_flags: list[bool],
    anchor_ids: list[int],
    anchor_accuracy: float,
    model: str,
    raw_response: str,
    db_path: str = DB_PATH,
) -> int:
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO rank_comparisons "
            "(content_type, joke_ids, ranking_order, funny_flags, anchor_ids, anchor_accuracy, model, raw_response, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                content_type,
                json.dumps(joke_ids, ensure_ascii=False),
                json.dumps(ranking_order, ensure_ascii=False),
                json.dumps([bool(flag) for flag in funny_flags], ensure_ascii=False),
                json.dumps(anchor_ids, ensure_ascii=False),
                float(anchor_accuracy),
                model,
                raw_response,
                _now(),
            ),
        )
        return cur.lastrowid


def get_rank_stats(recent_n: int = 50, db_path: str = DB_PATH) -> dict:
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT anchor_accuracy, funny_flags, content_type, created_at "
            "FROM rank_comparisons ORDER BY created_at DESC LIMIT ?",
            (recent_n,),
        ).fetchall()

    if not rows:
        return {
            "count": 0,
            "avg_anchor_accuracy": 0.0,
            "not_funny_ratio": 0.0,
            "by_type": {},
        }

    all_flags: list[bool] = []
    by_type: dict[str, dict[str, float | int]] = {}
    for row in rows:
        flags = json.loads(row["funny_flags"] or "[]")
        bool_flags = [bool(flag) for flag in flags]
        all_flags.extend(bool_flags)
        content_type = row["content_type"]
        bucket = by_type.setdefault(content_type, {"count": 0, "not_funny_ratio": 0.0})
        bucket["count"] += 1
        if bool_flags:
            not_funny_ratio = sum(1 for flag in bool_flags if not flag) / len(bool_flags)
            bucket["not_funny_ratio"] += not_funny_ratio

    for content_type, bucket in by_type.items():
        if bucket["count"]:
            bucket["not_funny_ratio"] = round(bucket["not_funny_ratio"] / bucket["count"], 4)

    avg_anchor_accuracy = sum(float(row["anchor_accuracy"] or 0.0) for row in rows) / len(rows)
    not_funny_ratio = (
        sum(1 for flag in all_flags if not flag) / len(all_flags)
        if all_flags else 0.0
    )
    return {
        "count": len(rows),
        "avg_anchor_accuracy": round(avg_anchor_accuracy, 4),
        "not_funny_ratio": round(not_funny_ratio, 4),
        "by_type": by_type,
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
            "SELECT COUNT(*) FROM jokes WHERE id > ? AND COALESCE(rank_score, score_total) IS NOT NULL",
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
    return get_latest_knowledge_content("generation_directive", db_path=db_path)


def get_current_judge_directive(db_path: str = DB_PATH) -> str:
    """返回战略师最新下发的评分原则。"""
    return get_latest_knowledge_content("judge_directive", db_path=db_path)


def get_latest_knowledge_content(entry_type: str, db_path: str = DB_PATH) -> str:
    """返回某类知识的最新一条 content。没有时返回空字符串。"""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM knowledge_base WHERE entry_type=? "
            "ORDER BY created_at DESC LIMIT 1"
            , (entry_type,)
        ).fetchone()
    return row["content"] if row else ""


def load_calibration_set(path: str = None) -> list[dict]:
    """
    从 data/calibration_set.json 加载校准数据。
    返回 list[dict]，每个 dict 含 id, text, content_type, label, expected_score, why, tags。
    """
    if path is None:
        path = str(Path(__file__).resolve().parent / "data" / "calibration_set.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data["calibration_jokes"]


def save_calibration_run(
    run_date: str,
    overall_correlation: float,
    dimension_biases: dict,
    classification_accuracy: dict,
    report_md: str,
    db_path: str = DB_PATH,
) -> int:
    """保存一次校准运行结果到 knowledge_base。"""
    content = json.dumps(
        {
            "run_date": run_date,
            "overall_correlation": overall_correlation,
            "dimension_biases": dimension_biases,
            "classification_accuracy": classification_accuracy,
            "report_md": report_md,
        },
        ensure_ascii=False,
    )
    return save_knowledge(
        entry_type="judge_calibration",
        content=content,
        relevance_score=1.5,
        db_path=db_path,
    )


def get_latest_calibration(db_path: str = DB_PATH) -> dict | None:
    """返回最近一次校准结果（parsed dict），无则返回 None。"""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT content FROM knowledge_base WHERE entry_type='judge_calibration' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return json.loads(row["content"])


def get_top_jokes(
    content_type: str = None,
    limit: int = 3,
    min_score: float = 7.5,
    db_path: str = DB_PATH,
) -> list[JokeRecord]:
    """返回高分 JokeRecord 列表，用于注入 Generator prompt。"""
    with _connect(db_path) as conn:
        if content_type:
            rows = conn.execute(
                "SELECT * FROM jokes WHERE COALESCE(rank_score, score_total) >= ? "
                "AND COALESCE(rank_score, score_total) IS NOT NULL "
                "AND content_type = ? ORDER BY COALESCE(rank_score, score_total) DESC LIMIT ?",
                (min_score, content_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jokes WHERE COALESCE(rank_score, score_total) >= ? "
                "AND COALESCE(rank_score, score_total) IS NOT NULL "
                "ORDER BY COALESCE(rank_score, score_total) DESC LIMIT ?",
                (min_score, limit),
            ).fetchall()
    return [_row_to_joke_record(row) for row in rows]
