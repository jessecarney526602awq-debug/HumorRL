"""
HumorRL — 生成与评分引擎

生成：MiniMax API（MiniMax-M2.7，temperature 0.9）
评分：MiniMax API（MiniMax-M2.7，temperature 0.3）
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

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


# ─────────────────────────────────────────
# 两个独立的 LLM 客户端
# ─────────────────────────────────────────

def _writer_client() -> OpenAI:
    """MiniMax — 负责生成笑话"""
    key = os.getenv("MINIMAX_API_KEY")
    if not key:
        raise RuntimeError("MINIMAX_API_KEY 未设置")
    return OpenAI(api_key=key, base_url="https://api.minimax.chat/v1")


def _judge_client() -> OpenAI:
    """MiniMax — 负责评分"""
    key = os.getenv("MINIMAX_API_KEY")
    if not key:
        raise RuntimeError("MINIMAX_API_KEY 未设置")
    return OpenAI(api_key=key, base_url="https://api.minimax.chat/v1")


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
    """MiniMax 生成 req.n 条内容，返回文本列表。"""
    prompt = _read_prompt(PROMPT_PATHS[req.content_type])
    persona_block = ""
    if req.persona is not None:
        persona_block = f"你的角色设定：\n{req.persona.style_prompt}"

    prompt = (
        prompt.replace("{persona_block}", persona_block)
        .replace("{topic}", req.topic or "（随机选择一个日常生活话题）")
        .replace("{n}", str(req.n))
    )

    model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
    text = _chat(_writer_client(), model, prompt, temperature=0.9, max_tokens=4000, role="writer")
    results = [item.strip() for item in text.split("===") if item.strip()]
    return results[:req.n] if len(results) > req.n else results


def score(text: str, content_type: ContentType) -> ScoreResult:
    """MiniMax 对一条内容进行 6 维评分，返回 ScoreResult。"""
    prompt = (
        _read_prompt(SCORE_PROMPT_PATH)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[content_type])
        .replace("{text}", text)
    )

    model = os.getenv("MINIMAX_MODEL", "MiniMax-Text-01")
    last_error = None
    for _ in range(2):
        try:
            raw = _chat(_judge_client(), model, prompt, temperature=0.3, max_tokens=512, role="judge")
            # 剥离 <think>...</think> 推理过程（MiniMax-M2.7 推理模型）
            import re as _re
            raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
            # 兼容 JSON 被包在 ```json ... ``` 里的情况
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
    """生成 N 条 → 全部评分 → 返回总分最高的那条。"""
    candidates = generate(req)
    if not candidates:
        raise RuntimeError("模型未返回可用内容")

    best_text = candidates[0]
    best_score = score(best_text, req.content_type)

    for candidate in candidates[1:]:
        s = score(candidate, req.content_type)
        if s.weighted_total > best_score.weighted_total:
            best_text = candidate
            best_score = s

    return JokeRecord(
        id=None,
        content_type=req.content_type,
        text=best_text,
        persona_id=req.persona.id if req.persona else None,
        score=best_score,
        human_rating=None,
        human_reaction=None,
    )
