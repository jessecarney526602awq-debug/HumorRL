"""
HumorRL — Judge 路由层

Phase 1 目标：
1. 先做短/长内容二分
2. 对短内容做 rule-based 的轻量 subtype 分流
3. 给 humor_engine.score() 提供稳定的 route prompt block
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re

from contract import ContentType


SHORT_TYPES = {
    ContentType.COLD_JOKE,
    ContentType.TEXT_JOKE,
}

LONG_TYPES = {
    ContentType.STANDUP,
    ContentType.CROSSTALK,
    ContentType.HUMOR_STORY,
}

OBSERVATION_HINTS = {
    "上班", "下班", "老板", "同事", "开会", "工位", "打工", "工资", "租房", "房租",
    "外卖", "地铁", "相亲", "结婚", "离婚", "婆婆", "男朋友", "女朋友", "对象", "社恐",
    "爸妈", "妈妈", "爸爸", "孩子", "学校", "老师", "同学", "熬夜", "健身", "医院",
    "职场", "加班", "面试", "班味", "emo", "相亲", "装修", "旅游", "坐高铁",
}

LANGUAGE_HINTS = {
    "谐音", "双关", "同音", "字面", "别念", "听成", "看成", "简称", "缩写", "拼音",
    "读音", "一语双关", "字义", "同义", "歧义",
}

ABSURD_HINTS = {
    "外星人", "僵尸", "鬼", "神仙", "阎王", "天堂", "地狱", "穿越", "宇宙", "平行世界",
    "魔法", "机器人", "龙", "妖怪", "会说话的", "突然活了", "世界末日", "穿回", "超能力",
}

FIRST_PERSON_HINTS = {"我", "我们", "本人", "自己", "老子", "本来"}
QUESTION_ANSWER_MARKERS = ("为什么", "因为", "问", "答")


@dataclass
class JudgeRoute:
    shape: str
    subtype: str
    route_reason: str
    prompt_block: str


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def classify_shape(text: str, content_type: ContentType) -> str:
    if content_type in LONG_TYPES:
        return "long"
    if content_type in SHORT_TYPES:
        return "short"

    compact = _clean_text(text)
    line_count = max(1, text.count("\n") + 1)
    char_count = len(compact)
    if line_count >= 4 or char_count >= 140:
        return "long"
    return "short"


def classify_short_subtype(text: str, content_type: ContentType) -> str:
    compact = _clean_text(text)
    obs_hits = sum(1 for hint in OBSERVATION_HINTS if hint in compact)
    lang_hits = sum(1 for hint in LANGUAGE_HINTS if hint in compact)
    absurd_hits = sum(1 for hint in ABSURD_HINTS if hint in compact)
    first_person_hits = sum(1 for hint in FIRST_PERSON_HINTS if hint in compact)
    qa_hits = sum(1 for hint in QUESTION_ANSWER_MARKERS if hint in compact)

    if lang_hits >= 1 or (qa_hits >= 2 and len(compact) <= 60):
        return "language"
    if obs_hits >= 2 or (obs_hits >= 1 and first_person_hits >= 1):
        return "observation"
    if absurd_hits >= 1:
        return "absurd"

    if content_type == ContentType.COLD_JOKE:
        return "language"
    if content_type == ContentType.TEXT_JOKE:
        return "observation"
    return "general"


def display_band_for_score(weighted_total: float) -> str:
    if weighted_total < 3.0:
        return "明显烂梗"
    if weighted_total < 5.0:
        return "结构未成立"
    if weighted_total < 6.5:
        return "有点意思"
    if weighted_total < 8.0:
        return "明显好笑"
    return "高标准"


def estimate_display_score(weighted_total: float, shape: str, subtype: str) -> tuple[float, str, str]:
    score = round(weighted_total, 1)
    band = display_band_for_score(score)
    reason = (
        f"当前展示分使用 Phase 1 的 pointwise fallback。Judge 先按 {shape} 内容"
        f"{' / ' + subtype if subtype else ''} 路由，再给出便于人工查看的展示分段。"
    )
    return score, band, reason


def build_prompt_block(route: JudgeRoute) -> str:
    if route.shape == "long":
        return (
            "当前评分模式：长内容 Judge。\n"
            "不要只看整体印象，请显式考虑：铺垫是否建立、递进是否增强、结尾是否回收、"
            "中段是否塌陷、局部梗点和整体结构是否彼此支撑。\n"
            "不要因为篇幅较长就机械压分；也不要因为结构看起来完整就高估。"
        )

    common = (
        "当前评分模式：短内容 Judge。\n"
        "本轮主判断只抓三件事：预期违背、快速闭环、真实命中。\n"
        "这里的“真实命中”不是要求所有人都共鸣，而是看它是否准确击中某个清晰人群或情境的真实经验。\n"
        "不要把受众分化内容简单平均降级：如果目标人群命中很强，且圈外人仍能理解其成立原因，可以判为高质量。"
    )

    subtype_detail = {
        "language": (
            "短内容子类型：语言型。\n"
            "额外关注：联想距离是否刚好、歧义是否成立、是不是低级谐音、用词是否利落。"
        ),
        "observation": (
            "短内容子类型：观察型。\n"
            "额外关注：是否来自真实日常经验、是否命中真实情绪、视角是否新鲜。"
        ),
        "absurd": (
            "短内容子类型：荒诞型。\n"
            "额外关注：跳跃是否带来认知快感、是否自洽、是否只是随机胡说八道。"
        ),
        "general": (
            "短内容子类型：通用。\n"
            "当前 subtype 识别不够确定，请以短内容通用骨架为主，不要过度依赖单一机制。"
        ),
    }
    return common + "\n" + subtype_detail.get(route.subtype, subtype_detail["general"])


def route_judge(text: str, content_type: ContentType) -> JudgeRoute:
    shape = classify_shape(text, content_type)
    if shape == "long":
        return JudgeRoute(
            shape="long",
            subtype="general",
            route_reason=f"{content_type.value} 默认归入长内容 Judge，后续优先做结构级分析。",
            prompt_block=build_prompt_block(
                JudgeRoute(shape="long", subtype="general", route_reason="", prompt_block="")
            ),
        )

    subtype = classify_short_subtype(text, content_type)
    compact = _clean_text(text)
    route_reason = (
        f"{content_type.value} 归入短内容 Judge；长度={len(compact)}；"
        f"基于内容特征路由到 {subtype or 'general'} 子类型。"
    )
    route = JudgeRoute(shape="short", subtype=subtype, route_reason=route_reason, prompt_block="")
    route.prompt_block = build_prompt_block(route)
    return route
