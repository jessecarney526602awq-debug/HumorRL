"""
首次运行执行此脚本，初始化数据库并导入种子数据。
python init_db.py
"""
import json
import os
import sys
import datetime

# 确保项目根目录在 path 里
sys.path.insert(0, os.path.dirname(__file__))

from db import init_db, save_joke, DB_PATH
from contract import ContentType, JokeRecord


def load_seed_jokes(path: str = "data/seed_jokes.json") -> None:
    if not os.path.exists(path):
        print(f"[跳过] 种子数据文件不存在：{path}")
        return

    with open(path, encoding="utf-8") as f:
        jokes = json.load(f)

    count = 0
    for j in jokes:
        record = JokeRecord(
            id=None,
            content_type=ContentType(j["content_type"]),
            text=j["text"],
            persona_id=None,
            score=None,
            human_rating=None,
            human_reaction=None,
            created_at=datetime.datetime.now(),
        )
        save_joke(record)
        count += 1

    print(f"[完成] 导入种子数据 {count} 条")


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    init_db()
    print(f"[完成] 数据库已初始化：{DB_PATH}")
    load_seed_jokes()
    print("\n准备就绪，运行以下命令启动：")
    print("  streamlit run app.py")
