"""
HumorRL — 生成与评分引擎

生成：豆包 Doubao-Seed-2.0-lite（temperature 0.9）
评分：豆包 Doubao-Seed-2.0-lite（temperature 0.3）
战略：豆包 Doubao-Seed-2.0-pro（temperature 0.3，在 strategist.py 中调用）
"""

import json
import os
from pathlib import Path
import re

from dotenv import load_dotenv
from openai import OpenAI

import db
import judge_router
from contract import (
    CONTENT_TYPE_LABELS,
    PROMPT_PATHS,
    SCORE_PROMPT_PATH,
    ContentType,
    GenerationRequest,
    JokeRecord,
    ScoreResult,
)

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
HUMOR_REFERENCE_PATH = "prompts/reference/humor_cases.txt"
DISPLAY_PROMPT_PATH = "prompts/evaluate/display_position.txt"
LONG_STRUCTURE_PROMPT_PATH = "prompts/evaluate/long_structure.txt"
DISPLAY_TARGETS = {
    "short": [2.0, 4.0, 6.0, 7.5, 8.5],
    "long": [4.0, 5.5, 7.0, 8.5, 9.2],
}

_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"


# ─────────────────────────────────────────
# 三个独立的 LLM 客户端
# ─────────────────────────────────────────

def _writer_client() -> OpenAI:
    """豆包 lite — 负责生成笑话（快速）"""
    key = os.getenv("DOUBAO_API_KEY")
    if not key:
        raise RuntimeError("DOUBAO_API_KEY 未设置")
    return OpenAI(api_key=key, base_url=_DOUBAO_BASE_URL)


def _judge_client() -> OpenAI:
    """豆包 lite — 负责评分（快速）"""
    key = os.getenv("DOUBAO_API_KEY")
    if not key:
        raise RuntimeError("DOUBAO_API_KEY 未设置")
    return OpenAI(api_key=key, base_url=_DOUBAO_BASE_URL)


def _strategist_client() -> OpenAI:
    """豆包 pro — 负责战略复盘（深度推理）"""
    key = os.getenv("DOUBAO_API_KEY")
    if not key:
        raise RuntimeError("DOUBAO_API_KEY 未设置")
    return OpenAI(api_key=key, base_url=_DOUBAO_BASE_URL)


def _chat(client: OpenAI, model: str, prompt: str, temperature: float, max_tokens: int,
          role: str = "writer") -> str:
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = resp.usage
    if usage:
        try:
            import db as _db
            _db.log_api_cost(
                model=model,
                role=role,
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
            )
        except Exception:
            pass
    return resp.choices[0].message.content.strip()


def _read_prompt(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def _default_score(reasoning: str) -> ScoreResult:
    return ScoreResult(
        structure=5, surprise=5, relatability=5,
        language=5, creativity=5, safety=5,
        reasoning=reasoning,
    )


def _default_long_structure() -> dict[str, str]:
    return {
        "structure_summary": "",
        "best_moment": "",
        "weakest_moment": "",
        "structure_guidance": "",
    }


def display_track_value(score: ScoreResult | None) -> float | None:
    if score is None:
        return None
    if score.display_score is not None:
        return float(score.display_score)
    return float(score.weighted_total)


def _clean_json_payload(raw: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return cleaned.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _parse_score_json(raw: str) -> ScoreResult:
    data = json.loads(_clean_json_payload(raw))
    critique = str(data.get("critique", ""))
    reasoning = str(data.get("reasoning", ""))
    if not reasoning and critique:
        reasoning = critique
    return ScoreResult(
        structure=max(0.0, min(10.0, float(data["structure"]))),
        surprise=max(0.0, min(10.0, float(data["surprise"]))),
        relatability=max(0.0, min(10.0, float(data["relatability"]))),
        language=max(0.0, min(10.0, float(data["language"]))),
        creativity=max(0.0, min(10.0, float(data["creativity"]))),
        safety=max(0.0, min(10.0, float(data["safety"]))),
        reasoning=reasoning,
        critique=critique,
    )


def _looks_like_collapsed_score(score: ScoreResult) -> bool:
    """
    豆包 lite 在当前 judge prompt 下会偶发性收敛到同一组模板分。
    命中这组向量时，触发一次更严格的复评。
    """
    vector = (
        round(score.structure, 2),
        round(score.surprise, 2),
        round(score.relatability, 2),
        round(score.language, 2),
        round(score.creativity, 2),
        round(score.safety, 2),
    )
    return vector == (8.0, 7.0, 9.0, 8.0, 6.0, 10.0)


def _parse_long_structure_json(raw: str) -> dict[str, str]:
    data = json.loads(_clean_json_payload(raw))
    return {
        "structure_summary": str(data.get("structure_summary", "")).strip(),
        "best_moment": str(data.get("best_moment", "")).strip(),
        "weakest_moment": str(data.get("weakest_moment", "")).strip(),
        "structure_guidance": str(data.get("structure_guidance", "")).strip(),
    }


def _anchor_excerpt(text: str, limit: int = 22) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def _select_display_anchors(content_type: ContentType, route_shape: str) -> list[dict]:
    calibration = db.load_calibration_set()

    def item_shape(item: dict) -> str:
        try:
            return judge_router.classify_shape(item["text"], ContentType(item["content_type"]))
        except Exception:
            return "short"

    targets = DISPLAY_TARGETS.get(route_shape, DISPLAY_TARGETS["short"])
    selected: list[dict] = []
    used_ids: set[int] = set()

    for target in targets:
        candidates = [item for item in calibration if item["id"] not in used_ids]
        if not candidates:
            break

        def sort_key(item: dict):
            same_type_penalty = 0.0 if item["content_type"] == content_type.value else 0.35
            same_shape_penalty = 0.0 if item_shape(item) == route_shape else 0.35
            distance = abs(float(item["expected_score"]) - target)
            return (distance + same_type_penalty + same_shape_penalty, distance, int(item["id"]))

        best = min(candidates, key=sort_key)
        selected.append(best)
        used_ids.add(int(best["id"]))

    selected.sort(key=lambda item: (float(item["expected_score"]), int(item["id"])))
    return selected


def _build_anchor_block(anchors: list[dict]) -> str:
    return "\n".join(
        f"[A{item['id']}] ({float(item['expected_score']):.1f}分, {item['label']}) "
        f"{re.sub(r'\\s+', ' / ', item['text']).strip()}"
        for item in anchors
    )


def _parse_display_position(raw: str, allowed_ids: list[str]) -> tuple[list[str], float, str]:
    data = json.loads(_clean_json_payload(raw))
    ranking = data.get("ranking", [])
    ordered: list[str] = []
    for item in ranking:
        candidate_id = str(item.get("id") if isinstance(item, dict) else item).strip()
        if candidate_id in allowed_ids and candidate_id not in ordered:
            ordered.append(candidate_id)
    for candidate_id in allowed_ids:
        if candidate_id not in ordered:
            ordered.append(candidate_id)

    relative = max(0.0, min(1.0, float(data.get("relative_position", 0.5))))
    reason = str(data.get("candidate_reason", "")).strip()
    return ordered, relative, reason


def _project_display_score(
    ordered_ids: list[str],
    anchors: list[dict],
    relative_position: float,
    candidate_reason: str,
) -> tuple[float, str, str]:
    anchor_ids = [f"A{item['id']}" for item in anchors]
    anchor_scores = {f"A{item['id']}": float(item["expected_score"]) for item in anchors}
    anchor_items = {f"A{item['id']}": item for item in anchors}
    sorted_anchors = sorted(anchors, key=lambda item: (float(item["expected_score"]), int(item["id"])))

    try:
        candidate_idx = ordered_ids.index("C1")
    except ValueError:
        candidate_idx = max(0, len(ordered_ids) // 2)
    better_anchor_count = sum(1 for item_id in ordered_ids[:candidate_idx] if item_id in anchor_ids)
    total_anchors = len(sorted_anchors)

    if better_anchor_count == 0:
        high = sorted_anchors[-1]
        high_score = float(high["expected_score"])
        score = min(10.0, round(high_score + 0.2 + 0.6 * relative_position, 1))
        benchmark = (
            f"{candidate_reason or '当前内容被放在所有锚点之上。'} "
            f"定位结果：高于最高锚点 {high_score:.1f} 分《{_anchor_excerpt(high['text'])}》。"
        ).strip()
    elif better_anchor_count >= total_anchors:
        low = sorted_anchors[0]
        low_score = float(low["expected_score"])
        score = max(0.5, round(low_score - (0.2 + 0.6 * relative_position), 1))
        benchmark = (
            f"{candidate_reason or '当前内容被放在所有锚点之下。'} "
            f"定位结果：低于最低锚点 {low_score:.1f} 分《{_anchor_excerpt(low['text'])}》。"
        ).strip()
    else:
        lower = sorted_anchors[total_anchors - better_anchor_count - 1]
        upper = sorted_anchors[total_anchors - better_anchor_count]
        low_score = float(lower["expected_score"])
        high_score = float(upper["expected_score"])
        score = round(low_score + (high_score - low_score) * relative_position, 1)
        benchmark = (
            f"{candidate_reason or '当前内容位于两个锚点之间。'} "
            f"定位结果：介于 {low_score:.1f} 分《{_anchor_excerpt(lower['text'])}》"
            f"和 {high_score:.1f} 分《{_anchor_excerpt(upper['text'])}》之间。"
        ).strip()

    band = judge_router.display_band_for_score(score)
    return score, band, benchmark


def _anchor_display_score(
    text: str,
    content_type: ContentType,
    route,
    judge_directive: str,
    judge_lessons_block: str,
    long_structure: dict[str, str] | None = None,
) -> tuple[float, str, str]:
    anchors = _select_display_anchors(content_type, route.shape)
    if len(anchors) < 3:
        raise RuntimeError("展示锚点不足，无法做稳定定位")

    prompt = (
        _read_prompt(DISPLAY_PROMPT_PATH)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{candidate_text}", text)
        .replace("{anchor_block}", _build_anchor_block(anchors))
    )
    prompt += f"\n\nJudge 路由信息（必须遵守）：\n{route.prompt_block}"
    if long_structure and long_structure.get("structure_guidance"):
        prompt += f"\n\n长内容结构预分析：\n{long_structure['structure_guidance']}"
    if judge_directive:
        prompt += f"\n\n当前战略师追加评分原则：\n{judge_directive}"
    if judge_lessons_block:
        prompt += f"\n\n{judge_lessons_block}"

    model = os.getenv("DOUBAO_JUDGE_MODEL", "doubao-seed-2.0-lite-250315")
    raw = _chat(_judge_client(), model, prompt, temperature=0.2, max_tokens=512, role="judge")
    ordered_ids, relative_position, candidate_reason = _parse_display_position(
        raw,
        ["C1", *[f"A{item['id']}" for item in anchors]],
    )
    return _project_display_score(ordered_ids, anchors, relative_position, candidate_reason)


def _analyze_long_structure(text: str, content_type: ContentType, route) -> dict[str, str]:
    if route.shape != "long":
        return _default_long_structure()

    prompt = (
        _read_prompt(LONG_STRUCTURE_PROMPT_PATH)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{text}", text)
    )
    prompt += f"\n\nJudge 路由信息（必须遵守）：\n{route.prompt_block}"
    model = os.getenv("DOUBAO_JUDGE_MODEL", "doubao-seed-2.0-lite-250315")
    raw = _chat(_judge_client(), model, prompt, temperature=0.2, max_tokens=512, role="judge")
    return _parse_long_structure_json(raw)


def _hydrate_display_fields(
    result: ScoreResult,
    text: str,
    content_type: ContentType,
    route,
    judge_directive: str,
    judge_lessons_block: str,
    long_structure: dict[str, str] | None = None,
) -> ScoreResult:
    result.judge_shape = route.shape
    result.judge_subtype = route.subtype
    result.route_reason = route.route_reason
    if long_structure:
        result.structure_summary = long_structure.get("structure_summary", "")
        result.best_moment = long_structure.get("best_moment", "")
        result.weakest_moment = long_structure.get("weakest_moment", "")
    try:
        result.display_score, result.display_band, result.benchmark_reason = _anchor_display_score(
            text,
            content_type,
            route,
            judge_directive,
            judge_lessons_block,
            long_structure=long_structure,
        )
    except Exception:
        result.display_score, result.display_band, result.benchmark_reason = (
            judge_router.estimate_display_score(
                result.weighted_total,
                route.shape,
                route.subtype,
            )
        )
    return result


# ─────────────────────────────────────────
# 公开接口
# ─────────────────────────────────────────

def generate(req: GenerationRequest) -> list[str]:
    """MiniMax 生成 req.n 条内容。优先使用进化后的最优 Prompt 变体。"""
    try:
        variants = db.get_active_variants(req.content_type.value)
        if variants and variants[0]["uses"] >= 5:
            prompt = variants[0]["prompt_text"]
        else:
            prompt = _read_prompt(PROMPT_PATHS[req.content_type])
    except Exception:
        prompt = _read_prompt(PROMPT_PATHS[req.content_type])

    persona_block = ""
    if req.persona is not None:
        persona_block = f"你的角色设定：\n{req.persona.style_prompt}"

    # 从 DB 读取战略师最新指令（无指令时留空，生成端自主发挥）
    strategy_context = ""
    try:
        directive = db.get_current_directive()
        if directive:
            strategy_context = directive
    except Exception:
        pass

    prompt = (
        prompt.replace("{persona_block}", persona_block)
        .replace("{topic}", req.topic or "（随机选择一个日常生活话题）")
        .replace("{n}", str(req.n))
        .replace("{strategy_context}", strategy_context or "（战略师暂无特别指令，按默认风格创作）")
    )

    reference_parts: list[str] = []
    try:
        humor_reference = _read_prompt(HUMOR_REFERENCE_PATH).strip()
        if humor_reference:
            reference_parts.append(
                "来自用户幽默案例语料的参考（学习视角、节奏和人设，不要照抄）：\n"
                + humor_reference
            )
    except Exception:
        pass

    try:
        top_jokes = db.get_top_jokes(content_type=req.content_type.value, limit=3, min_score=7.5)
        if top_jokes:
            examples = "\n".join(f"- {j.text}" for j in top_jokes[:3])
            reference_parts.append(
                "以下是近期高质量范例，学习它们的手法和节奏，不要抄袭具体内容：\n"
                + examples
            )
    except Exception:
        pass

    writer_lessons_block = ""
    try:
        writer_lessons = db.get_knowledge(entry_type="writer_lesson", limit=5)
        if writer_lessons:
            writer_lessons_block = (
                "你在过往创作中积累的教训（必须遵守）：\n"
                + "\n".join(f"- {item['content']}" for item in writer_lessons)
            )
    except Exception:
        pass

    prompt = prompt.replace("{reference_block}", "\n\n".join(reference_parts).strip())
    prompt = prompt.replace("{writer_lessons}", writer_lessons_block)

    model = os.getenv("DOUBAO_WRITER_MODEL", "doubao-seed-2.0-lite-250315")
    text = _chat(_writer_client(), model, prompt, temperature=0.9, max_tokens=4000, role="writer")
    results = [item.strip() for item in text.split("===") if item.strip()]
    return results[:req.n] if len(results) > req.n else results


def score(text: str, content_type: ContentType) -> ScoreResult:
    """MiniMax 对一条内容进行 6 维评分，返回 ScoreResult。
    评分用轻量模型（MINIMAX_SCORE_MODEL），默认 MiniMax-Text-01，比推理模型快3-5倍。
    """
    route = judge_router.route_judge(text, content_type)
    prompt = (
        _read_prompt(SCORE_PROMPT_PATH)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{text}", text)
    )
    prompt += f"\n\nJudge 路由信息（必须遵守）：\n{route.prompt_block}"
    long_structure = _default_long_structure()
    if route.shape == "long":
        try:
            long_structure = _analyze_long_structure(text, content_type, route)
        except Exception:
            long_structure = _default_long_structure()
        if long_structure.get("structure_summary") or long_structure.get("structure_guidance"):
            prompt += (
                "\n\n长内容结构预分析（必须参考）：\n"
                f"- 结构摘要：{long_structure.get('structure_summary') or '暂无'}\n"
                f"- 最强点：{long_structure.get('best_moment') or '暂无'}\n"
                f"- 最弱点：{long_structure.get('weakest_moment') or '暂无'}\n"
                f"- 施工建议：{long_structure.get('structure_guidance') or '暂无'}"
            )
    try:
        judge_directive = db.get_current_judge_directive()
    except Exception:
        judge_directive = ""
    if judge_directive:
        prompt += f"\n\n当前战略师追加评分原则：\n{judge_directive}"

    judge_lessons_block = ""
    try:
        judge_lessons = db.get_knowledge(entry_type="judge_lesson", limit=5)
        if judge_lessons:
            judge_lessons_block = (
                "你在历史校准中积累的评分教训（必须遵守）：\n"
                + "\n".join(f"- {lesson['content']}" for lesson in judge_lessons)
            )
    except Exception:
        pass
    prompt = prompt.replace("{judge_lessons_block}", judge_lessons_block)

    model = os.getenv("DOUBAO_JUDGE_MODEL", "doubao-seed-2.0-lite-250315")
    last_error = None
    for _ in range(2):
        try:
            raw = _chat(_judge_client(), model, prompt, temperature=0.3, max_tokens=512, role="judge")
            result = _parse_score_json(raw)
            if _looks_like_collapsed_score(result):
                strict_prompt = (
                    prompt
                    + "\n\n重要补充：这次请严格重新评分，避免模板化默认分。"
                    + "\n- 分数允许使用 0.5 粒度，不要全部给整数。"
                    + "\n- 至少两个维度必须体现这条文本的具体差异。"
                    + "\n- reasoning 必须点出文本里的具体梗点或词句，不能只写泛泛而谈的“结构清晰、共鸣强”。"
                    + "\n- 不要复用常见的 8/7/9/8/6/10 组合。"
                )
                try:
                    rescue_model = os.getenv("DOUBAO_STRATEGIST_MODEL", model)
                    strict_raw = _chat(
                        _strategist_client(),
                        rescue_model,
                        strict_prompt,
                        temperature=0.3,
                        max_tokens=512,
                        role="judge",
                    )
                    strict_result = _parse_score_json(strict_raw)
                    if not _looks_like_collapsed_score(strict_result):
                        return _hydrate_display_fields(
                            strict_result,
                            text,
                            content_type,
                            route,
                            judge_directive,
                            judge_lessons_block,
                            long_structure=long_structure,
                        )
                except Exception as exc:
                    last_error = exc
            return _hydrate_display_fields(
                result,
                text,
                content_type,
                route,
                judge_directive,
                judge_lessons_block,
                long_structure=long_structure,
            )
        except Exception as exc:
            last_error = exc

    fallback = _default_score(f"评分解析失败，已回退默认分。错误：{last_error}")
    return _hydrate_display_fields(
        fallback,
        text,
        content_type,
        route,
        judge_directive,
        judge_lessons_block,
        long_structure=long_structure,
    )


def generate_and_score_all(req: GenerationRequest) -> list[JokeRecord]:
    """生成 N 条 → 并行评分 → 全部返回（用于训练批次，不丢弃低分内容）。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = generate(req)
    if not candidates:
        raise RuntimeError("模型未返回可用内容")

    scores: dict[int, ScoreResult] = {}
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        future_to_idx = {
            executor.submit(score, text, req.content_type): i
            for i, text in enumerate(candidates)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                scores[idx] = future.result()
            except Exception as exc:
                scores[idx] = _default_score(f"并行评分失败：{exc}")

    return [
        JokeRecord(
            id=None,
            content_type=req.content_type,
            text=candidates[i],
            persona_id=req.persona.id if req.persona else None,
            score=scores[i],
            human_rating=None,
            human_reaction=None,
        )
        for i in range(len(candidates))
    ]


def generate_and_rank_all(req: GenerationRequest):
    """生成 N 条 → group comparison 排序 → 仅对 Top2+Bottom1 做诊断评分。"""
    import ranker

    candidates = generate(req)
    if not candidates:
        raise RuntimeError("模型未返回可用内容")

    return ranker.rank_and_score_batch(
        candidates,
        req.content_type,
        persona_id=req.persona.id if req.persona else None,
    )


def generate_and_pick_best(req: GenerationRequest) -> JokeRecord:
    """生成 N 条 → 并行评分 → 返回展示轨分数最高的那条。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates = generate(req)
    if not candidates:
        raise RuntimeError("模型未返回可用内容")

    # 并行对所有候选评分
    scores: dict[int, ScoreResult] = {}
    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        future_to_idx = {
            executor.submit(score, text, req.content_type): i
            for i, text in enumerate(candidates)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                scores[idx] = future.result()
            except Exception as exc:
                scores[idx] = _default_score(f"并行评分失败：{exc}")

    best_idx = max(
        scores,
        key=lambda i: (
            display_track_value(scores[i]) if display_track_value(scores[i]) is not None else scores[i].weighted_total
        ),
    )
    best_text = candidates[best_idx]
    best_score = scores[best_idx]

    return JokeRecord(
        id=None,
        content_type=req.content_type,
        text=best_text,
        persona_id=req.persona.id if req.persona else None,
        score=best_score,
        human_rating=None,
        human_reaction=None,
    )
