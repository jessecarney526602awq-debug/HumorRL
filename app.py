"""
HumorRL — Streamlit UI
视觉设计对应 Figma Make: DFXQR5oqREgG7rBHX59jFr
页面：生成 / 历史记录 / 统计
"""

import streamlit as st

import humor_engine
from contract import CONTENT_TYPE_LABELS, ContentType, GenerationRequest
from db import get_jokes, get_personas, get_stats, init_db, save_joke, update_human_rating

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
        ["🎲  生成", "📋  历史记录", "📊  统计"],
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
    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("💾  保存这条", disabled=st.session_state.generated_saved, use_container_width=True):
            try:
                saved_id = save_joke(joke)
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
                    st.rerun()
                except Exception as exc:
                    st.error(f"生成失败：{exc}")


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
    else:
        _page_stats()


if __name__ == "__main__":
    main()
