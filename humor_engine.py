"""
HumorRL — 生成与评分引擎

生成：豆包 Doubao-Seed-2.0-lite（temperature 0.9）
评分：豆包 Doubao-Seed-2.0-lite（temperature 0.3）
战略：豆包 Doubao-Seed-2.0-pro（temperature 0.3，在 strategist.py 中调用）
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

import db
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

    model = os.getenv("DOUBAO_WRITER_MODEL", "doubao-seed-2.0-lite-250315")
    text = _chat(_writer_client(), model, prompt, temperature=0.9, max_tokens=4000, role="writer")
    results = [item.strip() for item in text.split("===") if item.strip()]
    return results[:req.n] if len(results) > req.n else results


def score(text: str, content_type: ContentType) -> ScoreResult:
    """MiniMax 对一条内容进行 6 维评分，返回 ScoreResult。
    评分用轻量模型（MINIMAX_SCORE_MODEL），默认 MiniMax-Text-01，比推理模型快3-5倍。
    """
    import re as _re
    prompt = (
        _read_prompt(SCORE_PROMPT_PATH)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{text}", text)
    )

    model = os.getenv("DOUBAO_JUDGE_MODEL", "doubao-seed-2.0-lite-250315")
    last_error = None
    for _ in range(2):
        try:
            raw = _chat(_judge_client(), model, prompt, temperature=0.3, max_tokens=512, role="judge")
            raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            return ScoreResult(
                structure=float(data["structure"]),
                surprise=float(data["surprise"]),
                relatability=float(data["relatability"]),
                language=float(data["language"]),
                creativity=float(data["creativity"]),
                safety=float(data["safety"]),
                reasoning=str(data["reasoning"]),
            )
        except Exception as exc:
            last_error = exc

    return _default_score(f"评分解析失败，已回退默认分。错误：{last_error}")


def generate_and_pick_best(req: GenerationRequest) -> JokeRecord:
    """生成 N 条 → 并行评分 → 返回总分最高的那条。"""
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

    best_idx = max(scores, key=lambda i: scores[i].weighted_total)
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
