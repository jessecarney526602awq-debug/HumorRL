# OpenClaw 任务单 — HumorRL P2 前端

> 项目路径：/Users/milo/Documents/Claude/HumorRL/
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> 先读 CLAUDE.md 了解项目结构，再开始写代码。

## 前置条件

**等 Codex 的 PR 合并后再改 app.py**，因为你需要 import 他写的模块：
- `from rewriter import rewrite_until_good`
- `from calibration import compute_calibration, format_report_text`
- `from db import get_joke_by_id, get_rewrite_chain, save_persona`

## 你负责的文件

| 文件 | 操作 |
|------|------|
| `app.py` | 修改（6处改动，详见下方） |

**不要碰 `rewriter.py`、`calibration.py`、`db.py`，那是 Codex 的任务。**

---

## 改动 1：`_init_state()` 追加 session state key

在 `defaults` 字典中追加：
```python
"rewrite_source_id": None,
"rewrite_results": [],
"rewrite_in_progress": False,
```

---

## 改动 2：`_sidebar_nav()` 新增两个导航项

将 radio 的选项列表从 3 项改为 5 项：
```python
["🎲  生成", "📋  历史记录", "📊  统计", "🧑‍🎨  Persona", "🔬  校准报告"]
```

---

## 改动 3：`main()` 新增两个路由分支

```python
elif "Persona" in page:
    _page_persona()
elif "校准" in page:
    _page_calibration()
```

---

## 改动 4：`_page_generate()` — 保存回写 id + 新增改写按钮

**4a. 保存按钮回写 id**（在现有保存逻辑里加一行）：
```python
if st.button("💾  保存这条", ...):
    saved_id = save_joke(joke)
    st.session_state.generated_joke.id = saved_id  # ← 新增这行
    st.session_state.generated_saved = True
    st.success(f"已保存！ID = {saved_id}")
```

**4b. 操作按钮区从 2 列改为 3 列，新增改写按钮**：
```python
col1, col2, col3 = st.columns([1, 1, 1])
# col1: 保存（现有）
# col2: 再来一条（现有）
# col3: 改写（新增）
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
            try:
                source = get_joke_by_id(st.session_state.generated_joke.id)
                results = rewrite_until_good(source, max_rounds=3)
                st.session_state.rewrite_results = results
            except Exception as exc:
                st.error(f"改写失败：{exc}")

    if not st.session_state.generated_saved and rewrite_ok:
        st.caption("💡 先保存后再改写")
    elif joke.score and score_val > 7.0:
        st.caption("✅ 分数够高，无需改写")
    elif joke.score and score_val < 4.0:
        st.caption("❌ 分数过低，改写效果有限")
```

**4c. 在按钮区下方展示改写结果**：
```python
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
```

---

## 改动 5：`_page_history()` — 低分内容加改写入口

在每个 expander 内，`if joke.score:` 块之后、`st.divider()` 之前插入：

```python
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
```

---

## 改动 6：新增 `_page_persona()` 函数

```python
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
        p_name  = st.text_input("角色名称", placeholder="例：厌世文青")
        p_desc  = st.text_input("一句话描述", placeholder="例：28岁，对一切都有意见")
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
```

---

## 改动 7：新增 `_page_calibration()` 函数

```python
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
            # 散点图
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
```

---

## 完成后

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add app.py
git commit -m "feat(P2): persona管理 + 改写UI + 校准报告页"
git push origin main
```
