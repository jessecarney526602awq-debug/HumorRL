"""
stand-up 人设资料读取与格式化

目标：
- 允许 profiles 文件既支持旧版字符串，也支持新版结构化 persona 对象
- 为生成 / Judge / 拆段 / 改写提供统一的人设文本块
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_profiles(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    if path.suffix.lower() == ".md":
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        plain_text = text.replace("**", "").replace("__", "")
        name_match = re.search(r"姓名\s*[：:]\s*([^\n]+)", plain_text)
        heading_match = re.search(r"^#\s*([^\n（(]+)", text, flags=re.MULTILINE)
        name = (
            (name_match.group(1).strip() if name_match else "")
            or (heading_match.group(1).strip() if heading_match else "")
            or path.stem
        )
        return {
            name: {
                "source_markdown": text,
                "one_line": "",
            }
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "profiles" in data and isinstance(data["profiles"], dict):
        data = data["profiles"]
    return data if isinstance(data, dict) else {}


def _to_lines(values: Any) -> list[str]:
    if isinstance(values, list):
        return [str(item).strip() for item in values if str(item).strip()]
    if isinstance(values, str) and values.strip():
        return [values.strip()]
    return []


def _format_list_block(title: str, values: Any) -> str:
    lines = _to_lines(values)
    if not lines:
        return ""
    return f"{title}：\n" + "\n".join(f"- {line}" for line in lines)


def _format_structured_profile(profile: dict[str, Any], detailed: bool = True) -> str:
    parts: list[str] = []

    source_markdown = str(profile.get("source_markdown", "")).strip()
    if source_markdown:
        return (
            "使用原则：以下是后台人物资料，不是台上逐条说给观众听的素材。"
            "默认不要直接搬出资料里的具体人名、小圈子内部称呼、私密关系细节。"
            "优先转成观众一听就懂的关系称呼，比如“发小”“同学”“前同事”“亲戚”“邻居”。"
            "只有当专有名词本身就是必要信息或包袱的一部分时，才允许保留，而且要先让观众听懂。\n\n"
            f"{source_markdown}"
        )

    one_line = str(profile.get("one_line", "")).strip()
    if one_line:
        parts.append(f"一句话定位：{one_line}")

    direct_map = [
        ("社会身份", "social_identity"),
        ("人生处境", "life_context"),
        ("核心驱动力", "core_drive"),
        ("情绪底色", "emotion_base"),
        ("说话方式", "voice"),
        ("观众关系", "audience_relationship"),
        ("收尾偏好", "ending_preferences"),
    ]
    for label, key in direct_map:
        value = str(profile.get(key, "")).strip()
        if value:
            parts.append(f"{label}：{value}")

    for label, key in [
        ("关键经历", "life_experience"),
        ("幽默发动方式", "humor_engine"),
        ("常聊主题", "preferred_topics"),
        ("尽量规避", "avoid"),
    ]:
        block = _format_list_block(label, profile.get(key))
        if block:
            parts.append(block)

    if detailed:
        for label, key in [
            ("结构偏好", "structure_preferences"),
            ("人设一致性检查", "persona_consistency_checks"),
        ]:
            block = _format_list_block(label, profile.get(key))
            if block:
                parts.append(block)

    return "\n\n".join(part for part in parts if part.strip()).strip()


def build_profile_block(
    performer: str,
    profiles: dict[str, Any],
    *,
    fallback: str,
    detailed: bool = True,
) -> str:
    raw = profiles.get(performer)
    if raw is None:
        return fallback
    if isinstance(raw, str):
        return raw.strip() or fallback
    if isinstance(raw, dict):
        formatted = _format_structured_profile(raw, detailed=detailed)
        return formatted or fallback
    return fallback
