import os
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import db
import evolution
import humor_engine
import monitor
import strategist
import strategy
from api_models import (
    CalibrationResponse,
    CostStatsResponse,
    DailyReportGenerateRequest,
    DailyReportModel,
    DiversityResponse,
    EvolveRequestModel,
    EvolveResponseModel,
    GenerateRequestModel,
    GeneratedPersonaResponse,
    JokeModel,
    KnowledgeEntryModel,
    PersonaAIGenerateRequest,
    PersonaCreateRequest,
    PersonaModel,
    PersonaUpdateRequest,
    PromptVariantModel,
    RatingUpdateRequest,
    RewardHackingResponse,
    ReviewRequestModel,
    ReviewResponseModel,
    RewriteRequest,
    SelfLearnResponseModel,
    SimpleStatusResponse,
    StatsResponse,
    UCB1SummaryItemModel,
)
from calibration import compute_calibration, format_report_text, run_calibration
from contract import ContentType, GenerationRequest, Persona
from rewriter import rewrite_until_good


app = FastAPI(title="Only Funs API", version="1.0.0")
db.init_db()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _parse_content_type(value: str) -> ContentType:
    try:
        return ContentType(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Unsupported content_type: {value}") from exc


def _is_scheduler_alive(jobs: list[dict]) -> bool:
    heartbeat = next((j for j in jobs if j["job_name"] == "heartbeat"), None)
    if not heartbeat or not heartbeat.get("last_run_at"):
        return False
    try:
        delta = datetime.now() - datetime.fromisoformat(heartbeat["last_run_at"])
    except Exception:
        return False
    return delta.total_seconds() < 120


def _should_recover_stale_training(batch_job: Optional[dict], is_alive: bool) -> bool:
    if not batch_job or batch_job.get("last_status") != "running":
        return False
    if is_alive:
        return False
    last_run_at = batch_job.get("last_run_at")
    if not last_run_at:
        return True
    try:
        started_at = datetime.fromisoformat(last_run_at)
    except Exception:
        return True
    # 手动线程或异常退出后，旧的 running 状态可能残留在库里。
    # 超过生成窗口再加一点缓冲后，自动回收这类脏状态。
    grace_seconds = max(int(os.getenv("GENERATE_WINDOW_MINUTES", "28")) * 60 + 120, 180)
    return (datetime.now() - started_at).total_seconds() > grace_seconds


def _score_model(score) -> Optional["ScoreModel"]:
    from api_models import ScoreModel

    if score is None:
        return None
    return ScoreModel(
        structure=score.structure,
        surprise=score.surprise,
        relatability=score.relatability,
        language=score.language,
        creativity=score.creativity,
        safety=score.safety,
        reasoning=score.reasoning,
        critique=score.critique,
        judge_shape=score.judge_shape,
        judge_subtype=score.judge_subtype,
        route_reason=score.route_reason,
        display_score=score.display_score,
        display_band=score.display_band,
        benchmark_reason=score.benchmark_reason,
        structure_summary=score.structure_summary,
        best_moment=score.best_moment,
        weakest_moment=score.weakest_moment,
        weighted_total=score.weighted_total,
    )


def _persona_model(persona: Persona) -> PersonaModel:
    return PersonaModel(
        id=int(persona.id or 0),
        name=persona.name,
        description=persona.description,
        style_prompt=persona.style_prompt,
        is_preset=bool(persona.is_preset),
    )


def _joke_model(joke) -> JokeModel:
    return JokeModel(
        id=joke.id,
        content_type=joke.content_type.value,
        text=joke.text,
        persona_id=joke.persona_id,
        score=_score_model(joke.score),
        human_rating=joke.human_rating,
        human_reaction=joke.human_reaction,
        created_at=joke.created_at,
        parent_id=joke.parent_id,
        rewrite_round=joke.rewrite_round,
        rank_score=joke.rank_score,
        rank_position=joke.rank_position,
        rank_group_size=joke.rank_group_size,
        is_funny=joke.is_funny,
        rank_justification=joke.rank_justification,
        effective_reward=joke.effective_reward,
    )


def _knowledge_model(entry: dict) -> KnowledgeEntryModel:
    raw_ids = str(entry.get("source_joke_ids") or "").strip()
    source_ids = [int(part) for part in raw_ids.split(",") if part]
    return KnowledgeEntryModel(
        id=int(entry["id"]),
        content_type=entry.get("content_type"),
        entry_type=str(entry["entry_type"]),
        content=str(entry["content"]),
        source_joke_ids=source_ids,
        relevance_score=float(entry.get("relevance_score") or 0.0),
        used_count=int(entry.get("used_count") or 0),
        created_at=str(entry.get("created_at") or ""),
        updated_at=str(entry.get("updated_at") or ""),
    )


def _report_model(report: dict) -> DailyReportModel:
    return DailyReportModel(
        id=int(report["id"]),
        report_date=str(report["report_date"]),
        total_generated=int(report["total_generated"] or 0),
        avg_score=float(report["avg_score"] or 0.0),
        new_patterns=int(report["new_patterns"] or 0),
        best_joke_id=report.get("best_joke_id"),
        report_md=str(report["report_md"]),
        created_at=str(report["created_at"]),
    )


def _find_persona(persona_id: int) -> Persona:
    for persona in db.get_personas():
        if persona.id == persona_id:
            return persona
    raise HTTPException(status_code=404, detail=f"Persona {persona_id} not found")


def _service_error(detail: str, status_code: int = 503) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


@app.get("/api/personas", response_model=list[PersonaModel])
def get_personas_api() -> list[PersonaModel]:
    return [_persona_model(persona) for persona in db.get_personas()]


@app.post("/api/personas", response_model=PersonaModel)
def create_persona_api(payload: PersonaCreateRequest) -> PersonaModel:
    persona = Persona(
        id=None,
        name=payload.name.strip(),
        description=payload.description.strip(),
        style_prompt=payload.style_prompt.strip(),
        is_preset=payload.is_preset,
    )
    persona.id = db.save_persona(persona)
    return _persona_model(persona)


@app.put("/api/personas/{persona_id}", response_model=PersonaModel)
def update_persona_api(persona_id: int, payload: PersonaUpdateRequest) -> PersonaModel:
    db.update_persona(
        persona_id,
        payload.name.strip(),
        payload.description.strip(),
        payload.style_prompt.strip(),
    )
    return _persona_model(_find_persona(persona_id))


@app.delete("/api/personas/{persona_id}", response_model=SimpleStatusResponse)
def delete_persona_api(persona_id: int) -> SimpleStatusResponse:
    db.delete_persona(persona_id)
    return SimpleStatusResponse(message="persona deleted")


@app.post("/api/personas/ai-generate", response_model=GeneratedPersonaResponse)
def ai_generate_persona_api(payload: PersonaAIGenerateRequest) -> GeneratedPersonaResponse:
    try:
        return GeneratedPersonaResponse(**strategist.generate_persona_style(payload.name_input, payload.background))
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise _service_error(f"AI Persona 服务未就绪：{exc}") from exc
    except Exception as exc:
        raise _service_error(f"AI Persona 生成失败：{exc}", status_code=500) from exc


@app.post("/api/generate", response_model=JokeModel)
def generate_api(payload: GenerateRequestModel) -> JokeModel:
    try:
        content_type = _parse_content_type(payload.content_type)
        persona = _find_persona(payload.persona_id) if payload.persona_id is not None else None
        joke = humor_engine.generate_and_pick_best(
            GenerationRequest(
                content_type=content_type,
                persona=persona,
                topic=payload.topic,
                n=payload.n,
            )
        )
        joke.id = db.save_joke(joke)
        return _joke_model(joke)
    except HTTPException:
        raise
    except FileNotFoundError as exc:
        raise _service_error(f"生成模板缺失：{exc}", status_code=500) from exc
    except RuntimeError as exc:
        raise _service_error(f"生成服务未就绪：{exc}") from exc
    except Exception as exc:
        raise _service_error(f"生成失败：{exc}", status_code=500) from exc


@app.get("/api/jokes", response_model=list[JokeModel])
def get_jokes_api(
    content_type: Optional[str] = None,
    min_score: Optional[float] = None,
    unrated_only: bool = False,
    limit: int = Query(default=50, ge=1, le=500),
) -> list[JokeModel]:
    ct = _parse_content_type(content_type) if content_type else None
    jokes = db.get_jokes(content_type=ct, min_score=min_score, unrated_only=unrated_only, limit=limit)
    return [_joke_model(joke) for joke in jokes]


@app.put("/api/jokes/{joke_id}/rating", response_model=JokeModel)
def update_rating_api(joke_id: int, payload: RatingUpdateRequest) -> JokeModel:
    db.update_human_rating(joke_id, payload.rating, payload.reaction)
    joke = db.get_joke_by_id(joke_id)
    if joke is None:
        raise HTTPException(status_code=404, detail=f"Joke {joke_id} not found")
    return _joke_model(joke)


@app.post("/api/jokes/{joke_id}/rewrite", response_model=list[JokeModel])
def rewrite_joke_api(joke_id: int, payload: RewriteRequest) -> list[JokeModel]:
    joke = db.get_joke_by_id(joke_id)
    if joke is None:
        raise HTTPException(status_code=404, detail=f"Joke {joke_id} not found")
    try:
        rewritten = rewrite_until_good(joke, max_rounds=payload.max_rounds, target_score=payload.target_score)
        return [_joke_model(item) for item in rewritten]
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise _service_error(f"改写服务未就绪：{exc}") from exc
    except Exception as exc:
        raise _service_error(f"改写失败：{exc}", status_code=500) from exc


@app.get("/api/stats", response_model=StatsResponse)
def get_stats_api() -> StatsResponse:
    return StatsResponse(**db.get_stats())


@app.get("/api/costs", response_model=CostStatsResponse)
def get_costs_api(days: int = Query(default=7, ge=1, le=30)) -> CostStatsResponse:
    return CostStatsResponse(**db.get_cost_stats(days=days))


@app.get("/api/calibration", response_model=CalibrationResponse)
def get_calibration_api(content_type: Optional[str] = None) -> CalibrationResponse:
    report = compute_calibration(content_type=content_type)
    return CalibrationResponse(
        sample_size=report.sample_size,
        pearson_r=report.pearson_r,
        p_value=report.p_value,
        llm_mean=report.llm_mean,
        llm_std=report.llm_std,
        human_mean=report.human_mean,
        human_std=report.human_std,
        avg_gap=report.avg_gap,
        interpretation=report.interpretation,
        generated_at=report.generated_at,
        markdown=format_report_text(report),
    )


@app.post("/api/calibration/run")
def trigger_calibration_api():
    try:
        result = run_calibration()
        return {
            "status": "success",
            "sample_size": result["sample_size"],
            "spearman": result["overall_spearman"],
            "pearson": result["overall_pearson"],
            "classification_accuracy": result["classification_accuracy"],
            "dimension_biases": result["dimension_biases"],
            "lessons": result["lessons"],
            "judge_lessons": result["judge_lessons"],
            "writer_lessons": result["writer_lessons"],
            "judge_directive": result["judge_directive"],
            "report": result["report_md"],
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/api/calibration/latest")
def get_latest_calibration_api():
    result = db.get_latest_calibration()
    if not result:
        return {"status": "no_data", "message": "尚未运行过校准"}
    return {"status": "ok", "data": result}


@app.get("/api/monitor/diversity", response_model=DiversityResponse)
def get_diversity_api() -> DiversityResponse:
    return DiversityResponse(**monitor.compute_diversity().__dict__)


@app.get("/api/monitor/hacking", response_model=RewardHackingResponse)
def get_hacking_api() -> RewardHackingResponse:
    return RewardHackingResponse(**monitor.detect_reward_hacking().__dict__)


@app.get("/api/monitor/ucb1", response_model=list[UCB1SummaryItemModel])
def get_ucb1_api() -> list[UCB1SummaryItemModel]:
    items = []
    for item in strategy.get_type_performance_summary():
        value = item["ucb1_value"]
        items.append(
            UCB1SummaryItemModel(
                content_type=item["content_type"],
                label=item["label"],
                plays=int(item["plays"]),
                avg_score=float(item["avg_score"]),
                ucb1_value="inf" if value == float("inf") else float(value),
                recommended=bool(item["recommended"]),
            )
        )
    return items


@app.get("/api/knowledge", response_model=list[KnowledgeEntryModel])
def get_knowledge_api(entry_type: Optional[str] = None) -> list[KnowledgeEntryModel]:
    return [_knowledge_model(entry) for entry in db.get_knowledge(entry_type=entry_type, limit=100)]


@app.post("/api/strategist/review", response_model=ReviewResponseModel)
def run_review_api(payload: Optional[ReviewRequestModel] = None) -> ReviewResponseModel:
    since_joke_id = payload.since_joke_id if payload else None
    if since_joke_id is None:
        since_joke_id = db.get_last_strategist_joke_id()
    result = strategist.incremental_review(since_joke_id)
    return ReviewResponseModel(**result)


@app.post("/api/strategist/self-learn", response_model=SelfLearnResponseModel)
def self_learn_api() -> SelfLearnResponseModel:
    return SelfLearnResponseModel(**strategist.self_learn())


@app.get("/api/reports", response_model=list[DailyReportModel])
def get_reports_api() -> list[DailyReportModel]:
    return [_report_model(report) for report in db.get_daily_reports(limit=30)]


@app.post("/api/reports/generate", response_model=DailyReportModel)
def generate_report_api(payload: DailyReportGenerateRequest) -> DailyReportModel:
    strategist.generate_daily_report(report_date=payload.report_date)
    reports = db.get_daily_reports(limit=1)
    if not reports:
        raise HTTPException(status_code=500, detail="Report generation failed")
    return _report_model(reports[0])


@app.get("/api/variants", response_model=list[PromptVariantModel])
def get_variants_api(content_type: str) -> list[PromptVariantModel]:
    _parse_content_type(content_type)
    return [PromptVariantModel(**item) for item in db.get_active_variants(content_type)]


@app.post("/api/training/trigger")
def trigger_training():
    """手动触发一次完整训练周期（后台线程，立即返回）。"""
    import threading

    jobs = db.get_job_statuses()
    is_alive = _is_scheduler_alive(jobs)
    batch_job = next((j for j in jobs if j["job_name"] == "batch_generate"), None)
    if _should_recover_stale_training(batch_job, is_alive):
        db.upsert_job_status("batch_generate", "error", {"error": "stale_training_state_recovered"})
        jobs = db.get_job_statuses()

    # 如果 batch_generate 仍在运行，拒绝重复触发
    running = next((j for j in jobs if j["job_name"] == "batch_generate" and j["last_status"] == "running"), None)
    if running:
        raise HTTPException(status_code=409, detail="训练周期已在运行中")
    db.set_stop_flag(False)
    try:
        from scheduler import job_training_cycle
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"训练服务未就绪：{exc}") from exc

    def _run():
        try:
            job_training_cycle()
        except Exception as exc:
            db.upsert_job_status("batch_generate", "error", {"error": str(exc)})

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@app.post("/api/training/stop")
def stop_training():
    """请求终止当前训练周期（在下一轮生成完后生效）。"""
    db.set_stop_flag(True)
    return {"stop_requested": True}


@app.get("/api/scheduler/status")
def get_scheduler_status():
    jobs = db.get_job_statuses()
    is_alive = _is_scheduler_alive(jobs)

    last_id = db.get_last_strategist_joke_id()
    jokes_since = db.count_jokes_since(last_id)
    interval = int(os.getenv("STRATEGIST_TRIGGER_INTERVAL", "5"))
    progress_pct = min(int(jokes_since / interval * 100), 100) if interval > 0 else 0

    all_kb = db.get_knowledge(limit=1000)
    genes = [e for e in all_kb if e["entry_type"] == "gene"]
    rules = [e for e in all_kb if e["entry_type"] == "humor_rule"]

    batch_job = next((j for j in jobs if j["job_name"] == "batch_generate"), None)
    if _should_recover_stale_training(batch_job, is_alive):
        db.upsert_job_status("batch_generate", "error", {"error": "stale_training_state_recovered"})
        jobs = db.get_job_statuses()
        batch_job = next((j for j in jobs if j["job_name"] == "batch_generate"), None)
    is_training = bool(batch_job and batch_job.get("last_status") == "running")

    return {
        "is_alive": is_alive,
        "is_training": is_training,
        "jobs": [j for j in jobs if j["job_name"] not in ("heartbeat", "training_stop")],
        "training_progress": {
            "jokes_since_last_review": jokes_since,
            "trigger_interval": interval,
            "progress_pct": progress_pct,
        },
        "knowledge_stats": {
            "total": len([e for e in all_kb if e["entry_type"] != "_checkpoint"]),
            "genes": len(genes),
            "rules": len(rules),
        },
    }


@app.post("/api/evolve", response_model=EvolveResponseModel)
def evolve_api(payload: EvolveRequestModel) -> EvolveResponseModel:
    content_type = _parse_content_type(payload.content_type)
    report = evolution.run_evolution(
        content_type=content_type,
        population_size=4,
        generations=1,
        eval_n=2,
    )
    return EvolveResponseModel(
        best_variant_id=int(report["best_variant_id"]),
        best_score=float(report["best_score"]),
        improvement=float(report["improvement"]),
        survivor_ids=[int(item) for item in report["survivor_ids"]],
        baseline_best=float(report["baseline_best"]),
        content_type=content_type.value,
    )
