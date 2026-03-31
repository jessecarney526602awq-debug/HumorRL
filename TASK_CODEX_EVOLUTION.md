# Codex 任务单 — Prompt 遗传算法（策略进化）

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **先读 CLAUDE.md + contract.py + db.py + prompts/generate/standup.txt 再动手。**

---

## 背景理解

现有 Prompt 结构（以 standup.txt 为例）分三段：

```
[角色段] 你是一位专业的中文脱口秀段子写手……

{persona_block}

## 创作要求
- 结构：setup（铺垫）+ punchline（包袱）……   ← 基因 1
- 语气：口语化，像真人在台上说话……           ← 基因 2
- 包袱：出人意料，但回头想想又在情理之中      ← 基因 3
- 字数：每条 100-200 字                        ← 基因 4
- 风格参考：生活观察类……                      ← 基因 5

## 本次任务
主题：{topic}
请生成 {n} 条……===……
```

**遗传算法的"基因"= `## 创作要求` 下的每条 `- xxx` bullet。**
角色段和任务段固定不变（含占位符），只演化创作要求里的 bullet 组合。

---

## 你负责的文件

| 文件 | 操作 |
|------|------|
| `evolution.py` | 新建 — 遗传算法核心 |
| `db.py` | 追加 — prompt_variants 表 + 相关 CRUD |
| `app.py` | 追加 — 在「📡 监控」页面末尾加「🧬 Prompt 进化」折叠面板 |
| `scheduler.py` | 追加 — 每天凌晨2点运行一次进化任务 |
| `requirements.txt` | 无需改动（纯 Python 实现） |

---

## 任务一：修改 `db.py`

### 1a. 在 `SCHEMA` 末尾追加建表

```sql
CREATE TABLE IF NOT EXISTS prompt_variants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT    NOT NULL,
    generation      INTEGER NOT NULL DEFAULT 0,  -- 第几代，0=原始
    prompt_text     TEXT    NOT NULL,             -- 完整 prompt 文本
    parent_ids      TEXT    NOT NULL DEFAULT '',  -- 父代 id，逗号分隔，原始为空
    uses            INTEGER NOT NULL DEFAULT 0,   -- 被用于生成的次数
    total_score     REAL    NOT NULL DEFAULT 0.0, -- 累计评分
    avg_score       REAL    NOT NULL DEFAULT 0.0, -- 平均评分（total/uses）
    is_active       INTEGER NOT NULL DEFAULT 1,   -- 1=当前在用，0=已淘汰
    created_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_variants_type ON prompt_variants(content_type);
CREATE INDEX IF NOT EXISTS idx_variants_gen  ON prompt_variants(generation);
```

同时在 `jokes` 表的 `SCHEMA` 中追加一列（ALTER 不可用于已有 DB，用迁移脚本处理，见下方）：

**不要修改** `SCHEMA` 中 jokes 表的 CREATE 语句，改为在 `init_db()` 函数里加迁移：

```python
def init_db(db_path: str = DB_PATH) -> None:
    with _connect(db_path) as conn:
        conn.executescript(SCHEMA)
        # 迁移：为旧数据库补 prompt_variant_id 列（幂等）
        cols = [row[1] for row in conn.execute("PRAGMA table_info(jokes)").fetchall()]
        if "prompt_variant_id" not in cols:
            conn.execute("ALTER TABLE jokes ADD COLUMN prompt_variant_id INTEGER REFERENCES prompt_variants(id)")
        # 写入预设 persona（现有逻辑不变）
        row = conn.execute("SELECT COUNT(*) FROM personas").fetchone()
        if row[0] == 0:
            for p in PRESET_PERSONAS:
                conn.execute(...)  # 保留现有代码
```

### 1b. 在文件末尾追加函数

```python
def save_prompt_variant(
    content_type: str,          # ContentType.value
    prompt_text: str,
    generation: int,
    parent_ids: list[int],      # 父代 id 列表，原始为 []
    db_path: str = DB_PATH,
) -> int:
    """存入 prompt_variants，返回新 id。"""
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO prompt_variants "
            "(content_type, generation, prompt_text, parent_ids, uses, total_score, avg_score, is_active, created_at) "
            "VALUES (?, ?, ?, ?, 0, 0.0, 0.0, 1, ?)",
            (content_type, generation, prompt_text,
             ",".join(str(i) for i in parent_ids), _now()),
        )
        return cur.lastrowid


def get_active_variants(
    content_type: str,
    db_path: str = DB_PATH,
) -> list[dict]:
    """
    返回该类型所有 is_active=1 的变体，按 avg_score 降序。
    每项格式：{"id": int, "prompt_text": str, "generation": int,
               "uses": int, "avg_score": float}
    """
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, prompt_text, generation, uses, avg_score "
            "FROM prompt_variants WHERE content_type=? AND is_active=1 "
            "ORDER BY avg_score DESC",
            (content_type,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_variant_score(
    variant_id: int,
    score: float,
    db_path: str = DB_PATH,
) -> None:
    """在 jokes 生成后调用，更新变体的累计分和平均分。"""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE prompt_variants SET "
            "uses = uses + 1, "
            "total_score = total_score + ?, "
            "avg_score = (total_score + ?) / (uses + 1) "
            "WHERE id = ?",
            (score, score, variant_id),
        )


def seed_prompt_variants(db_path: str = DB_PATH) -> None:
    """
    将现有 5 个 .txt 文件作为第 0 代变体写入 DB（幂等：若该类型已有变体则跳过）。
    在 init_db() 末尾调用。
    """
    from pathlib import Path
    from contract import PROMPT_PATHS, ContentType
    project_root = Path(__file__).resolve().parent
    with _connect(db_path) as conn:
        for ct, path in PROMPT_PATHS.items():
            existing = conn.execute(
                "SELECT COUNT(*) FROM prompt_variants WHERE content_type=?",
                (ct.value,),
            ).fetchone()[0]
            if existing == 0:
                text = (project_root / path).read_text(encoding="utf-8")
                conn.execute(
                    "INSERT INTO prompt_variants "
                    "(content_type, generation, prompt_text, parent_ids, uses, total_score, avg_score, is_active, created_at) "
                    "VALUES (?, 0, ?, '', 0, 0.0, 0.0, 1, ?)",
                    (ct.value, text, _now()),
                )
```

同时在 `init_db()` 末尾调用 `seed_prompt_variants(db_path)`。

---

## 任务二：新建 `evolution.py`

```python
"""
HumorRL — Prompt 遗传算法
基因 = 创作要求里的每条 bullet point。
每代：选择 → 交叉 → 变异 → 评估适应度 → 淘汰弱者
"""

import random
import re
from typing import Optional
import db
from contract import ContentType, CONTENT_TYPE_LABELS, PROMPT_PATHS
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent

# ── Prompt 解析与重建 ─────────────────────────────────────────

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
    lines = prompt_text.split("\n")
    header_lines, gene_lines, footer_lines = [], [], []
    state = "header"  # header → genes → footer

    for line in lines:
        if state == "header":
            header_lines.append(line)
            if line.strip() == "## 创作要求":
                state = "genes"
        elif state == "genes":
            if line.startswith("- "):
                gene_lines.append(line[2:])  # 去掉 '- ' 前缀
            elif line.startswith("## "):
                state = "footer"
                footer_lines.append(line)
            else:
                header_lines.append(line)  # 创作要求前的空行归入 header
        elif state == "footer":
            footer_lines.append(line)

    return "\n".join(header_lines), gene_lines, "\n".join(footer_lines)


def _rebuild_prompt(header: str, genes: list[str], footer: str) -> str:
    """将三部分重新拼成完整 prompt。"""
    gene_block = "\n".join(f"- {g}" for g in genes)
    return f"{header}\n{gene_block}\n{footer}"


# ── 遗传操作 ────────────────────────────────────────────────

def crossover(parent_a: str, parent_b: str, seed: Optional[int] = None) -> tuple[str, str]:
    """
    单点交叉：随机选一个切割点，交换两个父代的后半段基因。
    返回两个子代的完整 prompt 文本。

    如果两个父代基因数量不同，以较短的为准确定切割点范围。
    最少保留 1 条基因，最多保留 len-1 条基因（避免子代与父代完全相同）。

    示例：
      parent_a genes: [A1, A2, A3, A4]
      parent_b genes: [B1, B2, B3, B4]
      切割点=2 →
      child_1: [A1, A2, B3, B4]
      child_2: [B1, B2, A3, A4]
    """
    rng = random.Random(seed)
    ha, genes_a, fa = _parse_genes(parent_a)
    hb, genes_b, fb = _parse_genes(parent_b)

    min_len = min(len(genes_a), len(genes_b))
    if min_len < 2:
        # 基因太少，直接返回原文（无法交叉）
        return parent_a, parent_b

    cut = rng.randint(1, min_len - 1)
    child_genes_1 = genes_a[:cut] + genes_b[cut:]
    child_genes_2 = genes_b[:cut] + genes_a[cut:]

    return _rebuild_prompt(ha, child_genes_1, fa), _rebuild_prompt(hb, child_genes_2, fb)


def mutate(prompt_text: str, mutation_rate: float = 0.2, seed: Optional[int] = None) -> str:
    """
    随机变异：对每条基因以 mutation_rate 的概率执行以下操作之一：
    - 删除（若基因数 > 3，避免基因池耗尽）
    - 替换为同类型的备用基因（从 MUTATION_GENE_POOL 中随机选）

    不做「添加新基因」操作（避免 prompt 越来越长，偏离原始风格）。

    返回变异后的完整 prompt 文本。
    """
    rng = random.Random(seed)
    header, genes, footer = _parse_genes(prompt_text)
    new_genes = []

    for gene in genes:
        if rng.random() < mutation_rate:
            action = rng.choice(["delete", "replace"])
            if action == "delete" and len(genes) > 3:
                continue  # 删除：跳过这条基因
            else:
                # 替换：从备用基因池随机选一条
                replacement = rng.choice(MUTATION_GENE_POOL)
                new_genes.append(replacement)
        else:
            new_genes.append(gene)

    if not new_genes:
        new_genes = genes  # 防止基因被全删光

    return _rebuild_prompt(header, new_genes, footer)


# 备用基因池：不同维度的替换基因，手工设计，覆盖各种创作策略
MUTATION_GENE_POOL = [
    # 结构类
    "结构：三段式（背景→冲突→反转），包袱在最后一句",
    "结构：先给结论，再补充让人忍俊不禁的原因",
    "结构：一问一答，答案出人意料",
    # 语气类
    "语气：冷静叙述，不加感叹，让读者自己发现好笑的地方",
    "语气：带点无奈和自我调侃，像在和老朋友吐槽",
    "语气：观察者视角，像在记录荒诞新闻",
    # 技法类
    "包袱手法：利用词语的双关或多义制造误解再解开",
    "包袱手法：把严肃的事用轻描淡写的方式说出来",
    "包袱手法：把微不足道的事用极其郑重的语气表达",
    "包袱手法：先建立一个读者以为懂的逻辑，最后一句打破它",
    # 内容类
    "内容：从当代年轻人的真实处境出发，越具体越好",
    "内容：聚焦一个具体细节或瞬间，而不是泛泛的生活感慨",
    "内容：利用反差——期望 vs 现实，想象 vs 真相",
    # 约束类
    "约束：不用感叹号，不用'哈哈'，让内容自己说话",
    "约束：避免说教，只呈现荒诞，不下结论",
    "约束：第一句必须制造悬念或疑问，让读者想看下去",
]


# ── 适应度评估 ───────────────────────────────────────────────

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

    实现步骤：
    1. 临时替换 humor_engine.generate() 使用的 prompt（通过直接传 prompt_text）
    2. 调用 humor_engine.score() 对每条评分
    3. 调用 db.update_variant_score(variant_id, score) 更新 DB
    4. 返回平均分

    注意：直接调用 humor_engine._writer_client() 和 humor_engine._chat()
    而不是 generate()，因为需要注入自定义 prompt 而不是读文件。
    """
    import os
    import humor_engine
    from contract import GenerationRequest

    scores = []
    for _ in range(eval_n):
        try:
            # 直接用自定义 prompt 生成
            filled = (
                prompt_text
                .replace("{persona_block}", "")
                .replace("{topic}", "（随机选择一个日常生活话题）")
                .replace("{n}", "1")
            )
            client = humor_engine._writer_client()
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            text = humor_engine._chat(client, model, filled, temperature=0.9, max_tokens=1500)
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


# ── 主进化循环 ───────────────────────────────────────────────

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

    算法流程：
    1. 从 DB 取当前 is_active=1 的变体（已有适应度数据）
    2. 选择：取 avg_score 最高的 elite_n 个为精英父代
       - 若变体总数 < population_size，补充随机变异版本填满种群
       - 若 DB 中只有 1 个变体（初始状态），先对其做 population_size-1 次变异，生成初始种群
    3. 交叉：对精英父代两两交叉，生成子代（最多 population_size-elite_n 个）
    4. 变异：对每个子代以 mutation_rate 概率变异
    5. 评估：调用 evaluate_variant() 为每个新子代打分（精英父代已有分数，跳过）
    6. 将新子代存入 DB（save_prompt_variant，generation=当前最大代数+1）
    7. 淘汰：将总变体数控制在 population_size 以内
       - 保留所有精英 + 分数最高的新子代
       - 被淘汰的变体设 is_active=0（软删除）
    8. 返回进化报告：
       {
           "content_type": str,
           "generations_run": int,
           "best_variant_id": int,
           "best_score": float,
           "improvement": float,    # best_score - 进化前最高分
           "population": [{"id": int, "generation": int, "avg_score": float}]
       }

    边界情况：
    - 变体数量不足 2 个时（无法交叉），只做变异
    - evaluate_variant 返回 0.0 时（全部生成失败），该子代不参与选择
    """
    ...
```

---

## 任务三：修改 `scheduler.py`

在文件末尾的 `main()` 函数中，追加一个每天凌晨2点的进化任务：

```python
def job_evolution():
    """每天凌晨2点运行 Prompt 遗传算法（逐类型轮换，每次只进化一种类型节省成本）。"""
    from evolution import run_evolution
    from contract import ContentType
    import datetime

    logger.info("=== Prompt 进化任务开始 ===")

    if not _check_daily_budget():
        return

    # 按星期几轮换类型（周一=standup，周二=cold_joke，……）
    weekday = datetime.datetime.now().weekday()  # 0=周一
    types = list(ContentType)
    content_type = types[weekday % len(types)]
    logger.info(f"本次进化类型：{content_type.value}")

    try:
        report = run_evolution(
            content_type=content_type,
            population_size=6,
            generations=2,     # 每次2代，控制成本
            eval_n=2,          # 每个变体评2条，控制成本
        )
        logger.info(
            f"进化完成 | 最佳变体 id={report['best_variant_id']} "
            f"分数={report['best_score']:.2f} "
            f"提升={report['improvement']:+.2f}"
        )
    except Exception as exc:
        logger.error(f"Prompt 进化失败：{exc}", exc_info=True)

    logger.info("=== Prompt 进化任务结束 ===")


# 在 main() 的 scheduler.add_job 区域追加：
# scheduler.add_job(job_evolution, "cron", hour=2, minute=0)
```

---

## 任务四：修改 `app.py`

在 `_page_monitor()` 函数末尾（UCB1 面板之后）追加进化状态面板：

```python
    # ── Prompt 进化状态
    st.markdown("---")
    with st.expander("🧬 Prompt 进化状态", expanded=False):
        from evolution import run_evolution, _parse_genes
        from db import get_active_variants

        evo_type_opts = list(ContentType)
        evo_ct = st.selectbox(
            "查看类型",
            options=evo_type_opts,
            format_func=lambda v: f"{CONTENT_ICONS[v]} {CONTENT_TYPE_LABELS[v]}",
            key="evo_type_select",
        )

        variants = get_active_variants(evo_ct.value)

        if not variants:
            st.info("该类型还没有 Prompt 变体，点击「立即进化」生成初始种群。")
        else:
            for v in variants:
                score_color = _score_color(v["avg_score"])
                _, genes, _ = _parse_genes(v["prompt_text"])
                st.markdown(f"""
                <div class="joke-card" style="margin-bottom:8px">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <div>
                      <span style="font-size:13px;font-weight:600;color:var(--text)">
                        变体 #{v['id']} &nbsp; 第 {v['generation']} 代
                      </span>
                    </div>
                    <div style="text-align:right">
                      <span style="font-size:18px;font-weight:700;color:{score_color}">{v['avg_score']:.2f}</span>
                      <span style="font-size:11px;color:var(--muted)"> / 使用{v['uses']}次</span>
                    </div>
                  </div>
                  <div style="font-size:12px;color:var(--muted);line-height:1.8">
                    {'<br>'.join(f'• {g}' for g in genes)}
                  </div>
                </div>""", unsafe_allow_html=True)

        st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
        col_evo1, col_evo2 = st.columns([1, 2])
        with col_evo1:
            if st.button("⚡ 立即进化一轮", key="btn_evolve", use_container_width=True):
                with st.spinner(f"正在进化 {CONTENT_TYPE_LABELS[evo_ct]} 的 Prompt……"):
                    try:
                        report = run_evolution(
                            content_type=evo_ct,
                            population_size=4,
                            generations=1,
                            eval_n=2,
                        )
                        st.success(
                            f"进化完成！最佳变体 #{report['best_variant_id']}，"
                            f"得分 {report['best_score']:.2f}，"
                            f"较进化前 {report['improvement']:+.2f}"
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"进化失败：{exc}")
        with col_evo2:
            st.caption("每次进化会生成新变体并评分，保留最优 4 个，自动淘汰弱者。\n每日凌晨2点自动运行。")
```

---

## 还需要：让进化后的最优 Prompt 真正用于生成

修改 `humor_engine.generate()` 函数，在读取 prompt 文件之前，先查询 DB 是否有该类型的 active 高分变体：

```python
def generate(req: GenerationRequest) -> list[str]:
    """DeepSeek 生成 req.n 条内容。优先使用进化后的最优 Prompt 变体。"""
    # 尝试从 DB 取最优变体
    try:
        variants = db.get_active_variants(req.content_type.value)
        if variants and variants[0]["uses"] >= 5:
            # 只有被用过5次以上（有统计意义）才启用进化版本
            prompt = variants[0]["prompt_text"]
        else:
            prompt = _read_prompt(PROMPT_PATHS[req.content_type])
    except Exception:
        prompt = _read_prompt(PROMPT_PATHS[req.content_type])

    # 后续逻辑不变
    persona_block = ""
    if req.persona is not None:
        persona_block = f"你的角色设定：\n{req.persona.style_prompt}"
    prompt = (
        prompt.replace("{persona_block}", persona_block)
        .replace("{topic}", req.topic or "（随机选择一个日常生活话题）")
        .replace("{n}", str(req.n))
    )
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    text = _chat(_writer_client(), model, prompt, temperature=0.9, max_tokens=4000)
    results = [item.strip() for item in text.split("===") if item.strip()]
    return results[:req.n] if len(results) > req.n else results
```

---

## 完成后

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add evolution.py db.py app.py scheduler.py humor_engine.py
git commit -m "feat(evolution): Prompt 遗传算法 + 自动进化调度 + 监控页进化面板"
git push origin main
```

服务器更新：
```bash
cd ~/HumorRL && git pull && docker compose up -d --build
```
