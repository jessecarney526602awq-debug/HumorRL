# Codex 任务单 — HumorRL P2 后端

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> 先读 CLAUDE.md 了解项目结构，再开始写代码。

## 你负责的文件

| 文件 | 操作 |
|------|------|
| `rewriter.py` | 新建 |
| `calibration.py` | 新建 |
| `db.py` | 追加（只加函数，不改现有代码） |
| `requirements.txt` | 追加 scipy（如未有） |

**不要碰 `app.py`，那是 OpenClaw 的任务。**

---

## 任务一：新建 `rewriter.py`

```python
"""
HumorRL — 改写引擎
对评分 4-7 分的内容进行迭代改写，最多3轮，parent_id 追踪链路。
"""
import os
from contract import JokeRecord, ContentType, CONTENT_TYPE_LABELS
import humor_engine   # 复用 _writer_client, _chat, _read_prompt, score
import db

REWRITE_PROMPT_PATH = "prompts/rewrite/rewrite.txt"


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
    ...


def rewrite_until_good(
    original: JokeRecord,
    max_rounds: int = 3,
    target_score: float = 7.0,
    db_path: str = db.DB_PATH,
) -> list[JokeRecord]:
    """
    迭代改写，最多 max_rounds 轮。
    终止条件（满足其一）：
      1. weighted_total >= target_score
      2. 已达 max_rounds 轮
      3. 改写后分数比上一版本下降超过 0.5（越改越烂，提前停止）

    - original.id 必须不为 None（已存 DB），否则 raise ValueError
    - 每轮改写后立即 db.save_joke() 存入 DB 获得真实 id，再传入下一轮
    - 返回所有改写版本列表（含已存 DB 的 id），不含原始版本
    """
    ...
```

**调用姿势（参考）**：
```python
# 复用 humor_engine 的内部工具
prompt = humor_engine._read_prompt(REWRITE_PROMPT_PATH)
prompt = (prompt
    .replace("{original_text}", original.text)
    .replace("{content_type_label}", CONTENT_TYPE_LABELS[original.content_type])
    # ... 其余占位符
)
client = humor_engine._writer_client()
model  = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
new_text = humor_engine._chat(client, model, prompt, temperature=0.85, max_tokens=2000)
new_score = humor_engine.score(new_text, original.content_type)
```

---

## 任务二：新建 `calibration.py`

```python
"""
HumorRL — LLM Judge 校准模块
计算人工评分 vs LLM 评分的皮尔逊相关系数。
"""
import datetime
from dataclasses import dataclass
from typing import Optional
import db
from contract import ContentType


@dataclass
class CalibrationReport:
    sample_size: int
    pearson_r: float
    p_value: float
    llm_mean: float
    llm_std: float
    human_mean: float
    human_std: float
    avg_gap: float          # LLM均值 - 人工均值
    interpretation: str
    generated_at: datetime.datetime


def compute_calibration(
    content_type: Optional[str] = None,
    db_path: str = db.DB_PATH,
) -> CalibrationReport:
    """
    从 DB 取同时有 human_rating 和 score_total 的记录，计算皮尔逊相关。
    content_type：传 ContentType.value 字符串或 None（全类型）。
    sample_size < 2 时 raise ValueError("没有可用于校准的已标注数据")。

    interpretation 规则：
      sample_size < 10 → "样本不足（{n}条），结论不可靠，建议先标注更多数据"
      r >= 0.7  → "LLM 评分与人工评分高度相关（r={r:.2f}），评分系统校准良好"
      r >= 0.4  → "LLM 评分与人工评分中度相关（r={r:.2f}），有一定参考价值"
      r >= 0    → "LLM 评分与人工评分弱相关（r={r:.2f}），建议检查评分 Prompt"
      r < 0     → "LLM 评分与人工评分负相关（r={r:.2f}），评分标准可能存在系统偏差"
      avg_gap > 1.5  → 追加："注意：LLM 评分系统性偏高 {avg_gap:.1f} 分"
      avg_gap < -1.5 → 追加："注意：LLM 评分系统性偏低 {abs(avg_gap):.1f} 分"

    优先用 scipy.stats.pearsonr；不可用时用 numpy 手算，p_value=float('nan')。
    """
    ...


def format_report_text(report: CalibrationReport) -> str:
    """
    格式化为 Markdown，包含：标题、生成时间、样本量、指标表格、结论。
    """
    ...
```

---

## 任务三：修改 `db.py`（只追加，不改现有代码）

在文件末尾追加：

```python
def get_joke_by_id(joke_id: int, db_path: str = DB_PATH) -> Optional[JokeRecord]:
    """按 id 查单条，复用 get_jokes 中的行解析逻辑。不存在返回 None。"""
    ...

def get_rewrite_chain(root_id: int, db_path: str = DB_PATH) -> list[JokeRecord]:
    """
    返回以 root_id 为根的完整改写链（含原始），按 rewrite_round 升序。
    用迭代（不用递归）：
      current_id = root_id
      while current_id:
          record = get_joke_by_id(current_id)
          chain.append(record)
          查找 parent_id = record.id 的下一条
    """
    ...
```

---

## 任务四：检查 `requirements.txt`

确认含有 `scipy>=1.11`，没有则追加。

---

## 完成后

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add rewriter.py calibration.py db.py requirements.txt prompts/rewrite/
git commit -m "feat(P2): rewriter + calibration + db extensions"
git push origin main
```
