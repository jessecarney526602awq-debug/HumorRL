"""
HumorRL — 改写引擎
对评分 4-7 分的内容进行迭代改写，最多3轮，parent_id 追踪链路。
"""

import os

from contract import CONTENT_TYPE_LABELS, JokeRecord
import humor_engine
import db


REWRITE_PROMPT_PATH = "prompts/rewrite/rewrite.txt"


def _score_value(value: float | None) -> str:
    return "N/A" if value is None else str(value)


def rewrite_once(original: JokeRecord, db_path: str = db.DB_PATH) -> JokeRecord:
    """
    单轮改写。
    - 读取 REWRITE_PROMPT_PATH，替换以下占位符后调用 DeepSeek：
        {original_text}          = original.text
        {content_type_label}     = CONTENT_TYPE_LABELS[original.content_type]
        {score_structure}        = original.score.structure  (或 "N/A")
        {score_surprise}         = original.score.surprise
        {score_relatability}     = original.score.relatability
        {score_language}         = original.score.language
        {score_creativity}       = original.score.creativity
        {score_safety}           = original.score.safety
        {reasoning}              = original.score.reasoning
    - 调用 DeepSeek：temperature=0.85，max_tokens=2000
    - 对改写结果调用 humor_engine.score() 打分
    - 返回新 JokeRecord：
        id=None, parent_id=original.id, rewrite_round=original.rewrite_round+1
        content_type/persona_id 继承原始，human_rating/human_reaction=None
    """
    score = original.score
    prompt = humor_engine._read_prompt(REWRITE_PROMPT_PATH)
    prompt = (
        prompt.replace("{original_text}", original.text)
        .replace("{content_type_label}", CONTENT_TYPE_LABELS[original.content_type])
        .replace("{score_structure}", _score_value(score.structure if score else None))
        .replace("{score_surprise}", _score_value(score.surprise if score else None))
        .replace("{score_relatability}", _score_value(score.relatability if score else None))
        .replace("{score_language}", _score_value(score.language if score else None))
        .replace("{score_creativity}", _score_value(score.creativity if score else None))
        .replace("{score_safety}", _score_value(score.safety if score else None))
        .replace("{reasoning}", score.reasoning if score else "N/A")
    )

    client = humor_engine._writer_client()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    new_text = humor_engine._chat(client, model, prompt, temperature=0.85, max_tokens=2000)
    new_score = humor_engine.score(new_text, original.content_type)

    return JokeRecord(
        id=None,
        content_type=original.content_type,
        text=new_text,
        persona_id=original.persona_id,
        score=new_score,
        human_rating=None,
        human_reaction=None,
        parent_id=original.id,
        rewrite_round=original.rewrite_round + 1,
    )


def rewrite_until_good(
    original: JokeRecord,
    max_rounds: int = 3,
    target_score: float = 7.0,
    db_path: str = db.DB_PATH,
) -> list[JokeRecord]:
    """
    迭代改写，最多 max_rounds 轮。
    终止条件（满足其一）：
      1. display_score >= target_score（若暂无展示分则回退 weighted_total）
      2. 已达 max_rounds 轮
      3. 改写后分数比上一版本下降超过 0.5（越改越烂，提前停止）

    - original.id 必须不为 None（已存 DB），否则 raise ValueError
    - 每轮改写后立即 db.save_joke() 存入 DB 获得真实 id，再传入下一轮
    - 返回所有改写版本列表（含已存 DB 的 id），不含原始版本
    """
    if original.id is None:
        raise ValueError("original.id 不能为空，必须先存入 DB")

    results: list[JokeRecord] = []
    current = original

    for _ in range(max_rounds):
        rewritten = rewrite_once(current, db_path=db_path)
        rewritten.id = db.save_joke(rewritten, db_path=db_path)
        results.append(rewritten)

        previous_total = humor_engine.display_track_value(current.score)
        current_total = humor_engine.display_track_value(rewritten.score)

        if current_total is not None and current_total >= target_score:
            break
        if (
            previous_total is not None
            and current_total is not None
            and current_total < previous_total - 0.5
        ):
            break

        current = rewritten

    return results
