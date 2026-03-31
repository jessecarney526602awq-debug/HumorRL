from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ScoreModel(BaseModel):
    structure: float
    surprise: float
    relatability: float
    language: float
    creativity: float
    safety: float
    reasoning: str
    weighted_total: float


class PersonaModel(BaseModel):
    id: int
    name: str
    description: str
    style_prompt: str
    is_preset: bool


class PersonaCreateRequest(BaseModel):
    name: str
    description: str = ""
    style_prompt: str
    is_preset: bool = False


class PersonaUpdateRequest(BaseModel):
    name: str
    description: str = ""
    style_prompt: str


class PersonaAIGenerateRequest(BaseModel):
    name_input: str = ""
    background: str


class GeneratedPersonaResponse(BaseModel):
    name: str
    description: str
    style_prompt: str


class JokeModel(BaseModel):
    id: Optional[int]
    content_type: str
    text: str
    persona_id: Optional[int]
    score: Optional[ScoreModel]
    human_rating: Optional[int]
    human_reaction: Optional[str]
    created_at: datetime
    parent_id: Optional[int]
    rewrite_round: int


class GenerateRequestModel(BaseModel):
    content_type: str
    persona_id: Optional[int] = None
    topic: Optional[str] = None
    n: int = Field(default=3, ge=1, le=10)


class RatingUpdateRequest(BaseModel):
    rating: int = Field(ge=1, le=10)
    reaction: str


class RewriteRequest(BaseModel):
    max_rounds: int = Field(default=3, ge=1, le=5)
    target_score: float = Field(default=7.0, ge=0.0, le=10.0)


class SimpleStatusResponse(BaseModel):
    ok: bool = True
    message: str = "ok"


class StatsByTypeModel(BaseModel):
    type: str
    count: int
    avg_score: float


class RecentScoreModel(BaseModel):
    score: float
    created_at: str


class StatsResponse(BaseModel):
    by_type: list[StatsByTypeModel]
    recent_scores: list[RecentScoreModel]


class CostBreakdownModel(BaseModel):
    model: str
    role: str
    total_tokens: int
    calls: int


class DailyCostModel(BaseModel):
    date: str
    total_tokens: int


class CostStatsResponse(BaseModel):
    total_tokens: int
    by_model: list[CostBreakdownModel]
    daily: list[DailyCostModel]


class CalibrationResponse(BaseModel):
    sample_size: int
    pearson_r: float
    p_value: float
    llm_mean: float
    llm_std: float
    human_mean: float
    human_std: float
    avg_gap: float
    interpretation: str
    generated_at: datetime
    markdown: str


class DiversityResponse(BaseModel):
    entropy: float
    max_entropy: float
    diversity_ratio: float
    type_distribution: dict[str, int]
    interpretation: str


class RewardHackingResponse(BaseModel):
    level: int
    score_trend: float
    repetition_rate: float
    message: str
    action: str


class UCB1SummaryItemModel(BaseModel):
    content_type: str
    label: str
    plays: int
    avg_score: float
    ucb1_value: float | str
    recommended: bool


class KnowledgeEntryModel(BaseModel):
    id: int
    content_type: Optional[str]
    entry_type: str
    content: str
    source_joke_ids: list[int]
    relevance_score: float
    used_count: int
    created_at: str
    updated_at: str


class ReviewRequestModel(BaseModel):
    since_joke_id: Optional[int] = None


class ReviewResponseModel(BaseModel):
    skipped: bool = False
    reason: Optional[str] = None
    processed_count: Optional[int] = None
    success_patterns: list[str] = Field(default_factory=list)
    failure_patterns: list[str] = Field(default_factory=list)
    humor_rules: list[str] = Field(default_factory=list)
    new_genes: list[str] = Field(default_factory=list)
    insight: Optional[str] = None
    best_joke_id: Optional[int] = None
    confidence: Optional[float] = None


class SelfLearnResponseModel(BaseModel):
    skipped: bool = False
    reason: Optional[str] = None
    meta_rules: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    top_features: list[str] = Field(default_factory=list)
    evolution_direction: Optional[str] = None


class DailyReportModel(BaseModel):
    id: int
    report_date: str
    total_generated: int
    avg_score: float
    new_patterns: int
    best_joke_id: Optional[int]
    report_md: str
    created_at: str


class DailyReportGenerateRequest(BaseModel):
    report_date: Optional[str] = None


class PromptVariantModel(BaseModel):
    id: int
    prompt_text: str
    generation: int
    uses: int
    avg_score: float


class EvolveRequestModel(BaseModel):
    content_type: str


class EvolveResponseModel(BaseModel):
    best_variant_id: int
    best_score: float
    improvement: float
    survivor_ids: list[int]
    baseline_best: float
    content_type: str
