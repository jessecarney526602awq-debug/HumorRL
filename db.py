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
        row = conn.execute("SELECT COUNT(*) FROM personas").fetchone()
        if row[0] == 0:
            for p in PRESET_PERSONAS:
                conn.execute(
                    "INSERT INTO personas (name, description, style_prompt, is_preset, created_at) "
                    "VALUES (?, ?, ?, 1, ?)",
                    (p["name"], p["description"], p["style_prompt"], _now()),
                )


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
            {"type": r["content_type"], "count": r["cnt"], "avg_score": r["avg_score"]}
            for r in rows
        ],
        "recent_scores": [
            {"score": r["score_total"], "created_at": r["created_at"]}
            for r in recent
        ],
    }
