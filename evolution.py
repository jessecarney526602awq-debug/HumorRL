"""
HumorRL — Prompt 遗传算法
基因 = 创作要求里的每条 bullet point。
每代：选择 → 交叉 → 变异 → 评估适应度 → 淘汰弱者
"""

import os
import random
import re
from pathlib import Path
from typing import Optional

import db
from contract import CONTENT_TYPE_LABELS, ContentType, PROMPT_PATHS


PROJECT_ROOT = Path(__file__).resolve().parent


def _parse_genes(prompt_text: str) -> tuple[str, list[str], str]:
    """
    将 prompt 分解为三部分：
    返回 (header, genes, footer)
    - header: 从开头到 '## 创作要求\n' 之前（含该标题行）
    - genes:  创作要求下的每条 '- xxx' bullet，list[str]（不含 '- ' 前缀）
    - footer: 从 '\n## 本次任务' 开始到结尾

    解析规则：
    1. 找到 '## 创作要求' 行的位置
    2. 之后每行以 '- ' 开头的为一条基因（去掉 '- ' 前缀后存储）
    3. 遇到空行后再遇到 '##' 开头的行，即为 footer 起始
    """
    match = re.search(r"(?s)^(.*?## 创作要求\s*)(.*?)(\n## 本次任务.*)$", prompt_text)
    if not match:
        return prompt_text, [], ""

    header = match.group(1).rstrip()
    middle = match.group(2)
    footer = match.group(3).lstrip("\n")
    genes = [line[2:] for line in middle.splitlines() if line.startswith("- ")]
    return header, genes, footer


def _rebuild_prompt(header: str, genes: list[str], footer: str) -> str:
    """将三部分重新拼成完整 prompt。"""
    gene_block = "\n".join(f"- {g}" for g in genes)
    if footer:
        return f"{header}\n\n{gene_block}\n\n{footer}"
    return f"{header}\n\n{gene_block}"


def crossover(parent_a: str, parent_b: str, seed: Optional[int] = None) -> tuple[str, str]:
    """
    单点交叉：随机选一个切割点，交换两个父代的后半段基因。
    返回两个子代的完整 prompt 文本。

    如果两个父代基因数量不同，以较短的为准确定切割点范围。
    最少保留 1 条基因，最多保留 len-1 条基因（避免子代与父代完全相同）。
    """
    rng = random.Random(seed)
    header_a, genes_a, footer_a = _parse_genes(parent_a)
    header_b, genes_b, footer_b = _parse_genes(parent_b)

    min_len = min(len(genes_a), len(genes_b))
    if min_len < 2:
        return parent_a, parent_b

    cut = rng.randint(1, min_len - 1)
    child_genes_1 = genes_a[:cut] + genes_b[cut:]
    child_genes_2 = genes_b[:cut] + genes_a[cut:]

    return (
        _rebuild_prompt(header_a, child_genes_1, footer_a),
        _rebuild_prompt(header_b, child_genes_2, footer_b),
    )


MUTATION_GENE_POOL = [
    "结构：三段式（背景→冲突→反转），包袱在最后一句",
    "结构：先给结论，再补充让人忍俊不禁的原因",
    "结构：一问一答，答案出人意料",
    "语气：冷静叙述，不加感叹，让读者自己发现好笑的地方",
    "语气：带点无奈和自我调侃，像在和老朋友吐槽",
    "语气：观察者视角，像在记录荒诞新闻",
    "包袱手法：利用词语的双关或多义制造误解再解开",
    "包袱手法：把严肃的事用轻描淡写的方式说出来",
    "包袱手法：把微不足道的事用极其郑重的语气表达",
    "包袱手法：先建立一个读者以为懂的逻辑，最后一句打破它",
    "内容：从当代年轻人的真实处境出发，越具体越好",
    "内容：聚焦一个具体细节或瞬间，而不是泛泛的生活感慨",
    "内容：利用反差——期望 vs 现实，想象 vs 真相",
    "约束：不用感叹号，不用'哈哈'，让内容自己说话",
    "约束：避免说教，只呈现荒诞，不下结论",
    "约束：第一句必须制造悬念或疑问，让读者想看下去",
]


def mutate(prompt_text: str, mutation_rate: float = 0.2, seed: Optional[int] = None) -> str:
    """
    随机变异：对每条基因以 mutation_rate 的概率执行以下操作之一：
    - 删除（若基因数 > 3，避免基因池耗尽）
    - 替换为同类型的备用基因（从 MUTATION_GENE_POOL 中随机选）

    不做「添加新基因」操作（避免 prompt 越来越长，偏离原始风格）。
    """
    rng = random.Random(seed)
    header, genes, footer = _parse_genes(prompt_text)
    new_genes = []

    for gene in genes:
        if rng.random() < mutation_rate:
            action = rng.choice(["delete", "replace"])
            if action == "delete" and len(genes) > 3:
                continue
            new_genes.append(rng.choice(MUTATION_GENE_POOL))
        else:
            new_genes.append(gene)

    if not new_genes:
        new_genes = genes

    return _rebuild_prompt(header, new_genes, footer)


def evaluate_variant(
    variant_id: int,
    content_type: ContentType,
    prompt_text: str,
    eval_n: int = 3,
    db_path: str = db.DB_PATH,
) -> float:
    """
    用该 prompt 变体生成 eval_n 条内容，取平均 weighted_total 作为适应度。
    同时将每次评分记录到 prompt_variants 表（update_variant_score）。
    返回平均适应度分数。
    """
    import humor_engine

    scores = []
    for _ in range(eval_n):
        try:
            filled = (
                prompt_text
                .replace("{persona_block}", "")
                .replace("{topic}", "（随机选择一个日常生活话题）")
                .replace("{n}", "1")
            )
            client = humor_engine._writer_client()
            model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.7")
            text = humor_engine._chat(client, model, filled, temperature=0.9, max_tokens=1500, role="writer")
            text = text.split("===")[0].strip()
            if not text:
                continue
            score_result = humor_engine.score(text, content_type)
            fitness = score_result.weighted_total
            db.update_variant_score(variant_id, fitness, db_path=db_path)
            scores.append(fitness)
        except Exception:
            continue

    return sum(scores) / len(scores) if scores else 0.0


def _current_generation(content_type: ContentType, db_path: str) -> int:
    with db._connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(generation), 0) FROM prompt_variants WHERE content_type=?",
            (content_type.value,),
        ).fetchone()
    return int(row[0] or 0)


def _deactivate_non_survivors(content_type: ContentType, survivor_ids: list[int], db_path: str) -> None:
    with db._connect(db_path) as conn:
        if survivor_ids:
            placeholders = ",".join("?" for _ in survivor_ids)
            conn.execute(
                f"UPDATE prompt_variants SET is_active=0 WHERE content_type=? AND id NOT IN ({placeholders})",
                [content_type.value, *survivor_ids],
            )
            conn.execute(
                f"UPDATE prompt_variants SET is_active=1 WHERE content_type=? AND id IN ({placeholders})",
                [content_type.value, *survivor_ids],
            )
        else:
            conn.execute(
                "UPDATE prompt_variants SET is_active=0 WHERE content_type=?",
                (content_type.value,),
            )


def run_evolution(
    content_type: ContentType,
    population_size: int = 6,
    generations: int = 3,
    elite_n: int = 2,
    mutation_rate: float = 0.2,
    eval_n: int = 2,
    db_path: str = db.DB_PATH,
) -> dict:
    """
    对指定 content_type 运行一轮完整进化。
    """
    db.seed_prompt_variants(db_path)
    active_variants = db.get_active_variants(content_type.value, db_path=db_path)
    if not active_variants:
        raise ValueError(f"{CONTENT_TYPE_LABELS[content_type]} 没有可用 Prompt 变体")

    baseline_best = max((float(item["avg_score"]) for item in active_variants), default=0.0)

    for generation_index in range(generations):
        active_variants = db.get_active_variants(content_type.value, db_path=db_path)
        if not active_variants:
            break

        elites = active_variants[: max(1, min(elite_n, len(active_variants)))]
        next_generation = _current_generation(content_type, db_path) + 1
        children: list[dict] = []
        target_children = max(population_size - len(elites), 0)

        if len(active_variants) == 1:
            base = active_variants[0]
            for child_index in range(target_children):
                child_prompt = mutate(
                    base["prompt_text"],
                    mutation_rate=mutation_rate,
                    seed=generation_index * 100 + child_index,
                )
                variant_id = db.save_prompt_variant(
                    content_type=content_type.value,
                    prompt_text=child_prompt,
                    generation=next_generation,
                    parent_ids=[base["id"]],
                    db_path=db_path,
                )
                avg_score = evaluate_variant(variant_id, content_type, child_prompt, eval_n=eval_n, db_path=db_path)
                children.append(
                    {
                        "id": variant_id,
                        "prompt_text": child_prompt,
                        "generation": next_generation,
                        "uses": eval_n if avg_score > 0 else 0,
                        "avg_score": avg_score,
                    }
                )
        else:
            parent_pool = elites if len(elites) >= 2 else active_variants[:2]
            pair_index = 0
            while len(children) < target_children:
                if len(parent_pool) >= 2:
                    parent_a = parent_pool[pair_index % len(parent_pool)]
                    parent_b = parent_pool[(pair_index + 1) % len(parent_pool)]
                    pair_index += 1
                    child_texts = crossover(
                        parent_a["prompt_text"],
                        parent_b["prompt_text"],
                        seed=generation_index * 100 + pair_index,
                    )
                    parent_ids = [parent_a["id"], parent_b["id"]]
                else:
                    parent_a = active_variants[0]
                    child_texts = (
                        mutate(
                            parent_a["prompt_text"],
                            mutation_rate=mutation_rate,
                            seed=generation_index * 100 + pair_index,
                        ),
                    )
                    parent_ids = [parent_a["id"]]
                    pair_index += 1

                for child_text in child_texts:
                    if len(children) >= target_children:
                        break
                    candidate_text = child_text
                    if random.random() < mutation_rate:
                        candidate_text = mutate(candidate_text, mutation_rate=mutation_rate)
                    variant_id = db.save_prompt_variant(
                        content_type=content_type.value,
                        prompt_text=candidate_text,
                        generation=next_generation,
                        parent_ids=parent_ids,
                        db_path=db_path,
                    )
                    avg_score = evaluate_variant(
                        variant_id,
                        content_type,
                        candidate_text,
                        eval_n=eval_n,
                        db_path=db_path,
                    )
                    children.append(
                        {
                            "id": variant_id,
                            "prompt_text": candidate_text,
                            "generation": next_generation,
                            "uses": eval_n if avg_score > 0 else 0,
                            "avg_score": avg_score,
                        }
                    )

        viable_children = [child for child in children if child["avg_score"] > 0.0]
        viable_children.sort(key=lambda item: item["avg_score"], reverse=True)

        survivors = list(elites)
        survivors.extend(viable_children[: max(population_size - len(survivors), 0)])

        if len(survivors) < population_size:
            existing_ids = {item["id"] for item in survivors}
            remaining_old = [item for item in active_variants if item["id"] not in existing_ids]
            survivors.extend(remaining_old[: max(population_size - len(survivors), 0)])

        survivor_ids = [item["id"] for item in survivors[:population_size]]
        _deactivate_non_survivors(content_type, survivor_ids, db_path)

    final_population = db.get_active_variants(content_type.value, db_path=db_path)
    best_variant = final_population[0] if final_population else active_variants[0]
    best_score = float(best_variant["avg_score"])

    return {
        "content_type": content_type.value,
        "generations_run": generations,
        "best_variant_id": int(best_variant["id"]),
        "best_score": best_score,
        "improvement": best_score - baseline_best,
        "population": [
            {
                "id": int(item["id"]),
                "generation": int(item["generation"]),
                "avg_score": float(item["avg_score"]),
            }
            for item in final_population
        ],
    }
