"""
HumorRL — Streamlit UI
视觉设计对应 Figma Make: DFXQR5oqREgG7rBHX59jFr
页面：生成 / 历史记录 / 统计
"""

import streamlit as st

import humor_engine
from contract import CONTENT_TYPE_LABELS, ContentType, GenerationRequest
from calibration import compute_calibration, format_report_text
from db import (
    get_joke_by_id,
    get_jokes,
    get_personas,
    get_rewrite_chain,
    get_stats,
    init_db,
    save_joke,
    save_persona,
    update_human_rating,
)
from rewriter import rewrite_until_good

# ─────────────────────────────────────────
# 页面基础配置
# ─────────────────────────────────────────
st.set_page_config(
    page_title="HumorRL",
    page_icon="😂",
    layout="wide",
    initial_sidebar_state="expanded",
)
init_db()

# ─────────────────────────────────────────
# 全局样式
# ─────────────────────────────────────────
st.markdown("""
<style>
/* ── 基础变量 ─────────────────────────── */
:root {
    --bg:        #0f1117;
    --surface:   #1a1d27;
    --surface2:  #22263a;
    --border:    #2e3250;
    --accent:    #7c5cfc;
    --accent2:   #a78bfa;
    --text:      #e8eaf0;
    --muted:     #7b82a0;
    --good:      #34d399;
    --warn:      #fbbf24;
    --bad:       #f87171;
    --radius:    12px;
}

/* ── Streamlit 外壳重置 ────────────────── */
html, body, [class*="css"] { font-family: 'Inter', 'PingFang SC', sans-serif; }
.stApp { background: var(--bg); }
section[data-testid="stSidebar"] {
    background: var(--surface) !important;
    border-right: 1px solid var(--border);
}
section[data-testid="stSidebar"] > div { padding: 1.5rem 1rem; }

/* ── 侧边栏 Logo ───────────────────────── */
.sidebar-logo {
    display: flex; align-items: center; gap: 10px;
    padding: 0.25rem 0.5rem 1.5rem;
    border-bottom: 1px solid var(--border);
    margin-bottom: 1rem;
}
.sidebar-logo .logo-icon {
    width: 36px; height: 36px; border-radius: 8px;
    background: linear-gradient(135deg, var(--accent), #c084fc);
    display: flex; align-items: center; justify-content: center;
    font-size: 18px;
}
.sidebar-logo .logo-text {
    font-weight: 700; font-size: 16px;
    color: var(--text); letter-spacing: 0.3px;
}

/* ── 导航按钮 ──────────────────────────── */
div[data-testid="stRadio"] label {
    display: flex !important; align-items: center;
    gap: 10px; padding: 10px 12px;
    border-radius: 8px;
    color: var(--muted) !important;
    font-size: 14px; font-weight: 500;
    cursor: pointer; transition: all 0.15s;
    margin: 2px 0;
}
div[data-testid="stRadio"] label:hover {
    background: var(--surface2); color: var(--text) !important;
}
div[data-testid="stRadio"] label[data-checked="true"] {
    background: rgba(124,92,252,0.15) !important;
    color: var(--accent2) !important;
}
div[data-testid="stRadio"] [data-testid="stMarkdownContainer"] p { margin: 0; }
div[data-testid="stRadio"] input { display: none !important; }

/* ── 页面标题 ──────────────────────────── */
.page-header {
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}
.page-header h1 {
    font-size: 22px; font-weight: 700;
    color: var(--text); margin: 0 0 4px;
}
.page-header p { color: var(--muted); font-size: 13px; margin: 0; }

/* ── 段子卡片 ──────────────────────────── */
.joke-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.75rem;
    transition: border-color 0.2s;
}
.joke-card:hover { border-color: var(--accent); }
.joke-card .joke-text {
    font-size: 15px; line-height: 1.8;
    color: var(--text); white-space: pre-wrap;
    margin-bottom: 1rem;
}
.joke-card .joke-meta {
    display: flex; gap: 8px; flex-wrap: wrap;
    align-items: center;
}

/* ── 标签徽章 ──────────────────────────── */
.badge {
    display: inline-flex; align-items: center;
    padding: 3px 10px; border-radius: 20px;
    font-size: 11px; font-weight: 600;
    letter-spacing: 0.3px;
}
.badge-type  { background: rgba(124,92,252,0.2); color: var(--accent2); }
.badge-score-good { background: rgba(52,211,153,0.15); color: var(--good); }
.badge-score-mid  { background: rgba(251,191,36,0.15);  color: var(--warn); }
.badge-score-bad  { background: rgba(248,113,113,0.15); color: var(--bad);  }
.badge-time  { background: var(--surface2); color: var(--muted); }

/* ── 分数进度条 ───────────────────────── */
.score-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; margin: 1rem 0; }
.score-item { }
.score-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; font-weight: 500; }
.score-value { font-size: 15px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
.score-bar-wrap { height: 4px; background: var(--surface2); border-radius: 2px; overflow: hidden; }
.score-bar { height: 100%; border-radius: 2px; transition: width 0.4s; }

/* ── 总分大字 ─────────────────────────── */
.total-score-block {
    display: flex; align-items: center; gap: 16px;
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 1rem 1.25rem;
    margin: 1rem 0;
}
.total-score-number { font-size: 36px; font-weight: 800; }
.total-score-label  { font-size: 12px; color: var(--muted); margin-top: 2px; }
.total-score-reasoning { font-size: 12px; color: var(--muted); line-height: 1.6; }

/* ── 空状态 ───────────────────────────── */
.empty-state {
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 4rem 2rem; text-align: center;
    color: var(--muted);
}
.empty-state .empty-icon { font-size: 48px; margin-bottom: 1rem; }
.empty-state h3 { font-size: 16px; font-weight: 600; color: var(--text); margin-bottom: 8px; }
.empty-state p  { font-size: 13px; }

/* ── 生成结果区 ───────────────────────── */
.result-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    margin-bottom: 1rem;
    font-size: 15px; line-height: 1.9;
    color: var(--text); white-space: pre-wrap;
    min-height: 160px;
}

/* ── 按钮覆写 ─────────────────────────── */
.stButton > button {
    background: var(--accent) !important;
    color: #fff !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
    font-size: 14px !important; padding: 10px 20px !important;
    transition: opacity 0.15s !important;
}
.stButton > button:hover { opacity: 0.85 !important; }
.stButton > button:disabled {
    background: var(--surface2) !important;
    color: var(--muted) !important;
}

/* ── 输入框覆写 ───────────────────────── */
.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb] {
    background: var(--surface2) !important;
    border: 1px solid var(--border) !important;
    border-radius: 8px !important;
    color: var(--text) !important;
}
.stToggle label { color: var(--text) !important; }

/* ── 侧边栏参数区 ─────────────────────── */
.sidebar-section {
    background: var(--surface2);
    border-radius: var(--radius);
    padding: 1rem;
    margin-bottom: 1rem;
}
.sidebar-section-title {
    font-size: 11px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.8px;
    color: var(--muted); margin-bottom: 0.75rem;
}

/* ── 统计卡片 ─────────────────────────── */
.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.5rem;
    text-align: center;
}
.stat-card .stat-num { font-size: 28px; font-weight: 800; color: var(--text); }
.stat-card .stat-lbl { font-size: 12px; color: var(--muted); margin-top: 4px; }

/* ── 隐藏默认 Streamlit 元素 ─────────── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem !important; max-width: 1100px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# Session State
# ─────────────────────────────────────────
def _init_state():
    defaults = {
        "generated_joke": None,
        "generated_saved": False,
        "expanded_joke_id": None,
        "rewrite_source_id": None,
        "rewrite_results": [],
        "rewrite_in_progress": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


# ─────────────────────────────────────────
# 辅助：分数颜色 & 进度条
# ─────────────────────────────────────────
CONTENT_ICONS = {
    ContentType.STANDUP:     "🎤",
    ContentType.COLD_JOKE:   "🧊",
    ContentType.HUMOR_STORY: "📖",
    ContentType.CROSSTALK:   "🎭",
    ContentType.TEXT_JOKE:   "✍️",
}

def _score_color(v: float) -> str:
    if v >= 7:   return "#34d399"
    if v >= 4.5: return "#fbbf24"
    return "#f87171"

def _score_badge_cls(v: float) -> str:
    if v >= 7:   return "badge-score-good"
    if v >= 4.5: return "badge-score-mid"
    return "badge-score-bad"

def _render_score_bars(score) -> None:
    dims = [
        ("结构", score.structure),
        ("意外", score.surprise),
        ("共鸣", score.relatability),
        ("语言", score.language),
        ("创意", score.creativity),
        ("安全", score.safety),
    ]
    cells = ""
    for label, val in dims:
        color = _score_color(val)
        pct = val * 10
        cells += f"""
        <div class="score-item">
          <div class="score-label">{label}</div>
          <div class="score-value" style="color:{color}">{val:.1f}</div>
          <div class="score-bar-wrap">
            <div class="score-bar" style="width:{pct}%;background:{color}"></div>
          </div>
        </div>"""
    st.markdown(f'<div class="score-grid">{cells}</div>', unsafe_allow_html=True)


def _render_total_score(score) -> None:
    total = score.weighted_total
    color = _score_color(total)
    st.markdown(f"""
    <div class="total-score-block">
      <div>
        <div class="total-score-number" style="color:{color}">{total:.2f}</div>
        <div class="total-score-label">加权总分</div>
      </div>
      <div class="total-score-reasoning">{score.reasoning}</div>
    </div>""", unsafe_allow_html=True)


# ─────────────────────────────────────────
# 侧边栏
# ─────────────────────────────────────────
def _sidebar_nav() -> str:
    st.markdown("""
    <div class="sidebar-logo">
      <div class="logo-icon">😂</div>
      <div class="logo-text">HumorRL</div>
    </div>""", unsafe_allow_html=True)

    page = st.radio(
        "导航",
        ["🎲  生成", "📋  历史记录", "📊  统计", "🧑‍🎨  Persona", "🔬  校准报告", "📡  监控"],
        label_visibility="collapsed",
    )
    return page


# ─────────────────────────────────────────
# 页面 1 — 生成
# ─────────────────────────────────────────
def _page_generate():
    st.markdown("""
    <div class="page-header">
      <h1>生成段子</h1>
      <p>配置参数，用 AI 生成最佳幽默内容</p>
    </div>""", unsafe_allow_html=True)

    personas = get_personas()

    # ── 左侧参数栏
    with st.sidebar:
        st.markdown('<div class="sidebar-section-title">内容类型</div>', unsafe_allow_html=True)
        content_type = st.selectbox(
            "内容类型",
            options=list(ContentType),
            format_func=lambda ct: f"{CONTENT_ICONS[ct]}  {CONTENT_TYPE_LABELS[ct]}",
            label_visibility="collapsed",
        )
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-section-title">主题词</div>', unsafe_allow_html=True)
        topic = st.text_input(
            "主题词",
            value="",
            placeholder="留空则随机主题",
            label_visibility="collapsed",
        )
        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

        st.markdown('<div class="sidebar-section-title">Persona</div>', unsafe_allow_html=True)
        use_persona = st.toggle("启用 Persona", value=False)
        selected_persona = None
        if use_persona and personas:
            selected_persona = st.selectbox(
                "选择 Persona",
                options=personas,
                format_func=lambda p: p.name,
                label_visibility="collapsed",
            )
            if selected_persona:
                st.caption(f"📝 {selected_persona.description}")

        st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
        should_generate = st.button("✨  开始生成", use_container_width=True)

    # ── 触发生成
    if should_generate:
        req = GenerationRequest(
            content_type=content_type,
            persona=selected_persona,
            topic=topic.strip() or None,
        )
        with st.spinner("AI 正在思考最好笑的方式……"):
            try:
                st.session_state.generated_joke = humor_engine.generate_and_pick_best(req)
                st.session_state.generated_saved = False
                st.session_state.rewrite_source_id = None
                st.session_state.rewrite_results = []
            except Exception as exc:
                st.error(f"生成失败：{exc}")

    # ── 结果展示
    joke = st.session_state.generated_joke
    if not joke:
        st.markdown("""
        <div class="empty-state">
          <div class="empty-icon">🎭</div>
          <h3>还没有生成内容</h3>
          <p>在左侧选择类型，点击「开始生成」按钮</p>
        </div>""", unsafe_allow_html=True)
        return

    # 内容展示
    ct_label = CONTENT_TYPE_LABELS[joke.content_type]
    ct_icon  = CONTENT_ICONS[joke.content_type]
    st.markdown(f"""
    <div class="result-box">{joke.text}</div>
    <div style="display:flex;gap:8px;margin-bottom:1rem">
      <span class="badge badge-type">{ct_icon} {ct_label}</span>
    </div>""", unsafe_allow_html=True)

    # 评分
    if joke.score:
        _render_score_bars(joke.score)
        _render_total_score(joke.score)

    # 操作按钮
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        if st.button("💾  保存这条", disabled=st.session_state.generated_saved, use_container_width=True):
            try:
                saved_id = save_joke(joke)
                st.session_state.generated_joke.id = saved_id
                st.session_state.generated_saved = True
                st.success(f"已保存！ID = {saved_id}")
            except Exception as exc:
                st.error(f"保存失败：{exc}")
    with col2:
        if st.button("🔄  再来一条", use_container_width=True):
            req = GenerationRequest(
                content_type=content_type,
                persona=selected_persona,
                topic=topic.strip() or None,
            )
            with st.spinner("换一个角度……"):
                try:
                    st.session_state.generated_joke = humor_engine.generate_and_pick_best(req)
                    st.session_state.generated_saved = False
                    st.session_state.rewrite_source_id = None
                    st.session_state.rewrite_results = []
                    st.rerun()
                except Exception as exc:
                    st.error(f"生成失败：{exc}")
    with col3:
        score_val = joke.score.weighted_total if joke.score else 0
        rewrite_ok = joke.score is not None and 4.0 <= score_val <= 7.0

        if st.button(
            "✏️  改写",
            disabled=not rewrite_ok or not st.session_state.generated_saved,
            use_container_width=True,
            key="btn_rewrite_gen",
        ):
            with st.spinner("AI 正在改写……"):
                st.session_state.rewrite_in_progress = True
                try:
                    source = get_joke_by_id(st.session_state.generated_joke.id)
                    results = rewrite_until_good(source, max_rounds=3)
                    st.session_state.rewrite_source_id = source.id if source else None
                    st.session_state.rewrite_results = results
                except Exception as exc:
                    st.error(f"改写失败：{exc}")
                finally:
                    st.session_state.rewrite_in_progress = False

        if not st.session_state.generated_saved and rewrite_ok:
            st.caption("💡 先保存后再改写")
        elif joke.score and score_val > 7.0:
            st.caption("✅ 分数够高，无需改写")
        elif joke.score and score_val < 4.0:
            st.caption("❌ 分数过低，改写效果有限")

    if st.session_state.rewrite_results:
        st.markdown("---")
        st.markdown("**改写历程**")
        for rw in st.session_state.rewrite_results:
            total = rw.score.weighted_total if rw.score else 0
            with st.expander(f"第 {rw.rewrite_round} 轮改写 — 得分 {total:.2f}"):
                st.markdown(
                    f'<div class="result-box" style="min-height:auto">{rw.text}</div>',
                    unsafe_allow_html=True,
                )
                if rw.score:
                    _render_score_bars(rw.score)
                    st.caption(f"💬 {rw.score.reasoning}")


# ─────────────────────────────────────────
# 页面 2 — 历史记录
# ─────────────────────────────────────────
def _page_history():
    st.markdown("""
    <div class="page-header">
      <h1>历史记录</h1>
      <p>查看、筛选并标注所有生成内容</p>
    </div>""", unsafe_allow_html=True)

    # ── 筛选栏
    f1, f2, f3 = st.columns([2, 2, 1])
    with f1:
        type_opts = ["全部"] + list(ContentType)
        ct_filter = st.selectbox(
            "内容类型",
            options=type_opts,
            format_func=lambda v: "🔍 全部类型" if v == "全部"
                else f"{CONTENT_ICONS[v]} {CONTENT_TYPE_LABELS[v]}",
        )
    with f2:
        min_score = st.slider("最低评分", 0, 10, 0)
    with f3:
        unrated_only = st.checkbox("仅未标注", value=False)

    jokes = get_jokes(
        content_type=ct_filter if isinstance(ct_filter, ContentType) else None,
        min_score=float(min_score) if min_score > 0 else None,
        unrated_only=unrated_only,
        limit=100,
    )

    if not jokes:
        st.markdown("""
        <div class="empty-state">
          <div class="empty-icon">📭</div>
          <h3>没有符合条件的记录</h3>
          <p>先去生成一些内容，或调整筛选条件</p>
        </div>""", unsafe_allow_html=True)
        return

    # ── 汇总信息
    st.markdown(
        f'<p style="color:var(--muted);font-size:13px;margin-bottom:1rem">共 {len(jokes)} 条</p>',
        unsafe_allow_html=True,
    )

    # ── 历史卡片列表
    for joke in jokes:
        total  = joke.score.weighted_total if joke.score else 0.0
        s_cls  = _score_badge_cls(total)
        ct_lbl = CONTENT_TYPE_LABELS[joke.content_type]
        ct_ico = CONTENT_ICONS[joke.content_type]
        preview = joke.text[:60] + ("…" if len(joke.text) > 60 else "")
        ts = joke.created_at.strftime("%m-%d %H:%M")
        rated_tag = (
            f'<span class="badge {_score_badge_cls(joke.human_rating or 0)}">'
            f'⭐ {joke.human_rating}</span>' if joke.human_rating else
            '<span class="badge badge-time">未标注</span>'
        )

        with st.expander(f"{ct_ico}  {preview}"):
            # 元信息行
            st.markdown(f"""
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:1rem;align-items:center">
              <span class="badge badge-type">{ct_ico} {ct_lbl}</span>
              <span class="badge {s_cls}">AI {total:.2f}</span>
              {rated_tag}
              <span class="badge badge-time">🕐 {ts}</span>
            </div>""", unsafe_allow_html=True)

            # 全文
            st.markdown(
                f'<div class="result-box" style="min-height:auto">{joke.text}</div>',
                unsafe_allow_html=True,
            )

            # 评分详情
            if joke.score:
                _render_score_bars(joke.score)
                st.caption(f"💬 {joke.score.reasoning}")

            if joke.score and 4.0 <= joke.score.weighted_total <= 7.0:
                st.markdown(
                    '<span class="badge badge-score-mid">✏️ 可改写区间</span>',
                    unsafe_allow_html=True,
                )
                if st.button("改写这条", key=f"rewrite_hist_{joke.id}"):
                    with st.spinner("AI 改写中……"):
                        try:
                            results = rewrite_until_good(joke, max_rounds=3)
                            for rw in results:
                                total = rw.score.weighted_total if rw.score else 0
                                st.markdown(f"**第 {rw.rewrite_round} 轮** — 得分 {total:.2f}")
                                st.markdown(
                                    f'<div class="result-box" style="min-height:auto">{rw.text}</div>',
                                    unsafe_allow_html=True,
                                )
                        except Exception as exc:
                            st.error(f"改写失败：{exc}")
            st.divider()

            # 人工标注
            st.markdown("**人工标注**")
            r_col1, r_col2 = st.columns([3, 2])
            with r_col1:
                rating = st.slider(
                    "打分", 1, 10,
                    value=joke.human_rating or 6,
                    key=f"rating_{joke.id}",
                )
            with r_col2:
                reaction_opts = ["好笑", "一般", "不好笑"]
                r_idx = reaction_opts.index(joke.human_reaction) \
                        if joke.human_reaction in reaction_opts else 0
                reaction = st.radio(
                    "反应",
                    options=reaction_opts,
                    index=r_idx,
                    horizontal=True,
                    key=f"reaction_{joke.id}",
                )
            if st.button("提交标注", key=f"submit_{joke.id}"):
                try:
                    update_human_rating(joke.id, rating, reaction)
                    st.success("标注已保存 ✓")
                    st.rerun()
                except Exception as exc:
                    st.error(f"提交失败：{exc}")


# ─────────────────────────────────────────
# 页面 3 — 统计
# ─────────────────────────────────────────
def _page_stats():
    st.markdown("""
    <div class="page-header">
      <h1>数据统计</h1>
      <p>生成质量趋势与各类型表现分析</p>
    </div>""", unsafe_allow_html=True)

    stats = get_stats()
    by_type      = stats.get("by_type", [])
    recent_scores = stats.get("recent_scores", [])

    # ── 汇总卡片
    total_count = sum(r["count"] for r in by_type)
    avg_all     = (sum((r["avg_score"] or 0) * r["count"] for r in by_type) / total_count
                   if total_count else 0)
    rated_count = sum(1 for r in recent_scores if r["score"] and r["score"] > 0)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"""<div class="stat-card">
          <div class="stat-num">{total_count}</div>
          <div class="stat-lbl">总生成数量</div>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="stat-card">
          <div class="stat-num" style="color:#7c5cfc">{avg_all:.2f}</div>
          <div class="stat-lbl">全局平均分</div>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown(f"""<div class="stat-card">
          <div class="stat-num" style="color:#34d399">{rated_count}</div>
          <div class="stat-lbl">近100条有效评分</div>
        </div>""", unsafe_allow_html=True)

    st.markdown('<div style="height:1.5rem"></div>', unsafe_allow_html=True)

    if not by_type:
        st.markdown("""
        <div class="empty-state">
          <div class="empty-icon">📊</div>
          <h3>暂无统计数据</h3>
          <p>先去生成一些内容吧！</p>
        </div>""", unsafe_allow_html=True)
        return

    count_data = {
        CONTENT_TYPE_LABELS[ContentType(r["type"])]: r["count"]
        for r in by_type
    }
    avg_data = {
        CONTENT_TYPE_LABELS[ContentType(r["type"])]: round(float(r["avg_score"] or 0), 2)
        for r in by_type
    }

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**各类型数量**")
        st.bar_chart(count_data, height=220)
    with col_b:
        st.markdown("**各类型平均分**")
        st.bar_chart(avg_data, height=220)

    if recent_scores:
        st.markdown("**最近 100 条分数趋势**")
        trend = {
            r["created_at"]: float(r["score"] or 0)
            for r in reversed(recent_scores)
        }
        st.line_chart(trend, height=200)


def _page_persona():
    st.markdown("""
    <div class="page-header">
      <h1>Persona 管理</h1>
      <p>查看预设角色，或创建你自己的说话风格</p>
    </div>""", unsafe_allow_html=True)

    personas = get_personas()
    preset = [p for p in personas if p.is_preset]
    custom = [p for p in personas if not p.is_preset]

    for group_label, group in [("预设角色", preset), ("自定义角色", custom)]:
        if not group:
            continue
        st.markdown(f"**{group_label}**")
        cols = st.columns(min(len(group), 3))
        for i, p in enumerate(group):
            with cols[i % 3]:
                st.markdown(f"""
                <div class="joke-card">
                  <div style="font-size:16px;font-weight:700;color:var(--text);margin-bottom:4px">{p.name}</div>
                  <div style="font-size:12px;color:var(--muted);margin-bottom:8px">{p.description}</div>
                  <div style="font-size:12px;color:var(--text);line-height:1.6">
                    {p.style_prompt[:80]}{'…' if len(p.style_prompt) > 80 else ''}
                  </div>
                </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 创建自定义角色")
    with st.form("create_persona_form"):
        p_name = st.text_input("角色名称", placeholder="例：厌世文青")
        p_desc = st.text_input("一句话描述", placeholder="例：28岁，对一切都有意见")
        p_style = st.text_area("风格 Prompt", placeholder="你是……用2-5句话描述说话风格", height=120)
        submitted = st.form_submit_button("创建角色", use_container_width=True)

    if submitted:
        if not p_name.strip() or not p_style.strip():
            st.error("角色名称和风格 Prompt 不能为空")
        else:
            from contract import Persona as PersonaModel
            try:
                new_id = save_persona(PersonaModel(
                    id=None, name=p_name.strip(), description=p_desc.strip(),
                    style_prompt=p_style.strip(), is_preset=False,
                ))
                st.success(f"角色「{p_name}」已创建（ID={new_id}）")
                st.rerun()
            except Exception as exc:
                st.error(f"创建失败：{exc}")


def _page_calibration():
    st.markdown("""
    <div class="page-header">
      <h1>LLM Judge 校准报告</h1>
      <p>分析 AI 评分与人工评分的一致性</p>
    </div>""", unsafe_allow_html=True)

    type_opts = ["全部"] + list(ContentType)
    ct_filter = st.selectbox(
        "按内容类型筛选",
        options=type_opts,
        format_func=lambda v: "🔍 全类型合并" if v == "全部"
        else f"{CONTENT_ICONS[v]} {CONTENT_TYPE_LABELS[v]}",
    )

    if st.button("生成校准报告"):
        ct_val = ct_filter.value if isinstance(ct_filter, ContentType) else None
        try:
            with st.spinner("计算中……"):
                report = compute_calibration(content_type=ct_val)
            st.markdown(format_report_text(report))

            jokes = get_jokes(
                content_type=ct_filter if isinstance(ct_filter, ContentType) else None,
                limit=500,
            )
            paired = [
                {"LLM 评分": j.score.weighted_total, "人工评分": float(j.human_rating)}
                for j in jokes if j.score and j.human_rating
            ]
            if len(paired) >= 3:
                import pandas as pd

                st.markdown("**评分散点分布**")
                st.scatter_chart(pd.DataFrame(paired), x="LLM 评分", y="人工评分", height=300)
        except ValueError as ve:
            st.warning(str(ve))
        except Exception as exc:
            st.error(f"校准计算失败：{exc}")


def _page_monitor():
    from monitor import compute_diversity, detect_reward_hacking
    from strategy import get_type_performance_summary

    st.markdown("""
    <div class="page-header">
      <h1>监控中心</h1>
      <p>生成质量、多样性、成本与 Reward Hacking 实时检测</p>
    </div>""", unsafe_allow_html=True)

    if st.button("🔄  刷新数据"):
        st.rerun()

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
            from db import get_cost_stats

            costs = get_cost_stats(days=7)
            total_tok = costs["total_tokens"]
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

    st.markdown("**UCB1 内容策略**")
    try:
        summary = get_type_performance_summary()
        for item in summary:
            label = item["label"]
            plays = item["plays"]
            avg = item["avg_score"]
            ucb1 = item["ucb1_value"]
            rec = item["recommended"]
            bar_w = 100 if ucb1 == float("inf") else min(int(ucb1 / 2 * 100), 100)
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
                {plays}次 · 均分{avg:.1f} · UCB1={"∞" if ucb1 == float("inf") else f"{ucb1:.3f}"}
              </div>
            </div>""", unsafe_allow_html=True)
    except Exception as exc:
        st.info(f"暂无 UCB1 数据：{exc}")

    st.markdown("---")
    with st.expander("🧬 Prompt 进化状态", expanded=False):
        from evolution import _parse_genes, run_evolution
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

    st.markdown("---")
    with st.expander("📚 知识库", expanded=False):
        from db import get_knowledge, get_last_strategist_joke_id
        from strategist import incremental_review

        knowledge_type_labels = {
            None: "全部",
            "success_pattern": "成功规律",
            "failure_pattern": "失败规律",
            "humor_rule": "幽默规律",
            "gene": "新基因",
            "insight": "洞察",
        }
        knowledge_type = st.selectbox(
            "知识类型",
            options=list(knowledge_type_labels.keys()),
            format_func=lambda v: knowledge_type_labels[v],
            key="knowledge_type_filter",
        )

        col_k1, col_k2 = st.columns([1, 2])
        with col_k1:
            if st.button("🔬 立即复盘", key="btn_incremental_review", use_container_width=True):
                try:
                    since_id = get_last_strategist_joke_id()
                    with st.spinner("战略师正在复盘最近数据……"):
                        result = incremental_review(since_id)
                    if result.get("skipped"):
                        st.info(f"本次未触发复盘：{result.get('reason', '条件未满足')}")
                    else:
                        st.success(
                            f"复盘完成，处理 {result['processed_count']} 条，"
                            f"新增 {len(result.get('new_genes', []))} 个基因。"
                        )
                        if result.get("insight"):
                            st.caption(result["insight"])
                        st.rerun()
                except Exception as exc:
                    st.error(f"复盘失败：{exc}")
        with col_k2:
            st.caption("每满 50 条新笑话会自动触发一次增量复盘。这里可以手动对最近未复盘数据立即分析。")

        entries = get_knowledge(entry_type=knowledge_type, limit=50)
        if not entries:
            st.info("知识库还没有可展示内容。")
        else:
            for entry in entries:
                type_label = knowledge_type_labels.get(entry["entry_type"], entry["entry_type"])
                content_type = entry.get("content_type")
                content_label = CONTENT_TYPE_LABELS.get(ContentType(content_type), "跨类型") if content_type else "跨类型"
                source_ids = entry.get("source_joke_ids") or []
                source_text = f"来源 ID：{', '.join(str(i) for i in source_ids[:8])}" if source_ids else "来源 ID：无"
                st.markdown(f"""
                <div class="joke-card" style="margin-bottom:8px">
                  <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;margin-bottom:8px">
                    <div>
                      <span class="badge badge-type">{type_label}</span>
                      <span style="font-size:12px;color:var(--muted);margin-left:8px">{content_label}</span>
                    </div>
                    <div style="font-size:12px;color:var(--muted)">
                      相关度 {float(entry.get("relevance_score", 0.0)):.2f} · 使用 {int(entry.get("used_count", 0) or 0)} 次
                    </div>
                  </div>
                  <div style="font-size:14px;color:var(--text);line-height:1.75">{entry['content']}</div>
                  <div style="font-size:11px;color:var(--muted);margin-top:8px">{source_text} · {entry['created_at']}</div>
                </div>""", unsafe_allow_html=True)

    st.markdown("---")
    with st.expander("📰 项目日报", expanded=False):
        from db import get_daily_reports
        from strategist import generate_daily_report

        reports = get_daily_reports(limit=7)

        if st.button("📝 立即生成今日日报", key="btn_daily_report", use_container_width=True):
            try:
                with st.spinner("正在生成今日日报……"):
                    generate_daily_report()
                st.success("今日日报已生成。")
                st.rerun()
            except Exception as exc:
                st.error(f"日报生成失败：{exc}")

        if not reports:
            st.info("还没有项目日报。")
        else:
            latest = reports[0]
            stat_cols = st.columns(4)
            stat_cols[0].metric("日期", latest["report_date"])
            stat_cols[1].metric("生成数", int(latest["total_generated"]))
            stat_cols[2].metric("平均分", f"{float(latest['avg_score'] or 0):.2f}")
            stat_cols[3].metric("知识增量", int(latest["new_patterns"]))

            for report in reports:
                title = f"{report['report_date']} · {int(report['total_generated'])} 条 · 均分 {float(report['avg_score'] or 0):.2f}"
                with st.expander(title, expanded=(report is latest)):
                    st.caption(
                        f"新增知识 {int(report['new_patterns'])} 条 | "
                        f"日报生成于 {report['created_at']}"
                    )
                    st.markdown(report["report_md"])


# ─────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────
def main():
    _init_state()

    with st.sidebar:
        page = _sidebar_nav()

    if "生成" in page:
        _page_generate()
    elif "历史" in page:
        _page_history()
    elif "Persona" in page:
        _page_persona()
    elif "校准" in page:
        _page_calibration()
    elif "监控" in page:
        _page_monitor()
    else:
        _page_stats()


if __name__ == "__main__":
    main()
