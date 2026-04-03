"""
HumorRL 接口契约文件
====================
这是所有 agent 的施工图纸。
- Codex 根据此文件实现 humor_engine.py 和 app.py
- WorkBuddy 根据此文件写生成 prompt 模板
- OpenClaw 根据此文件写评分 prompt 和种子数据

不要修改此文件的接口定义，只做实现。
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional
import datetime


# ─────────────────────────────────────────
# 枚举：内容类型
# ─────────────────────────────────────────

class ContentType(str, Enum):
    STANDUP      = "standup"       # 脱口秀段子
    COLD_JOKE    = "cold_joke"     # 冷笑话
    HUMOR_STORY  = "humor_story"   # 幽默故事
    CROSSTALK    = "crosstalk"     # 相声段子
    TEXT_JOKE    = "text_joke"     # 文字笑话

# 各类型的中文名（用于 UI 展示）
CONTENT_TYPE_LABELS = {
    ContentType.STANDUP:     "脱口秀段子",
    ContentType.COLD_JOKE:   "冷笑话",
    ContentType.HUMOR_STORY: "幽默故事",
    ContentType.CROSSTALK:   "相声段子",
    ContentType.TEXT_JOKE:   "文字笑话",
}

# 各类型对应的 prompt 模板文件路径（相对于项目根目录）
PROMPT_PATHS = {
    ContentType.STANDUP:     "prompts/generate/standup.txt",
    ContentType.COLD_JOKE:   "prompts/generate/cold_joke.txt",
    ContentType.HUMOR_STORY: "prompts/generate/humor_story.txt",
    ContentType.CROSSTALK:   "prompts/generate/crosstalk.txt",
    ContentType.TEXT_JOKE:   "prompts/generate/text_joke.txt",
}

SCORE_PROMPT_PATH = "prompts/evaluate/judge.txt"


# ─────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────

@dataclass
class Persona:
    """人设定义"""
    id: Optional[int]          # DB 主键，新建时为 None
    name: str                  # 角色名，如"毒舌大叔"
    description: str           # 一句话描述
    style_prompt: str          # 注入到生成 prompt 的风格描述（2-5句话）
    is_preset: bool = True


@dataclass
class GenerationRequest:
    """生成请求参数"""
    content_type: ContentType
    persona: Optional[Persona] = None   # None = 无人设模式
    n: int = 5                          # Best-of-N 的 N
    topic: Optional[str] = None         # 可选：指定主题词


@dataclass
class ScoreResult:
    """
    评分结果，所有分数 0-10。
    由 humor_engine.score() 返回。
    """
    structure: float       # 结构完整性（铺垫-包袱）
    surprise: float        # 意外性（包袱猜不到）
    relatability: float    # 共鸣度（有代入感）
    language: float        # 语言质量（用词、节奏）
    creativity: float      # 创意度（新颖，不套路）
    safety: float          # 安全性（无冒犯歧视）
    reasoning: str         # LLM 的评分理由（自然语言）
    critique: str = ""     # Judge 的苛刻批评（先批评再打分的 CoT 内容）
    judge_shape: str = ""  # Judge 路由：short / long
    judge_subtype: str = ""  # Judge 子类型：language / observation / absurd / general
    route_reason: str = ""  # 为什么走到这个 Judge 分支
    display_score: Optional[float] = None  # 给人看的展示分（Phase 1 先用 pointwise fallback）
    display_band: str = ""  # 给人看的分段标签
    benchmark_reason: str = ""  # 展示分解释，后续可升级为锚点区间说明
    structure_summary: str = ""  # 长内容结构摘要
    best_moment: str = ""  # 长内容最成立的一处
    weakest_moment: str = ""  # 长内容最拖后腿的一处

    @property
    def weighted_total(self) -> float:
        """
        加权总分。两道一票否决：
        1. safety < 3 → 直接返回 0（安全问题）
        2. surprise < 5 → 总分封顶 4.0（没有包袱不算笑话）
        """
        if self.safety < 3:
            return 0.0
        raw = (
            self.structure    * 0.15 +
            self.surprise     * 0.25 +
            self.relatability * 0.20 +
            self.language     * 0.15 +
            self.creativity   * 0.15 +
            self.safety       * 0.10
        )
        if self.surprise < 5:
            return min(raw, 4.0)
        return raw


@dataclass
class RankPosition:
    text_index: int
    rank: int
    is_funny: bool
    justification: str
    rank_score: float
    is_anchor: bool = False
    candidate_id: str = ""


@dataclass
class GroupRankResult:
    positions: list[RankPosition]
    anchor_positions: list[RankPosition]
    raw_response: str
    model: str
    anchor_accuracy: float = 0.0


@dataclass
class JokeRecord:
    """
    存入 DB 的完整记录。
    由 db.save_joke() 写入，db.get_jokes() 读出。
    """
    id: Optional[int]                  # DB 主键
    content_type: ContentType
    text: str                          # 段子正文
    persona_id: Optional[int]          # 关联 persona，无人设为 None
    score: Optional[ScoreResult]       # 自动评分结果
    human_rating: Optional[int]        # 人工评分 1-10，未标注为 None
    human_reaction: Optional[str]      # "好笑" | "一般" | "不好笑"
    created_at: datetime.datetime = field(default_factory=datetime.datetime.now)
    parent_id: Optional[int] = None    # 改写来源，原创为 None
    rewrite_round: int = 0             # 第几轮改写，原创为 0
    rank_score: Optional[float] = None
    rank_position: Optional[int] = None
    rank_group_size: Optional[int] = None
    is_funny: Optional[bool] = None
    rank_justification: str = ""

    @property
    def effective_reward(self) -> float:
        if self.rank_score is not None:
            return float(self.rank_score)
        if self.score is not None:
            return float(self.score.weighted_total)
        return 0.0


# ─────────────────────────────────────────
# humor_engine.py 需要实现的函数签名
# ─────────────────────────────────────────

# from humor_engine import generate, score, generate_and_pick_best
#
# def generate(req: GenerationRequest) -> list[str]:
#     """
#     调用 LLM 生成 req.n 条内容，返回纯文本列表。
#     - 读取 PROMPT_PATHS[req.content_type] 的模板
#     - 如果 req.persona 不为 None，将 persona.style_prompt 注入模板
#     - 调用 Anthropic API（模型见 config.py）
#     - 返回 list[str]，长度为 req.n
#     """
#     ...
#
# def score(text: str, content_type: ContentType) -> ScoreResult:
#     """
#     调用 LLM 对一条内容评分，返回 ScoreResult。
#     - 读取 SCORE_PROMPT_PATH 的模板
#     - 将 text 和 content_type 填入模板
#     - 要求 LLM 返回 JSON，解析为 ScoreResult
#     - temperature 用 0.3（保证评分稳定）
#     """
#     ...
#
# def generate_and_pick_best(req: GenerationRequest) -> JokeRecord:
#     """
#     生成 req.n 条 → 全部评分 → 返回加权总分最高的那条（含评分）。
#     返回 JokeRecord（id=None，未存 DB，由调用方决定是否存）。
#     """
#     ...


# ─────────────────────────────────────────
# db.py 需要实现的函数签名
# ─────────────────────────────────────────

# from db import init_db, save_joke, get_jokes, save_persona, get_personas, update_human_rating
#
# def init_db(path: str = "data/humor.db") -> None:
#     """初始化 SQLite，建表（幂等，已存在不报错）"""
#     ...
#
# def save_joke(joke: JokeRecord, db_path: str = "data/humor.db") -> int:
#     """存入 jokes 表，返回新生成的 id"""
#     ...
#
# def get_jokes(
#     content_type: Optional[ContentType] = None,
#     min_score: Optional[float] = None,
#     limit: int = 50,
#     db_path: str = "data/humor.db"
# ) -> list[JokeRecord]:
#     """按条件查询，按 weighted_total 降序"""
#     ...
#
# def save_persona(persona: Persona, db_path: str = "data/humor.db") -> int:
#     """存入 personas 表，返回新生成的 id"""
#     ...
#
# def get_personas(db_path: str = "data/humor.db") -> list[Persona]:
#     """返回所有 persona（包含预设和用户创建）"""
#     ...
#
# def update_human_rating(
#     joke_id: int,
#     rating: int,
#     reaction: str,
#     db_path: str = "data/humor.db"
# ) -> None:
#     """更新人工评分，reaction 只接受 '好笑'|'一般'|'不好笑'"""
#     ...


# ─────────────────────────────────────────
# app.py（Streamlit）需要实现的页面结构
# ─────────────────────────────────────────

# 页面 1 — 生成（默认页）
#   左侧栏：
#     - 内容类型下拉（ContentType 枚举，显示中文名）
#     - Persona 开关（toggle）
#       - 开：出现 persona 下拉（从 db.get_personas() 读取）
#     - 主题词输入框（可选，placeholder="留空则随机主题"）
#     - 生成按钮
#   主区域：
#     - 显示生成结果（文本框）
#     - 显示评分（6维度 + 总分，用 st.metric 或进度条）
#     - 按钮："再来一条" | "保存这条" | "基于这条改写"（P2功能，暂时置灰）
#
# 页面 2 — 历史记录
#   - 筛选栏：内容类型 / 最低分 / 是否已人工评分
#   - 列表：每条显示摘要（前50字）+ 总分 + 类型 + 时间
#   - 点击展开：显示全文 + 评分详情 + 人工评分操作（打分 + 反应选择）
#
# 页面 3 — 统计（简单）
#   - 各类型生成数量 bar chart
#   - 各类型平均分 bar chart
#   - 最近 N 条的分数趋势折线图
