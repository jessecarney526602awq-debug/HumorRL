"""
从用户提供的幽默语料压缩包提炼生成/战略师可读的案例参考。

输出：
    prompts/reference/humor_cases.txt
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "prompts" / "reference" / "humor_cases.txt"


def _repair_zip_name(name: str) -> str:
    for encoding in ("utf-8", "gbk"):
        try:
            return name.encode("cp437").decode(encoding)
        except Exception:
            continue
    return name


def _resolve_source(source: Path) -> Path:
    if source.is_dir():
        return source
    if source.suffix.lower() != ".zip":
        raise ValueError(f"不支持的输入类型：{source}")
    temp_dir = Path(tempfile.mkdtemp(prefix="humorrl_reference_"))
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            fixed_name = _repair_zip_name(info.filename)
            target = temp_dir / fixed_name
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    return temp_dir


def _clean_line(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    return text


def _extract_description(text: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(">"):
            return _clean_line(line.lstrip("> "))
    return ""


def _extract_snippets(text: str, limit: int = 2) -> list[str]:
    snippets: list[str] = []
    blocks = re.split(r"\n\s*\n", text)
    for block in blocks:
        if block.strip().startswith(">"):
            continue
        clean = _clean_line(re.sub(r"^\s*#+\s*", "", block, flags=re.MULTILINE))
        clean = clean.strip('“”"')
        if len(clean) < 25:
            continue
        if "语料库" in clean and "著称" in clean:
            continue
        if any(token in clean for token in ('"', "“", "”", "：")):
            if len(clean) > 220:
                clean = clean[:220].rstrip("，。； ") + "…"
            if clean not in snippets:
                snippets.append(clean)
        if len(snippets) >= limit:
            break
    return snippets


def _extract_good_jokes(text: str, limit: int = 6) -> list[str]:
    pattern = re.compile(r"^\s*#{2,3}\s*\d+(?:-\d+)?\.\s*(.*?)\s*-\s*评分[:：]\s*([0-9.]+)分\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    samples = []
    for index, match in enumerate(matches[:limit]):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = _clean_line(text[start:end].replace("\n", " "))
        if len(body) > 120:
            body = body[:120].rstrip("，。； ") + "…"
        title = match.group(1).strip()
        score = match.group(2)
        samples.append(f"{title}（{score}分）：{body}")
    return samples


def build_reference(source: Path) -> str:
    source_dir = _resolve_source(source)
    performer_files = sorted(source_dir.glob("脱口秀语料库-*.md"))
    good_jokes_file = next((path for path in source_dir.glob("好笑的笑话300个.md")), None)

    parts = [
        "# 中文幽默案例参考",
        "这些内容来自用户提供的幽默案例语料。学习其中的人设、观察角度、节奏和包袱落点，不要照抄任何原句。",
        "",
        "## 使用方式",
        "- 先找真实处境，再找被压抑的情绪，再做预期违背。",
        "- 学人设的稳定性、口语感和观察视角，不模仿具体文本。",
        "- 包袱尽量落在末句，避免解释。",
        "- 优先吸收和中文互联网、日常生活、打工人情绪相关的材料。",
    ]

    if good_jokes_file and good_jokes_file.exists():
        text = good_jokes_file.read_text(encoding="utf-8")
        parts.extend(
            [
                "",
                "## 高分短篇笑话样本",
                *[f"- {item}" for item in _extract_good_jokes(text)],
            ]
        )

    if performer_files:
        parts.extend(["", "## 脱口秀风格样本"])
    for path in performer_files:
        text = path.read_text(encoding="utf-8")
        title = next((line.strip("# ").strip() for line in text.splitlines() if line.startswith("# ")), path.stem)
        description = _extract_description(text)
        snippets = _extract_snippets(text, limit=2)
        parts.extend(["", f"### {title}"])
        if description:
            parts.append(f"- 风格描述：{description}")
        for snippet in snippets:
            parts.append(f"- 代表片段：{snippet}")

    return "\n".join(parts).strip() + "\n"


def main() -> int:
    default_source = Path("/Users/milo/Downloads/幽默语料.zip")
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else default_source
    text = build_reference(source)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(text, encoding="utf-8")
    print(f"幽默案例参考已生成：{OUTPUT_PATH}")
    print(text[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
