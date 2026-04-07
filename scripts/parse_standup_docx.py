"""
解析带笑声标记的脱口秀文稿 `.docx`，输出 set-level 数据集。

Phase 1 目标：
- 稳定抽出每篇 stand-up 文稿
- 保留正文段落
- 保留笑声/掌声标记的位置和等级
- 先生成 `data/standup_sets.json`

默认输入：
    /Users/milo/Downloads/脱口秀文稿合集.docx

输出：
    data/standup_sets.json
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path("/Users/milo/Downloads/脱口秀文稿合集.docx")
OUTPUT_PATH = PROJECT_ROOT / "data" / "standup_sets.json"

DOC_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

SECTION_RE = re.compile(r"^第[一二三四五六七八九十]+部分[:：](.+)$")
TITLE_RE = re.compile(r"^(?:(.{0,8}))?《([^》]+)》(?:（([^）]+)）)?$")
MARKER_RE = re.compile(r"^【(.+?)】$")
TRAILING_PAGE_RE = re.compile(r"^(.*?)(\d+)$")
PUNCTUATION_RE = re.compile(r"[，。！？；：,.!?;:]")

REACTION_LEVELS = {
    "笑": 1,
    "爆笑": 2,
    "爆笑/欢呼": 3,
    "爆笑/掌声": 2,
    "欢呼": 2,
    "掌声": None,
}


@dataclass
class Marker:
    index: int
    marker: str
    level: int | None
    char_offset: int
    paragraph_index: int


@dataclass
class StandupSet:
    performer: str
    section: str
    title: str
    source_file: str
    source_type: str = "docx_compilation"
    source_section_index: int = 0
    paragraphs: list[str] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    clean_text: str = ""
    full_text: str = ""

    def finalize(self) -> dict:
        full_text, markers = _build_full_text_and_offsets(self.paragraphs, self.markers)
        clean_text = _normalize_text(full_text)
        reaction_summary = {
            "laugh_count": sum(1 for item in markers if item["level"] == 1),
            "big_laugh_count": sum(1 for item in markers if item["level"] and item["level"] >= 2),
            "applause_count": sum(1 for item in markers if "掌声" in item["marker"]),
        }
        return {
            "id": _slugify_id(self.performer, self.title),
            "performer": self.performer,
            "section": self.section,
            "title": self.title,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "source_section_index": self.source_section_index,
            "full_text": full_text,
            "clean_text": clean_text,
            "paragraphs": list(self.paragraphs),
            "markers": markers,
            "reaction_summary": reaction_summary,
            "is_excerpt": "高光" in self.section,
        }


def _read_docx_paragraphs(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", DOC_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", DOC_NS)).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def _normalize_text(text: str) -> str:
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _clean_heading(text: str) -> tuple[str, bool]:
    text = text.strip()
    matched = TRAILING_PAGE_RE.match(text)
    if matched and matched.group(1):
        body = matched.group(1).strip()
        if body.endswith("》") or body.endswith("）") or body.endswith("演出") or body.endswith("文稿"):
            return body, True
    return text, False


def _is_toc_line(text: str) -> bool:
    cleaned, trimmed = _clean_heading(text)
    return trimmed and (
        cleaned.startswith("第")
        or cleaned.startswith("《")
        or "《" in cleaned[:24]
    )


def _section_info(text: str) -> tuple[str, str] | None:
    cleaned, _ = _clean_heading(text)
    match = SECTION_RE.match(cleaned)
    if not match:
        return None
    label = cleaned
    body = match.group(1).strip()
    performer = re.split(r"(?:高光演出|完整文稿|《|（|\s)", body, maxsplit=1)[0].strip()
    return label, performer or body


def _title_info(text: str) -> str | None:
    cleaned, trimmed = _clean_heading(text)
    if "《" not in cleaned or "》" not in cleaned:
        return None
    if PUNCTUATION_RE.search(cleaned.split("》", 1)[-1]):
        return None
    if len(cleaned) > 28:
        return None
    match = TITLE_RE.match(cleaned)
    if match:
        prefix, title, suffix = match.groups()
        prefix = (prefix or "").strip()
        suffix = (suffix or "").strip()
        if prefix:
            title = f"{prefix}{title}"
        if suffix:
            title = f"{title}（{suffix}）"
        return title.strip()
    if cleaned.startswith("突围赛《") and cleaned.endswith("》"):
        return cleaned
    return cleaned if trimmed else None


def _marker_info(text: str) -> tuple[str, int | None] | None:
    match = MARKER_RE.match(text.strip())
    if not match:
        return None
    marker = match.group(1).strip()
    return marker, REACTION_LEVELS.get(marker)


def _fallback_title(section: str, performer: str) -> str:
    if performer and section:
        return section.split("：", 1)[-1].strip()
    return "未命名段子"


def _slugify_id(performer: str, title: str) -> str:
    mapping = {
        "付航": "fu_hang",
        "呼兰": "hu_lan",
        "毛豆": "mao_dou",
        "翟佳宁": "zhai_jia_ning",
        "嘻哈": "xi_ha",
    }
    performer_slug = mapping.get(performer, _ascii_slug(performer))
    title_slug = _ascii_slug(title)
    return f"standup_{performer_slug}_{title_slug}".strip("_")


def _ascii_slug(text: str) -> str:
    normalized = re.sub(r"[《》（）()【】\[\]：:、·\-/\s]+", "_", text)
    normalized = re.sub(r"[^0-9A-Za-z_\u4e00-\u9fff]+", "", normalized)
    normalized = normalized.strip("_").lower()
    return normalized or "item"


def _build_full_text_and_offsets(paragraphs: list[str], markers: list[Marker]) -> tuple[str, list[dict]]:
    parts: list[str] = []
    offsets_by_paragraph: list[int] = []
    current_offset = 0
    for idx, paragraph in enumerate(paragraphs):
        offsets_by_paragraph.append(current_offset)
        if idx > 0:
            parts.append("\n\n")
            current_offset += 2
        parts.append(paragraph)
        current_offset += len(paragraph)

    full_text = "".join(parts)
    serialized_markers: list[dict] = []
    for marker in markers:
        if not paragraphs:
            char_offset = 0
        elif marker.paragraph_index >= len(paragraphs):
            char_offset = len(full_text)
        else:
            char_offset = offsets_by_paragraph[marker.paragraph_index]
        serialized_markers.append(
            {
                "index": marker.index,
                "marker": marker.marker,
                "level": marker.level,
                "char_offset": char_offset,
                "paragraph_index": marker.paragraph_index,
            }
        )
    return full_text, serialized_markers


def parse_docx(source: Path) -> list[dict]:
    paragraphs = _read_docx_paragraphs(source)
    content_start = 0
    for idx, text in enumerate(paragraphs):
        section = _section_info(text)
        if section and not _clean_heading(text)[1]:
            content_start = idx
            break

    records: list[dict] = []
    current_section = ""
    current_performer = ""
    section_counter = 0
    current_set: StandupSet | None = None
    marker_index = 0

    def finalize_current() -> None:
        nonlocal current_set
        if current_set and current_set.paragraphs:
            records.append(current_set.finalize())
        current_set = None

    for raw in paragraphs[content_start:]:
        marker = _marker_info(raw)
        section = _section_info(raw)
        title = _title_info(raw)

        if section:
            finalize_current()
            current_section, current_performer = section
            section_counter += 1
            continue

        if title:
            finalize_current()
            current_set = StandupSet(
                performer=current_performer or "未知演员",
                section=current_section,
                title=title,
                source_file=source.name,
                source_section_index=section_counter,
            )
            continue

        if marker:
            if current_set is None:
                current_set = StandupSet(
                    performer=current_performer or "未知演员",
                    section=current_section,
                    title=_fallback_title(current_section, current_performer),
                    source_file=source.name,
                    source_section_index=section_counter,
                )
            current_set.markers.append(
                Marker(
                    index=marker_index,
                    marker=marker[0],
                    level=marker[1],
                    char_offset=0,
                    paragraph_index=len(current_set.paragraphs),
                )
            )
            marker_index += 1
            continue

        if _is_toc_line(raw):
            continue

        if current_set is None:
            current_set = StandupSet(
                performer=current_performer or "未知演员",
                section=current_section,
                title=_fallback_title(current_section, current_performer),
                source_file=source.name,
                source_section_index=section_counter,
            )
        current_set.paragraphs.append(raw.strip())

    finalize_current()
    return [record for record in records if record["full_text"].strip()]


def _print_preview(records: list[dict]) -> None:
    print(f"共解析 {len(records)} 篇 stand-up 文稿\n")
    for item in records[:8]:
        summary = item["reaction_summary"]
        preview = item["clean_text"].replace("\n", " ")[:80]
        print(
            f"- {item['performer']} / {item['title']} "
            f"(段落={len(item['paragraphs'])}, 笑={summary['laugh_count']}, "
            f"爆笑={summary['big_laugh_count']}, 掌声={summary['applause_count']})"
        )
        print(f"  {preview}")


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SOURCE
    records = parse_docx(source)
    payload = {
        "version": "1.0",
        "description": "脱口秀文稿 set-level 数据集（保留笑声/掌声标记位置）",
        "source": str(source),
        "standup_sets": records,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成：{OUTPUT_PATH}")
    _print_preview(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
