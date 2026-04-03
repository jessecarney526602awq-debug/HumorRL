"""
解析用户提供的幽默语料压缩包，生成 Judge 校准数据集。

默认优先读取压缩包中的：
- 好笑的笑话100个.md
- 不好笑的笑话100个.md

用法：
    python scripts/parse_calibration.py /path/to/幽默语料.zip
    python scripts/parse_calibration.py /path/to/extracted_dir
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "calibration_set.json"

PREFERRED_FILES = [
    "好笑的笑话100个.md",
    "不好笑的笑话100个.md",
]

ENTRY_RE = re.compile(
    r"^\s*#{2,3}\s*(\d+(?:-\d+)?)\.\s*(.*?)\s*-\s*评分[:：]\s*([0-9.]+)分\s*$",
    re.MULTILINE,
)


def _repair_zip_name(name: str) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return name.encode("cp437").decode(encoding)
        except Exception:
            continue
    return name


def _extract_zip(zip_path: Path) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="humorrl_calibration_"))
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            fixed_name = _repair_zip_name(info.filename)
            target = temp_dir / fixed_name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    return temp_dir


def _resolve_source(source: Path) -> Path:
    if source.is_dir():
        return source
    if source.suffix.lower() == ".zip":
        return _extract_zip(source)
    raise ValueError(f"不支持的输入类型：{source}")


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def classify_content_type(text: str) -> str:
    compact = text.replace(" ", "")
    if "甲：" in compact and "乙：" in compact:
        return "crosstalk"
    if len(text) > 220 and any(token in text for token in ("有一次", "后来", "结果", "那天", "最后", "然后")):
        return "humor_story"
    if len(text) < 70:
        if any(token in text for token in ("字", "词", "谐音", "断句", "成语", "双关")):
            return "text_joke"
        if any(token in text for token in ("为什么", "因为", "问：", "答：", "?", "？")):
            return "cold_joke"
        return "text_joke"
    return "standup"


def _clamp_expected(score: float, label: str) -> float:
    if label == "funny":
        return min(9.5, max(7.5, score))
    if label == "not_funny":
        return min(4.0, max(1.0, score))
    return min(7.0, max(4.5, score))


def _why_text(label: str, raw_score: float, content_type: str, text: str) -> str:
    label_text = {"funny": "好笑", "not_funny": "不好笑", "medium": "中等"}.get(label, label)
    reasons = [f"源文件标注为{label_text}，标题评分 {raw_score:.1f}"]
    if content_type == "crosstalk":
        reasons.append("含对话往返结构")
    elif content_type == "humor_story":
        reasons.append("篇幅较长，具备叙事推进")
    elif content_type == "cold_joke":
        reasons.append("短句问答/反转，更接近冷笑话")
    elif content_type == "text_joke":
        reasons.append("短句文字梗或极简包袱")
    else:
        reasons.append("默认按脱口秀观察段子处理")
    if len(text) < 25:
        reasons.append("文本较短")
    elif len(text) > 180:
        reasons.append("文本较长")
    return "；".join(reasons)


def _parse_markdown_entries(path: Path, label: str) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    matches = list(ENTRY_RE.finditer(text))
    items = []
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        raw_score = float(match.group(3))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        body = re.sub(r"^\s*---+\s*$", "", body, flags=re.MULTILINE)
        body = _normalize_text(body)
        if not body:
            continue
        content_type = classify_content_type(body)
        items.append(
            {
                "title": title,
                "text": body,
                "content_type": content_type,
                "label": label,
                "expected_score": _clamp_expected(raw_score, label),
                "raw_score": raw_score,
                "why": _why_text(label, raw_score, content_type, body),
                "tags": [],
            }
        )
    return items


def _find_calibration_files(source_dir: Path) -> list[Path]:
    all_md = list(source_dir.rglob("*.md"))
    preferred = []
    for name in PREFERRED_FILES:
        matched = next((path for path in all_md if path.name == name), None)
        if matched:
            preferred.append(matched)
    if preferred:
        return preferred
    fallback = [
        path for path in all_md
        if ("好笑" in path.name or "不好笑" in path.name) and "300" not in path.name
    ]
    if fallback:
        return sorted(fallback)
    raise FileNotFoundError("没有找到可用于校准的 好笑/不好笑 markdown 文件")


def parse_source(source: Path) -> list[dict]:
    source_dir = _resolve_source(source)
    calibration_files = _find_calibration_files(source_dir)

    jokes = []
    next_id = 1
    for path in calibration_files:
        label = "not_funny" if "不好笑" in path.name else "funny"
        for item in _parse_markdown_entries(path, label):
            jokes.append(
                {
                    "id": next_id,
                    "text": item["text"],
                    "content_type": item["content_type"],
                    "label": item["label"],
                    "expected_score": item["expected_score"],
                    "why": item["why"],
                    "tags": item["tags"],
                }
            )
            next_id += 1
    return jokes


def _print_preview(jokes: list[dict]) -> None:
    funny = [item for item in jokes if item["label"] == "funny"][:3]
    not_funny = [item for item in jokes if item["label"] == "not_funny"][:3]

    print("\n=== 好笑组预览 ===")
    for item in funny:
        preview = item["text"].replace("\n", " ")[:80]
        print(f"[{item['id']}] ({item['content_type']}, {item['expected_score']:.1f}) {preview}")

    print("\n=== 不好笑组预览 ===")
    for item in not_funny:
        preview = item["text"].replace("\n", " ")[:80]
        print(f"[{item['id']}] ({item['content_type']}, {item['expected_score']:.1f}) {preview}")


def main() -> int:
    default_source = Path("/Users/milo/Downloads/幽默语料.zip")
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else default_source
    jokes = parse_source(source)

    payload = {
        "version": "1.0",
        "description": "Judge 校准数据集：来自用户提供的好笑/不好笑笑话样本",
        "source": str(source),
        "calibration_jokes": jokes,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    counts = {}
    for item in jokes:
        counts[item["label"]] = counts.get(item["label"], 0) + 1

    print(f"校准数据集已生成：{OUTPUT_PATH}")
    print(f"总计 {len(jokes)} 条：{counts}")
    _print_preview(jokes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
