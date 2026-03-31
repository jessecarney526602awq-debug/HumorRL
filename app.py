import streamlit as st

import humor_engine
from contract import CONTENT_TYPE_LABELS, ContentType, GenerationRequest
from db import get_jokes, get_personas, get_stats, init_db, save_joke, update_human_rating


st.set_page_config(page_title="HumorRL", layout="wide")
init_db()


def _init_session_state() -> None:
    if "generated_joke" not in st.session_state:
        st.session_state.generated_joke = None
    if "generated_saved" not in st.session_state:
        st.session_state.generated_saved = False


def _content_type_label(content_type: ContentType) -> str:
    return CONTENT_TYPE_LABELS[content_type]


def _render_score_metrics(score) -> None:
    metric_items = [
        ("结构完整性", score.structure),
        ("意外性", score.surprise),
        ("共鸣度", score.relatability),
        ("语言质量", score.language),
        ("创意度", score.creativity),
        ("安全性", score.safety),
    ]
    for start in (0, 3):
        cols = st.columns(3)
        for col, (label, value) in zip(cols, metric_items[start:start + 3]):
            with col:
                st.metric(label, f"{value:.1f}")


def _page_generate() -> None:
    st.title("生成")
    personas = get_personas()

    with st.sidebar:
        st.subheader("生成参数")
        content_type = st.selectbox(
            "内容类型",
            options=list(ContentType),
            format_func=_content_type_label,
            index=0,
        )
        use_persona = st.toggle("Persona", value=False)
        selected_persona = None
        if use_persona and personas:
            selected_persona = st.selectbox(
                "选择 persona",
                options=personas,
                format_func=lambda p: f"{p.name}｜{p.description}",
            )
        topic = st.text_input("主题词", value="", placeholder="留空则随机主题")
        should_generate = st.button("生成", use_container_width=True)

    if should_generate:
        req = GenerationRequest(
            content_type=content_type,
            persona=selected_persona,
            topic=topic.strip() or None,
        )
        try:
            with st.spinner("生成中..."):
                st.session_state.generated_joke = humor_engine.generate_and_pick_best(req)
                st.session_state.generated_saved = False
        except Exception as exc:
            st.error(f"生成失败：{exc}")

    joke = st.session_state.generated_joke
    if not joke:
        st.info("点击左侧“生成”按钮，先来一条新段子。")
        return

    st.text_area("段子正文", value=joke.text, height=260, disabled=True)

    if joke.score:
        _render_score_metrics(joke.score)
        st.markdown(
            f"<h2 style='margin-top: 1rem;'>总分：{joke.score.weighted_total:.2f}</h2>",
            unsafe_allow_html=True,
        )
        st.caption(joke.score.reasoning)

    save_disabled = st.session_state.generated_saved
    if st.button("保存这条", disabled=save_disabled):
        try:
            saved_id = save_joke(joke)
            st.session_state.generated_saved = True
            st.success(f"已保存，ID = {saved_id}")
        except Exception as exc:
            st.error(f"保存失败：{exc}")


def _page_history() -> None:
    st.title("历史记录")

    filter_cols = st.columns(3)
    with filter_cols[0]:
        content_type_filter = st.selectbox(
            "类型",
            options=["全部"] + list(ContentType),
            format_func=lambda value: "全部" if value == "全部" else _content_type_label(value),
        )
    with filter_cols[1]:
        min_score = st.slider("最低分", min_value=0, max_value=10, value=0)
    with filter_cols[2]:
        unrated_only = st.checkbox("仅看未标注", value=False)

    jokes = get_jokes(
        content_type=content_type_filter if isinstance(content_type_filter, ContentType) else None,
        min_score=float(min_score) if min_score > 0 else None,
        unrated_only=unrated_only,
        limit=100,
    )

    if not jokes:
        st.info("当前筛选条件下还没有记录。")
        return

    for joke in jokes:
        total = joke.score.weighted_total if joke.score else 0.0
        title = f"{joke.text[:30]}{'...' if len(joke.text) > 30 else ''} | 总分 {total:.2f}"
        with st.expander(title):
            st.caption(
                f"{_content_type_label(joke.content_type)} | {joke.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            st.text_area(
                f"全文 #{joke.id}",
                value=joke.text,
                height=220,
                disabled=True,
                key=f"text_{joke.id}",
            )

            if joke.score:
                _render_score_metrics(joke.score)
                st.caption(f"评分理由：{joke.score.reasoning}")

            st.divider()
            st.subheader("人工评分")
            rating = st.slider("评分", 1, 10, value=joke.human_rating or 6, key=f"rating_{joke.id}")
            reaction_options = ["好笑", "一般", "不好笑"]
            reaction_index = reaction_options.index(joke.human_reaction) if joke.human_reaction in reaction_options else 0
            reaction = st.radio(
                "反应",
                options=reaction_options,
                index=reaction_index,
                horizontal=True,
                key=f"reaction_{joke.id}",
            )
            if st.button("提交", key=f"submit_{joke.id}"):
                try:
                    update_human_rating(joke.id, rating, reaction)
                    st.success("人工评分已提交")
                    st.rerun()
                except Exception as exc:
                    st.error(f"提交失败：{exc}")


def _page_stats() -> None:
    st.title("统计")
    stats = get_stats()

    by_type = stats.get("by_type", [])
    recent_scores = stats.get("recent_scores", [])

    count_chart_data = [
        {"类型": CONTENT_TYPE_LABELS[ContentType(item["type"])], "数量": item["count"]}
        for item in by_type
    ]
    avg_chart_data = [
        {
            "类型": CONTENT_TYPE_LABELS[ContentType(item["type"])],
            "平均分": round(float(item["avg_score"] or 0), 2),
        }
        for item in by_type
    ]
    trend_chart_data = [
        {"时间": item["created_at"], "分数": float(item["score"] or 0)}
        for item in reversed(recent_scores)
    ]

    st.subheader("各类型数量")
    if count_chart_data:
        st.bar_chart(count_chart_data, x="类型", y="数量")
    else:
        st.info("还没有可统计的数据。")

    st.subheader("各类型平均分")
    if avg_chart_data:
        st.bar_chart(avg_chart_data, x="类型", y="平均分")
    else:
        st.info("还没有可统计的数据。")

    st.subheader("最近100条分数趋势")
    if trend_chart_data:
        st.line_chart(trend_chart_data, x="时间", y="分数")
    else:
        st.info("最近还没有带评分的记录。")


def main() -> None:
    _init_session_state()
    page = st.sidebar.radio("页面", ["生成", "历史记录", "统计"], index=0)

    if page == "生成":
        _page_generate()
    elif page == "历史记录":
        _page_history()
    else:
        _page_stats()


if __name__ == "__main__":
    main()
