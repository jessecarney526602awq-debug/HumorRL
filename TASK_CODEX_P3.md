# Codex 任务单 — HumorRL P3 监控 + 自动化

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **先拉最新代码，先读 CLAUDE.md + contract.py + db.py + app.py 再动手。**

---

## 你负责的全部文件

| 文件 | 操作 |
|------|------|
| `monitor.py` | 新建 — 多样性熵 + Reward Hacking 检测 |
| `scheduler.py` | 新建 — APScheduler 定时任务 |
| `strategy.py` | 新建 — MAB/UCB1 内容类型选择策略 |
| `db.py` | 追加（只加，不改现有） — cost 追踪表 + 写入函数 |
| `humor_engine.py` | 微改 — `_chat()` 调用后记录 token 用量 |
| `app.py` | 追加 — 新增"📡 监控"页面（第6个导航项） |
| `requirements.txt` | 追加 APScheduler + numpy（如未有） |

---

## 任务一：修改 `db.py` — 新增 cost 追踪表

### 1a. 在 `SCHEMA` 字符串末尾追加建表语句

```sql
CREATE TABLE IF NOT EXISTS api_costs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    model       TEXT    NOT NULL,
    role        TEXT    NOT NULL,  -- 'writer' | 'judge'
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_costs_created ON api_costs(created_at);
CREATE INDEX IF NOT EXISTS idx_costs_model   ON api_costs(model);
```

### 1b. 在文件末尾追加函数

```python
def log_api_cost(
    model: str,
    role: str,                # 'writer' | 'judge'
    prompt_tokens: int,
    completion_tokens: int,
    db_path: str = DB_PATH,
) -> None:
    """记录一次 API 调用的 token 用量。"""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO api_costs (model, role, prompt_tokens, completion_tokens, total_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (model, role, prompt_tokens, completion_tokens,
             prompt_tokens + completion_tokens, _now()),
        )


def get_cost_stats(days: int = 7, db_path: str = DB_PATH) -> dict:
    """
    返回最近 N 天的 cost 统计。
    结果格式：
    {
        "total_tokens": int,
        "by_model": [{"model": str, "role": str, "total_tokens": int, "calls": int}],
        "daily": [{"date": str, "total_tokens": int}],   # 按天聚合，最近 days 天
    }
    """
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    with _connect(db_path) as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM api_costs WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()[0]

        by_model = conn.execute(
            "SELECT model, role, SUM(total_tokens) as total_tokens, COUNT(*) as calls "
            "FROM api_costs WHERE created_at >= ? GROUP BY model, role",
            (cutoff,),
        ).fetchall()

        daily = conn.execute(
            "SELECT substr(created_at, 1, 10) as date, SUM(total_tokens) as total_tokens "
            "FROM api_costs WHERE created_at >= ? GROUP BY date ORDER BY date",
            (cutoff,),
        ).fetchall()

    return {
        "total_tokens": int(total),
        "by_model": [
            {"model": r["model"], "role": r["role"],
             "total_tokens": r["total_tokens"], "calls": r["calls"]}
            for r in by_model
        ],
        "daily": [{"date": r["date"], "total_tokens": r["total_tokens"]} for r in daily],
    }
```

---

## 任务二：修改 `humor_engine.py` — `_chat()` 记录 token

**只改 `_chat()` 函数**，在返回前调用 `db.log_api_cost()`：

```python
def _chat(client: OpenAI, model: str, prompt: str, temperature: float, max_tokens: int) -> str:
    resp = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    # 记录 token 用量
    usage = resp.usage
    if usage:
        role = "judge" if "minimax" in (client.base_url.host or "").lower() else "writer"
        try:
            import db as _db
            _db.log_api_cost(
                model=model,
                role=role,
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
            )
        except Exception:
            pass  # cost 记录失败不影响主流程
    return resp.choices[0].message.content.strip()
```

**注意**：`client.base_url` 是 `httpx.URL` 对象，`.host` 属性取主机名。
MiniMax 的 base_url 是 `api.minimax.chat`，DeepSeek 是 `api.deepseek.com`。

---

## 任务三：新建 `monitor.py`

```python
"""
HumorRL — 监控模块
多样性熵计算 + Reward Hacking 检测 + 干预建议
"""
import math
from dataclasses import dataclass
from typing import Optional
import db
from contract import ContentType


@dataclass
class DiversityReport:
    """内容多样性报告"""
    entropy: float          # Shannon 熵，0（完全同质）→ log2(N)（完全均匀）
    max_entropy: float      # 理论最大熵
    diversity_ratio: float  # entropy / max_entropy，0-1
    type_distribution: dict[str, int]   # {content_type: count}
    interpretation: str


@dataclass
class RewardHackingAlert:
    """Reward Hacking 检测结果"""
    level: int              # 0=正常, 1=预警(L1), 2=警告(L2), 3=严重(L3)
    score_trend: float      # 近期分数变化（正=上升，负=下降）
    repetition_rate: float  # 近期内容重复率（0-1）
    message: str            # 人类可读描述
    action: str             # 建议采取的行动


def compute_diversity(
    recent_n: int = 100,
    db_path: str = db.DB_PATH,
) -> DiversityReport:
    """
    计算最近 recent_n 条内容的 Shannon 熵（按内容类型分布）。

    entropy = -sum(p_i * log2(p_i)) for each content_type
    max_entropy = log2(num_types)
    diversity_ratio = entropy / max_entropy

    interpretation 规则：
      diversity_ratio >= 0.8 → "内容分布均衡，多样性良好"
      diversity_ratio >= 0.5 → "内容分布中等，部分类型偏少"
      diversity_ratio < 0.5  → "内容分布集中，建议增加其他类型生成"
    """
    ...


def detect_reward_hacking(
    recent_n: int = 50,
    db_path: str = db.DB_PATH,
) -> RewardHackingAlert:
    """
    检测 Reward Hacking：分数在上升，但内容开始趋同（重复）。

    算法：
    1. 取最近 recent_n 条（含评分）按时间排序
    2. score_trend = 后半段均分 - 前半段均分
    3. repetition_rate：取每条文本前 20 字，统计重复片段占比
       repetition_rate = 重复出现的前缀数 / total，重复定义为出现 ≥2 次的前缀

    告警级别规则：
      L0（正常）：score_trend <= 1.5 OR repetition_rate < 0.3
      L1（预警）：score_trend > 1.5 AND repetition_rate >= 0.3
                  action = "自动微调：下次生成 temperature +0.1（不超过 1.2）"
      L2（警告）：score_trend > 2.0 AND repetition_rate >= 0.5
                  action = "建议暂停自动生成，人工检查近期内容质量"
      L3（严重）：score_trend > 2.5 AND repetition_rate >= 0.7
                  action = "立即停止自动生成，回滚到上一个健康检查点的 Prompt"

    数据不足（< 10 条）时返回 level=0, message="数据不足，暂无检测结果"
    """
    ...
```

---

## 任务四：新建 `strategy.py` — MAB/UCB1

```python
"""
HumorRL — 内容类型选择策略
使用 UCB1（Upper Confidence Bound）算法，
根据历史评分自动选择最优内容类型进行下一次生成。
"""
import math
from typing import Optional
import db
from contract import ContentType


def ucb1_select_content_type(
    db_path: str = db.DB_PATH,
    exploration_weight: float = 1.41,  # sqrt(2)，标准 UCB1
) -> ContentType:
    """
    UCB1 算法选择下一次最应该生成的内容类型。

    UCB1 公式：score(i) = avg_reward(i) + C * sqrt(ln(total_plays) / plays(i))
    其中：
      avg_reward(i) = 该类型的历史平均 weighted_total（归一化到 0-1：除以 10）
      plays(i)      = 该类型的历史生成次数
      total_plays   = 所有类型的总生成次数
      C             = exploration_weight

    冷启动处理：
      - 如果某类型从未生成过（plays=0），优先选择这类型（保证每种类型至少尝试一次）
      - 如果多个类型都未生成过，按 ContentType 枚举顺序选第一个

    从 DB 的 jokes 表取数据：按 content_type GROUP BY，取 COUNT 和 AVG(score_total)。
    score_total 为 NULL 的记录视为 avg_reward=0.5（中性）。

    返回选中的 ContentType。
    """
    ...


def get_type_performance_summary(
    db_path: str = db.DB_PATH,
) -> list[dict]:
    """
    返回各类型的 UCB1 状态摘要，供监控页展示。
    格式：[{
        "content_type": str,        # ContentType.value
        "label": str,               # 中文名
        "plays": int,               # 生成次数
        "avg_score": float,         # 平均分
        "ucb1_value": float,        # 当前 UCB1 值
        "recommended": bool,        # 是否是当前最推荐的类型
    }]
    按 ucb1_value 降序排列。
    """
    ...
```

---

## 任务五：新建 `scheduler.py`

```python
"""
HumorRL — 自动调度器
APScheduler 定时批量生成、评分、Reward Hacking 检查。

启动方式：python scheduler.py
（独立进程，与 Streamlit app 并行运行）
"""
import logging
import os
import time

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

import db
import humor_engine
import monitor
import strategy
from contract import GenerationRequest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# 每日 token 上限（从环境变量读取，默认 500,000）
DAILY_TOKEN_LIMIT = int(os.getenv("DAILY_TOKEN_LIMIT", "500000"))


def _check_daily_budget() -> bool:
    """检查今天的 token 用量是否超限。"""
    stats = db.get_cost_stats(days=1)
    used = stats["total_tokens"]
    if used >= DAILY_TOKEN_LIMIT:
        logger.warning(f"今日 token 用量 {used} 已达上限 {DAILY_TOKEN_LIMIT}，跳过本次生成")
        return False
    return True


def job_batch_generate():
    """
    定时批量生成任务（每小时执行一次）。
    流程：
    1. 检查每日 token 预算
    2. 用 UCB1 选择内容类型
    3. 生成 1 条最优内容（Best-of-3，节省 token）
    4. 存入 DB
    5. 检测 Reward Hacking，L2 及以上则停止本次生成
    """
    logger.info("=== 批量生成任务开始 ===")

    if not _check_daily_budget():
        return

    try:
        content_type = strategy.ucb1_select_content_type()
        logger.info(f"UCB1 选择类型：{content_type.value}")

        # 先检查 Reward Hacking
        alert = monitor.detect_reward_hacking()
        if alert.level >= 2:
            logger.warning(f"Reward Hacking L{alert.level} 检测到，停止生成：{alert.message}")
            return

        req = GenerationRequest(content_type=content_type, n=3)  # Best-of-3
        joke = humor_engine.generate_and_pick_best(req)
        saved_id = db.save_joke(joke)
        logger.info(f"已生成并存储，id={saved_id}，得分={joke.score.weighted_total:.2f}")

        # L1 预警时记录日志
        if alert.level == 1:
            logger.warning(f"Reward Hacking L1 预警：{alert.action}")

    except Exception as exc:
        logger.error(f"批量生成任务失败：{exc}", exc_info=True)

    logger.info("=== 批量生成任务结束 ===")


def job_health_check():
    """
    定时健康检查（每6小时执行一次）。
    - 输出多样性报告
    - 输出 Reward Hacking 检测结果
    - 输出今日 token 用量
    """
    logger.info("=== 健康检查 ===")
    try:
        diversity = monitor.compute_diversity()
        logger.info(f"多样性熵：{diversity.entropy:.3f}（{diversity.interpretation}）")

        alert = monitor.detect_reward_hacking()
        logger.info(f"Reward Hacking Level={alert.level}，{alert.message}")

        cost = db.get_cost_stats(days=1)
        logger.info(f"今日 token 用量：{cost['total_tokens']:,} / {DAILY_TOKEN_LIMIT:,}")
    except Exception as exc:
        logger.error(f"健康检查失败：{exc}", exc_info=True)


def main():
    db.init_db()
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # 每小时整点批量生成
    scheduler.add_job(job_batch_generate, "cron", minute=0)

    # 每6小时健康检查（0/6/12/18点）
    scheduler.add_job(job_health_check, "cron", hour="0,6,12,18", minute=5)

    logger.info("调度器启动，按 Ctrl+C 退出")
    logger.info(f"每日 token 上限：{DAILY_TOKEN_LIMIT:,}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("调度器已停止")


if __name__ == "__main__":
    main()
```

---

## 任务六：`app.py` — 新增"📡 监控"页面

### 6a. 侧边栏导航追加一项

将 `_sidebar_nav()` 中的 radio 列表从 5 项改为 6 项：
```python
["🎲  生成", "📋  历史记录", "📊  统计", "🧑‍🎨  Persona", "🔬  校准报告", "📡  监控"]
```

### 6b. `main()` 追加路由

```python
elif "监控" in page:
    _page_monitor()
```

### 6c. 新增 `_page_monitor()` 函数（追加到文件末尾 `main()` 之前）

```python
def _page_monitor():
    from monitor import compute_diversity, detect_reward_hacking
    from strategy import get_type_performance_summary

    st.markdown("""
    <div class="page-header">
      <h1>监控中心</h1>
      <p>生成质量、多样性、成本与 Reward Hacking 实时检测</p>
    </div>""", unsafe_allow_html=True)

    # ── 刷新按钮
    if st.button("🔄  刷新数据"):
        st.rerun()

    # ── Reward Hacking 告警（放最顶部，醒目）
    try:
        alert = detect_reward_hacking()
        level_colors = {0: "var(--good)", 1: "var(--warn)", 2: "var(--bad)", 3: "#ff0000"}
        level_labels = {0: "✅ 正常", 1: "⚠️ L1 预警", 2: "🚨 L2 警告", 3: "🛑 L3 严重"}
        color = level_colors.get(alert.level, "var(--muted)")
        label = level_labels.get(alert.level, "未知")
        st.markdown(f"""
        <div class="joke-card" style="border-color:{color}">
          <div style="font-size:13px;color:var(--muted);margin-bottom:4px">Reward Hacking 检测</div>
          <div style="font-size:18px;font-weight:700;color:{color};margin-bottom:6px">{label}</div>
          <div style="font-size:13px;color:var(--text)">{alert.message}</div>
          {"<div style='font-size:12px;color:var(--warn);margin-top:8px'>建议：" + alert.action + "</div>" if alert.level > 0 else ""}
        </div>""", unsafe_allow_html=True)
    except Exception as exc:
        st.warning(f"Reward Hacking 检测失败：{exc}")

    st.markdown('<div style="height:1rem"></div>', unsafe_allow_html=True)

    # ── 多样性 + 成本 两列
    col_left, col_right = st.columns(2)

    with col_left:
        st.markdown("**内容多样性**")
        try:
            diversity = compute_diversity()
            st.markdown(f"""
            <div class="stat-card" style="text-align:left;margin-bottom:0.75rem">
              <div style="display:flex;justify-content:space-between;align-items:center">
                <div>
                  <div class="stat-num">{diversity.diversity_ratio:.0%}</div>
                  <div class="stat-lbl">多样性指数（Shannon 熵）</div>
                </div>
                <div style="font-size:28px">{"🌈" if diversity.diversity_ratio >= 0.8 else "🟡" if diversity.diversity_ratio >= 0.5 else "🔴"}</div>
              </div>
              <div style="font-size:12px;color:var(--muted);margin-top:8px">{diversity.interpretation}</div>
            </div>""", unsafe_allow_html=True)
            # 分布柱图
            import pandas as pd
            from contract import CONTENT_TYPE_LABELS
            dist_data = {
                CONTENT_TYPE_LABELS[ContentType(k)]: v
                for k, v in diversity.type_distribution.items()
            }
            if dist_data:
                st.bar_chart(dist_data, height=160)
        except Exception as exc:
            st.info(f"暂无多样性数据：{exc}")

    with col_right:
        st.markdown("**API 成本（近7天）**")
        try:
            cost_stats = get_stats()  # reuse existing; then get cost
            from db import get_cost_stats
            costs = get_cost_stats(days=7)
            total_tok = costs["total_tokens"]
            # 粗略估算费用（DeepSeek $0.14/1M tokens）
            est_usd = total_tok / 1_000_000 * 0.14
            st.markdown(f"""
            <div class="stat-card" style="margin-bottom:0.75rem">
              <div class="stat-num">{total_tok:,}</div>
              <div class="stat-lbl">近7天总 tokens</div>
              <div style="font-size:12px;color:var(--muted);margin-top:4px">≈ ${est_usd:.3f} USD</div>
            </div>""", unsafe_allow_html=True)
            if costs["daily"]:
                daily_data = {r["date"]: r["total_tokens"] for r in costs["daily"]}
                st.line_chart(daily_data, height=160)
        except Exception as exc:
            st.info(f"暂无成本数据：{exc}")

    # ── UCB1 内容类型策略
    st.markdown("**UCB1 内容策略**")
    try:
        summary = get_type_performance_summary()
        from contract import CONTENT_TYPE_LABELS, ContentType as CT
        for item in summary:
            label = item["label"]
            plays = item["plays"]
            avg   = item["avg_score"]
            ucb1  = item["ucb1_value"]
            rec   = item["recommended"]
            bar_w = min(int(ucb1 / 2 * 100), 100)  # UCB1 max ~2，映射到100%
            rec_badge = '<span class="badge badge-type">推荐</span>' if rec else ""
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
              <div style="width:90px;font-size:13px;color:var(--text)">{label} {rec_badge}</div>
              <div style="flex:1">
                <div style="height:6px;background:var(--surface2);border-radius:3px;overflow:hidden">
                  <div style="width:{bar_w}%;height:100%;background:var(--accent);border-radius:3px"></div>
                </div>
              </div>
              <div style="width:120px;font-size:12px;color:var(--muted);text-align:right">
                {plays}次 · 均分{avg:.1f} · UCB1={ucb1:.3f}
              </div>
            </div>""", unsafe_allow_html=True)
    except Exception as exc:
        st.info(f"暂无 UCB1 数据：{exc}")
```

---

## 任务七：`requirements.txt` 追加

```
APScheduler>=3.10
numpy>=1.24
```

---

## 任务八：`docker-compose.yml` 追加 scheduler 服务

在 `docker-compose.yml` 中，`services` 下追加：

```yaml
  scheduler:
    build: .
    container_name: humorrl-scheduler
    restart: unless-stopped
    command: python scheduler.py
    volumes:
      - ./data:/app/data
    env_file:
      - .env
    depends_on:
      - humorrl
```

---

## 完成后

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add monitor.py scheduler.py strategy.py db.py humor_engine.py app.py requirements.txt docker-compose.yml
git commit -m "feat(P3): monitor + scheduler + UCB1 strategy + cost tracking"
git push origin main
```

服务器端更新：
```bash
cd ~/HumorRL && git pull && docker compose up -d --build
```

这会同时启动两个容器：
- `humorrl`：Streamlit UI（端口 8501）
- `humorrl-scheduler`：APScheduler 定时任务（后台静默运行）
