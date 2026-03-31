# Codex 任务单 — 推理模型战略师（Strategist）

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **先读 CLAUDE.md + humor_engine.py + evolution.py + db.py**

---

## 架构总图

```
┌─────────────────────────────────────────────────────────────┐
│                     快循环（每小时）                          │
│                                                             │
│  MiniMax-Text-01      MiniMax-Text-01                       │
│  [生成器] ──────────▶ [评分器] ──────▶ DB                   │
│  快，创意输出          快，即时反馈                            │
└─────────────────────────────────────────────────────────────┘
                              │ 每天凌晨积累数据
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     慢循环（每天）                            │
│                                                             │
│  MiniMax-M2.7                                               │
│  [战略师 Strategist]                                         │
│  ① 复盘：分析高分 vs 低分的差异模式                            │
│  ② 学习：提取成功基因，归纳失败原因                            │
│  ③ 指导：输出具体的 Prompt 改进方向                           │
│  ④ 记录：将案例和洞察存入知识库                                │
│  ⑤ 更新：向 evolution.py 注入新基因                          │
└─────────────────────────────────────────────────────────────┘
```

## 三个模型的环境变量

```
MINIMAX_MODEL=MiniMax-Text-01          # 生成器（快）
MINIMAX_SCORE_MODEL=MiniMax-Text-01    # 评分器（快）
MINIMAX_STRATEGIST_MODEL=MiniMax-M2.7  # 战略师（深度推理）
```

---

## 你负责的文件

| 文件 | 操作 |
|------|------|
| `strategist.py` | 新建 — 战略师核心逻辑 |
| `db.py` | 追加 — knowledge_base 表 + CRUD |
| `prompts/strategist/review.txt` | 新建 — 战略师复盘 Prompt |
| `prompts/strategist/gene_gen.txt` | 新建 — 战略师生成新基因 Prompt |
| `evolution.py` | 修改 — `MUTATION_GENE_POOL` 改为从 DB 动态读取 |
| `scheduler.py` | 追加 — 每天凌晨3点运行战略师 |
| `app.py` | 追加 — 监控页新增「知识库」tab |
| `.env.example` | 追加 MINIMAX_STRATEGIST_MODEL |

---

## 任务一：修改 `db.py` — 知识库表

### 1a. SCHEMA 末尾追加

```sql
CREATE TABLE IF NOT EXISTS knowledge_base (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    content_type    TEXT,                  -- NULL 表示跨类型通用
    entry_type      TEXT    NOT NULL,      -- 'success_pattern'|'failure_pattern'|'gene'|'case'|'insight'
    content         TEXT    NOT NULL,      -- 具体内容（Markdown 文本）
    source_joke_ids TEXT    NOT NULL DEFAULT '',  -- 来源 joke id 列表，逗号分隔
    relevance_score REAL    NOT NULL DEFAULT 1.0, -- 相关性/质量评分，越高越优先使用
    used_count      INTEGER NOT NULL DEFAULT 0,   -- 被 evolution 使用次数
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kb_type     ON knowledge_base(entry_type);
CREATE INDEX IF NOT EXISTS idx_kb_ct       ON knowledge_base(content_type);
CREATE INDEX IF NOT EXISTS idx_kb_score    ON knowledge_base(relevance_score DESC);
```

### 1b. 追加函数

```python
def save_knowledge(
    entry_type: str,        # 'success_pattern'|'failure_pattern'|'gene'|'case'|'insight'
    content: str,
    content_type: Optional[str] = None,   # None = 通用
    source_joke_ids: list[int] = None,
    relevance_score: float = 1.0,
    db_path: str = DB_PATH,
) -> int:
    """存入知识库，返回新 id。"""
    ...


def get_knowledge(
    entry_type: Optional[str] = None,    # None = 全部类型
    content_type: Optional[str] = None,  # None = 全部内容类型
    limit: int = 20,
    db_path: str = DB_PATH,
) -> list[dict]:
    """
    按 relevance_score DESC 返回知识条目。
    每项格式：{"id": int, "entry_type": str, "content": str,
               "content_type": str|None, "relevance_score": float,
               "used_count": int, "created_at": str}
    """
    ...


def get_dynamic_gene_pool(
    content_type: Optional[str] = None,
    limit: int = 30,
    db_path: str = DB_PATH,
) -> list[str]:
    """
    从知识库取 entry_type='gene' 的条目，返回纯文本列表。
    供 evolution.py 的 MUTATION_GENE_POOL 动态替换。
    按 relevance_score DESC + used_count ASC（优先用未用过的）排序。
    """
    ...


def increment_knowledge_used(knowledge_id: int, db_path: str = DB_PATH) -> None:
    """每次被 evolution 使用时调用，更新 used_count 和 updated_at。"""
    ...
```

---

## 任务二：新建 `prompts/strategist/review.txt`

```
你是一位专业的中文幽默内容研究员，擅长从大量创作案例中提取规律、总结模式。

## 任务
分析以下 {content_type_label} 内容的生成结果，从中提取可复用的创作规律。

## 高分内容（得分 ≥ 7.0）
{high_score_cases}

## 低分内容（得分 ≤ 4.0）
{low_score_cases}

## 人工标注反馈（如有）
{human_feedback}

## 分析要求
请按以下结构输出 JSON，不要包含任何其他文字：

{
  "success_patterns": [
    "成功模式1：具体描述，要可操作，可以直接写进创作要求",
    "成功模式2：..."
  ],
  "failure_patterns": [
    "失败模式1：具体描述这种内容为什么失败，如何避免",
    "失败模式2：..."
  ],
  "new_genes": [
    "可直接加入创作要求的新 bullet point（15-30 字）",
    "另一条新 bullet point"
  ],
  "insight": "一句话核心洞察，总结本次分析最重要的发现",
  "best_case_id": 最高分内容的 ID（整数）,
  "worst_case_id": 最低分内容的 ID（整数）
}
```

---

## 任务三：新建 `prompts/strategist/gene_gen.txt`

```
你是一位专业的中文幽默创作导师，擅长设计具体的创作指令来引导 AI 产出更高质量的幽默内容。

## 背景
当前 {content_type_label} 的生成质量偏弱，平均得分 {avg_score}/10。
主要弱点：{weak_dimensions}

## 已有的创作指令（现有基因）
{existing_genes}

## 任务
设计 {n} 条全新的创作指令，要求：
- 针对上述弱点，直接解决问题
- 与已有指令不重复，不矛盾
- 每条 15-30 字，可以直接用作 bullet point
- 具体可操作，不要泛泛而谈

只输出 JSON 数组，不要其他文字：
["新指令1", "新指令2", ...]
```

---

## 任务四：新建 `strategist.py`

```python
"""
HumorRL — 战略师（Strategist）
使用推理模型（MiniMax-M2.7）定期复盘、提取规律、指导进化方向。
"""

import json
import os
import re
from typing import Optional

import db
import humor_engine
from contract import ContentType, CONTENT_TYPE_LABELS

REVIEW_PROMPT_PATH     = "prompts/strategist/review.txt"
GENE_GEN_PROMPT_PATH   = "prompts/strategist/gene_gen.txt"


def _strategist_client():
    """MiniMax-M2.7 — 战略师专用客户端（复用 judge client）"""
    return humor_engine._judge_client()


def _strategist_chat(prompt: str, max_tokens: int = 2000) -> str:
    """调用推理模型，自动剥离 <think> 块。"""
    model = os.getenv("MINIMAX_STRATEGIST_MODEL", "MiniMax-M2.7")
    raw = humor_engine._chat(
        _strategist_client(), model, prompt,
        temperature=0.3, max_tokens=max_tokens, role="strategist"
    )
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    return raw


def _format_cases(jokes: list, limit: int = 5) -> str:
    """
    将 JokeRecord 列表格式化为 Prompt 中的案例文本。
    格式：
    [ID=123, 得分=8.2]
    内容：xxx
    评分理由：yyy
    ---
    """
    lines = []
    for j in jokes[:limit]:
        score_val = j.score.weighted_total if j.score else 0
        reasoning = j.score.reasoning if j.score else ""
        human = f"人工评分：{j.human_rating}（{j.human_reaction}）" if j.human_rating else ""
        lines.append(
            f"[ID={j.id}, 得分={score_val:.2f}]\n"
            f"内容：{j.text}\n"
            f"评分理由：{reasoning}\n"
            f"{human}"
        )
    return "\n---\n".join(lines) if lines else "（暂无数据）"


def review_and_learn(
    content_type: ContentType,
    sample_size: int = 30,
    db_path: str = db.DB_PATH,
) -> dict:
    """
    战略师复盘主流程：
    1. 从 DB 取最近 sample_size 条（含评分），按分数分为高分组和低分组
    2. 取有人工标注的记录作为 human_feedback
    3. 填入 review.txt prompt，调用推理模型
    4. 解析 JSON 结果：
       - success_patterns → 存入 knowledge_base（entry_type='success_pattern'）
       - failure_patterns → 存入 knowledge_base（entry_type='failure_pattern'）
       - new_genes        → 存入 knowledge_base（entry_type='gene'）
       - insight          → 存入 knowledge_base（entry_type='insight'）
    5. 返回完整报告 dict（含所有解析结果 + 存储的 knowledge id 列表）

    高分组：weighted_total >= 7.0，取分最高的 5 条
    低分组：weighted_total <= 4.0，取分最低的 5 条
    人工反馈：取有 human_rating 的，按 human_rating DESC 取 5 条

    出错时不抛异常，返回 {"error": str, "content_type": str}
    """
    ...


def generate_new_genes(
    content_type: ContentType,
    n: int = 5,
    db_path: str = db.DB_PATH,
) -> list[str]:
    """
    战略师生成新基因（当某类型平均分低于 6.0 时额外调用）：
    1. 取当前最优 prompt 变体的基因列表（_parse_genes）
    2. 计算该类型 6 维度平均分，找出最弱的 2 个维度
    3. 填入 gene_gen.txt prompt，调用推理模型
    4. 解析 JSON 数组，存入 knowledge_base（entry_type='gene'）
    5. 返回新基因列表

    弱维度判断：
    从最近 50 条有评分记录中，取各维度均值，最低的两个即为弱维度。
    维度名称映射：
      structure → "结构完整性", surprise → "意外性",
      relatability → "共鸣度", language → "语言质量",
      creativity → "创意度", safety → "安全性"
    """
    ...


def run_daily_review(db_path: str = db.DB_PATH) -> list[dict]:
    """
    每天运行一次，对所有内容类型做复盘。
    流程：
    1. 对每种 ContentType 调用 review_and_learn()
    2. 若该类型最近30条平均分 < 6.0，额外调用 generate_new_genes()
    3. 返回所有类型的复盘报告列表
    """
    reports = []
    for ct in ContentType:
        report = review_and_learn(ct, db_path=db_path)
        reports.append(report)

        # 额外检查：平均分低则补充生成新基因
        try:
            recent = db.get_jokes(content_type=ct, limit=30, db_path=db_path)
            scored = [j for j in recent if j.score]
            if scored:
                avg = sum(j.score.weighted_total for j in scored) / len(scored)
                if avg < 6.0:
                    new_genes = generate_new_genes(ct, n=5, db_path=db_path)
                    report["extra_genes"] = new_genes
        except Exception:
            pass

    return reports
```

---

## 任务五：修改 `evolution.py` — 动态基因池

将现有的硬编码 `MUTATION_GENE_POOL` 改为动态从 DB 读取，并保留静态列表作为兜底：

```python
# 静态兜底基因池（当知识库为空时使用，保留原有列表）
_STATIC_GENE_POOL = [
    # ... 保留原有的16条 ...
]

def _get_gene_pool(content_type: Optional[ContentType] = None,
                   db_path: str = db.DB_PATH) -> list[str]:
    """
    优先从知识库取动态基因（entry_type='gene'），不足时补充静态兜底。
    同时记录使用次数（increment_knowledge_used）。
    """
    try:
        ct_val = content_type.value if content_type else None
        dynamic = db.get_dynamic_gene_pool(content_type=ct_val, limit=30, db_path=db_path)
        if len(dynamic) >= 8:
            return dynamic
        # 补充静态基因凑满
        return dynamic + _STATIC_GENE_POOL
    except Exception:
        return _STATIC_GENE_POOL
```

在 `mutate()` 函数中将：
```python
replacement = rng.choice(MUTATION_GENE_POOL)
```
改为：
```python
pool = _get_gene_pool(db_path=db_path)
replacement = rng.choice(pool)
```

同时 `mutate()` 函数签名加 `db_path` 参数。

---

## 任务六：修改 `scheduler.py` — 添加战略师定时任务

```python
def job_strategist_review():
    """每天凌晨3点运行战略师复盘（在进化任务之后）。"""
    from strategist import run_daily_review

    logger.info("=== 战略师复盘任务开始 ===")

    if not _check_daily_budget():
        return

    try:
        reports = run_daily_review()
        for report in reports:
            if "error" in report:
                logger.warning(f"复盘失败 [{report.get('content_type')}]: {report['error']}")
            else:
                ct = report.get("content_type", "unknown")
                n_genes  = len(report.get("new_genes", []))
                n_success = len(report.get("success_patterns", []))
                insight  = report.get("insight", "")
                logger.info(
                    f"[{ct}] 复盘完成 | "
                    f"新基因 {n_genes} 条 | 成功模式 {n_success} 条 | "
                    f"洞察：{insight[:50]}"
                )
    except Exception as exc:
        logger.error(f"战略师复盘任务失败：{exc}", exc_info=True)

    logger.info("=== 战略师复盘任务结束 ===")

# 在 main() 中追加：
# scheduler.add_job(job_strategist_review, "cron", hour=3, minute=0)
```

---

## 任务七：修改 `app.py` — 监控页新增知识库 Tab

在 `_page_monitor()` 函数末尾，在"🧬 Prompt 进化状态"expander 之后追加：

```python
    # ── 知识库
    with st.expander("📚 知识库", expanded=False):
        from db import get_knowledge

        kb_type = st.selectbox(
            "条目类型",
            options=["全部", "gene", "success_pattern", "failure_pattern", "insight", "case"],
            format_func=lambda v: {
                "全部": "🔍 全部", "gene": "🧬 基因",
                "success_pattern": "✅ 成功模式", "failure_pattern": "❌ 失败模式",
                "insight": "💡 洞察", "case": "📝 案例",
            }.get(v, v),
            key="kb_type_select",
        )

        entries = get_knowledge(
            entry_type=None if kb_type == "全部" else kb_type,
            limit=30,
        )

        if not entries:
            st.info("知识库暂无条目，等待战略师每日复盘后自动填充。")
        else:
            st.markdown(f'<p style="color:var(--muted);font-size:13px">{len(entries)} 条</p>',
                        unsafe_allow_html=True)
            for e in entries:
                type_icons = {
                    "gene": "🧬", "success_pattern": "✅",
                    "failure_pattern": "❌", "insight": "💡", "case": "📝",
                }
                icon = type_icons.get(e["entry_type"], "📌")
                ct_tag = f'<span class="badge badge-type">{e["content_type"]}</span>' \
                         if e["content_type"] else \
                         '<span class="badge badge-time">通用</span>'
                st.markdown(f"""
                <div class="joke-card" style="margin-bottom:6px;padding:0.75rem 1rem">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div style="flex:1;font-size:13px;color:var(--text);line-height:1.6">
                      {icon} {e['content']}
                    </div>
                    <div style="margin-left:12px;text-align:right;flex-shrink:0">
                      {ct_tag}
                      <div style="font-size:11px;color:var(--muted);margin-top:4px">
                        ⭐ {e['relevance_score']:.1f} · 用{e['used_count']}次
                      </div>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

        # 手动触发战略师（调试用）
        st.markdown('<div style="height:0.5rem"></div>', unsafe_allow_html=True)
        if st.button("🔬 立即运行战略师复盘", key="btn_strategist"):
            with st.spinner("推理模型深度分析中（约30-60秒）……"):
                try:
                    from strategist import run_daily_review
                    reports = run_daily_review()
                    success = sum(1 for r in reports if "error" not in r)
                    st.success(f"复盘完成，{success}/{len(reports)} 个类型成功，刷新页面查看新知识。")
                    st.rerun()
                except Exception as exc:
                    st.error(f"复盘失败：{exc}")
```

---

## 任务八：更新 `.env.example`

追加：
```
MINIMAX_STRATEGIST_MODEL=MiniMax-M2.7
```

---

## 完成后

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add strategist.py db.py evolution.py scheduler.py app.py \
        prompts/strategist/ .env.example
git commit -m "feat(strategist): reasoning model review loop + knowledge base"
git push origin main
```
