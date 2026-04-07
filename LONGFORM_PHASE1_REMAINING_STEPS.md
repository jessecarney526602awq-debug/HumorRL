# HumorRL 长稿 Phase 1 剩余 4 步施工文档

## 一、这份文档的目的

这不是理念文档，而是接下来真正要落代码的施工说明。

当前长稿线已经完成：

1. stand-up 文稿解析  
2. set-level Judge  
3. 粗拆段  
4. weakest segment 局部改写 sample 闭环

所以现在剩下的工作，不再是“这个方向对不对”，而是：

**如何把现有 sample 能力，推进成一条可持续运行的长稿主循环。**

---

## 二、当前已完成状态

### 已有能力

- [data/standup_sets.json](/Users/milo/Documents/Claude/HumorRL/data/standup_sets.json)  
  已能保存整篇 stand-up 文稿和笑声/掌声标记位置

- [scripts/judge_standup_sets.py](/Users/milo/Documents/Claude/HumorRL/scripts/judge_standup_sets.py)  
  已能做 set-level Judge，输出：
  - `set_score`
  - `structure_issue`
  - `strongest_segment`
  - `weakest_segment`
  - `predicted_laughs`

- [scripts/segment_standup_sets.py](/Users/milo/Documents/Claude/HumorRL/scripts/segment_standup_sets.py)  
  已能把整篇稿子粗拆成 5-7 个结构段

- [scripts/rewrite_standup_set.py](/Users/milo/Documents/Claude/HumorRL/scripts/rewrite_standup_set.py)  
  已能做最小闭环：
  - 找 weakest segment
  - 只改 weakest segment
  - 重跑整篇 Judge
  - 未提升则拒绝改写版本

### 当前还缺什么

真正缺的不是局部能力，而是：

- 没有“长稿生成器”
- 没有“生成 → Judge → 改写”的主闭环
- 没有“批量实测和停止条件验证”
- 没有“正式版长稿版本落库”

---

## 三、Phase 1 剩余 4 步

## Step 1：实现长稿生成器

### 目标

新增一个**文本型 stand-up 初稿生成器**，能稳定产出一篇完整 stand-up 稿子。

### 为什么这是第一步

现在局部改写链已经能跑，但前提是假设“整篇初稿已经存在”。

没有长稿生成器，就只能拿现成文稿做离线实验，没法进入真正的主循环。

### 要做什么

新增：

- `prompts/generate/standup_set.txt`
- `scripts/generate_standup_set.py`

输入建议：

- `persona`
- `topic`
- `target_audience`
- `length_minutes` 或 `paragraph_target`
- `tone`
- `generation_directive`

输出要求：

- 一篇完整的 stand-up 稿子
- 结构上至少包含：
  - `opening`
  - `premise`
  - `build`
  - `至少 2 个有效笑点`
  - `closer`

### 输出格式契约（必须显式遵守）

这一条是下游所有脚本的隐性前提，现在提升为显式约定：

- 生成器必须按 `\n\n` 输出段落
- 每段都是一个完整语义单元
- 段内不要再嵌套随意换行

原因：

- [scripts/rewrite_standup_set.py](/Users/milo/Documents/Claude/HumorRL/scripts/rewrite_standup_set.py) 的局部改写是按 `paragraph index` 做 splice
- `judge -> segment -> rewrite` 整条链路都依赖 `item["paragraphs"]` 是稳定的字符串数组

所以生成后必须立刻做这一步：

```python
text = generated_text.strip()
paragraphs = [p.strip() for p in text.split("\\n\\n") if p.strip()]
```

然后组装成合法 item dict，再丢给下游：

```python
{
  "id": "...",
  "performer": "...",
  "title": "...",
  "full_text": text,
  "clean_text": text,
  "paragraphs": paragraphs,
  "markers": [],
  "reaction_summary": {"laugh_count": 0, "big_laugh_count": 0, "applause_count": 0},
  "source_type": "generated_standup_set"
}
```

如果不先完成这一步，后面的 Judge / segment / rewrite 链都会失效。

### Phase 1 约束

- 只做**文本型 stand-up**
- 不追求强表演依赖
- 优先适配：
  - 鸟鸟
  - 孙书恒
  - 呼兰
  这类文本更强、结构更稳的方向

### 验收标准

人工抽看 10 篇生成稿，至少满足：

- `成稿率 >= 50%`
- 不少于 `70%` 的稿子有明确开场和结尾
- 不少于 `50%` 的稿子有至少 2 个可识别的局部笑点

### 暂不做

- 不做强表演型 stand-up
- 不做相声化结构
- 不做 callback 精细控制

---

## Step 2：接成长稿主闭环

### 目标

把以下流程串成一个真实可运行的主循环：

`generate_set -> set_judge -> coarse_segment -> rewrite_weakest_segment -> set_judge_again`

### 要做什么

新增一个 orchestration 脚本或模块，例如：

- `scripts/run_longform_cycle.py`

它至少要负责：

1. 生成初稿  
2. 把初稿组装成合法 item dict  
2. 跑 set-level Judge  
3. 跑 coarse segmentation  
4. 选择 weakest segment  
5. 跑 1-3 轮局部改写  
6. 对每轮结果重新 Judge  
7. 保留最佳版本

### 推荐默认参数

- `max_iterations = 3`
- `improvement_threshold = 0.4`
- `stop_if_same_weakest_twice = true`

### 当前代码里的真实退出逻辑

当前 [scripts/rewrite_standup_set.py](/Users/milo/Documents/Claude/HumorRL/scripts/rewrite_standup_set.py) 的行为比理念文档更保守：

- 只要有一轮改写 `score_delta < 0.4`
- 就立刻退出，不会继续试下一轮

也就是说，目前最常见的退出路径会是：

`第一轮改写不达标 -> 直接停止`

这不是 bug，但做 Step 2 时必须明确知道：

- `stop_if_same_weakest_twice` 现在只是次级停止条件
- 真正最常触发的是“第一轮未达 improvement_threshold”

Phase 1 先保持这个保守逻辑，等小批量验证后再决定是否升级成：

- “第一轮不达标时，允许尝试下一个 weakest segment”

### 关键原则

- 默认**只改 weakest segment**
- 不整篇重写
- 如果 weakest segment 连续两轮不变，说明是骨架问题，应停止

### 验收标准

至少能稳定跑完：

- `1 篇主题 -> 1 个完整循环`
- 输出：
  - 初稿
  - 每轮评分
  - 每轮 weakest segment
  - 接受/拒绝原因
  - 最优版本

---

## Step 3：版本与结果落库（建议在小批量验证通过后再做）

### 目标

把长稿循环从“sample JSON 文件”升级成“系统资产”。

### 为什么重要

当前其实已经能用 JSON 先跑完整版本历史：

- [scripts/rewrite_standup_set.py](/Users/milo/Documents/Claude/HumorRL/scripts/rewrite_standup_set.py)

所以 Step 3 不是为了让 Phase 1 能跑，而是为了让 Phase 1 稳定沉淀。

如果不落库：

- Strategist 看不到长稿版本演化
- 无法统计哪种改写策略有效
- 无法回放某篇稿子的版本历史

### 要做什么

新增或扩展数据库结构，建议至少有两张表：

#### 1. `standup_sets`

保存整篇稿版本

建议字段：

- `id`
- `root_id`
- `parent_id`
- `title`
- `persona_id`
- `topic`
- `generation_directive`
- `version_no`
- `text`
- `set_score`
- `display_band`
- `structure_issue`
- `status` (`draft` / `accepted` / `rejected` / `best`)
- `created_at`

#### 2. `standup_segments`

保存结构段

建议字段：

- `id`
- `set_id`
- `segment_index`
- `role`
- `start_paragraph`
- `end_paragraph`
- `summary`
- `function`
- `rewrite_priority`

#### 3. 可选：`standup_rewrite_actions`

保存每轮改写动作

建议字段：

- `id`
- `set_id`
- `target_segment_index`
- `rewrite_note`
- `accepted`
- `score_delta`

### 实现要求

不是只加表，还必须同时更新正式 schema 和 CRUD：

- [db.py](/Users/milo/Documents/Claude/HumorRL/db.py) 里的 `init_db()`
- [db.py](/Users/milo/Documents/Claude/HumorRL/db.py) 里的 stand-up 相关 CRUD 封装

不要让长稿表变成“脚本私有 schema”。

### 验收标准

任意一篇长稿循环结束后，能从 DB 查询到：

- 初稿
- 所有迭代版本
- 每轮 weakest/strongest segment 信息
- 哪轮被接受，哪轮被拒绝
- 最终 best version

---

## Step 4：小批量实测（先跑 JSON 版）

### 目标

不是先长期自动跑，而是先做一轮小批量人工可检查的验证。

这一轮建议优先直接用 JSON 跑，不先绑 DB。

原因：

- 如果成稿率、提升率、停止条件有问题
- 先调生成器和主闭环会更便宜
- 不必提前锁死 DB schema

### 推荐规模

先跑：

- `5-10` 个主题
- 每个主题 `1` 篇初稿
- 每篇最多 `3` 轮改写

### 核心要回答的 5 个问题

1. 长稿生成器成稿率够不够  
2. weakest segment 改写后，整篇分数是否真的有提升  
3. 停止条件是否会过早或过晚  
4. 哪一类结构问题最常见
5. Judge 自己的重复性噪声有多大

### 建议输出

跑完后生成一个人工 review 用报告，至少包括：

- 总共跑了多少篇
- 成稿率
- 平均起始分
- 平均最佳分
- 平均提升幅度
- 多少篇在 1 轮后停
- 多少篇 3 轮都没有改善
- 最常见的 `structure_issue`
- 最常见的 weakest segment role
- 3-5 篇样本重复 Judge 两次后的 `set_score` 偏差

### 验收标准

至少满足其中 3 条：

- `成稿率 >= 50%`
- `平均最佳分 > 平均起始分`
- 至少 `30%` 的稿子经过局部改写后有可见提升
- 停止条件没有明显失控
- 能总结出 2-3 条稳定结构问题

额外硬性观察项：

- 如果同一篇稿子重复 Judge 两次，`set_score` 偏差经常 > `0.5`
- 那么 `improvement_threshold = 0.4` 暂时不可信
- 需要先收紧 Judge，再继续扩主循环

---

## 四、建议执行顺序

严格按下面顺序来，不要并行跳步：

1. **先做长稿生成器**
2. **再接主闭环 orchestration**
3. **先跑 JSON 版小批量验证**
4. **验证通过后，再做 DB 落库**

原因：

- 没有生成器，就没有主循环
- 没有主循环，成稿率和改写提升率无法验证
- 如果先上 DB，再发现生成器或循环设计要大改，会徒增迁移成本
- 当前 JSON 输出已经足够支撑 Phase 1 的小批量验证

---

## 五、Phase 1 的非目标

这几个东西很重要，但**现在不要做**：

1. 不做 punchline-level 自动抽取  
2. 不做 stand-up 全自动长期调度  
3. 不做表演型演员模拟优化  
4. 不做笑声强度精细标定  
5. 不做多 segment 联动改写  
6. 不做 callback 精修器  

这些都应该进 Phase 2。

---

## 六、当前风险

### 风险 1：长稿生成器本身成稿率可能不够

如果文本型 stand-up 初稿本身经常不成稿，后面的改写循环就会变成修烂稿。

### 风险 1.5：生成器输出如果不满足 item dict 契约，整条链会直接断

最容易被忽视的真实阻塞点不是“生成得差”，而是：

- 生成器输出没有稳定切成 `paragraphs`
- 没有组装成合法 item dict

这一步如果没写清楚，`run_longform_cycle.py` 根本接不上现有 Judge / segment / rewrite 链。

### 风险 2：局部改写可能只会做“局部润色”，无法解决骨架问题

所以必须保留：

- `连续两轮 weakest_segment 不变 -> 停止`

### 风险 3：set-level Judge 仍可能对长稿波动较大

所以小批量验证阶段，一定要看：

- 同类稿件评分是否稳定
- weakest segment 是否经常跳来跳去

### 风险 4：文本型 stand-up 和强表演型 stand-up 不应混在同一个 Phase 1 目标里

当前必须坚持：

- 先做文本强
- 再谈表演放大

---

## 七、希望 Claude Code 重点审的地方

请 Claude Code 不要泛泛总结，重点审以下 6 件事：

1. 这 4 步的顺序是否合理  
2. 长稿生成器的输入/输出设计是否够稳  
3. `paragraphs + item dict` 契约是否写得足够清楚  
4. 主闭环的停止条件是否合理  
5. DB 结构是否过早、过重，或者还缺关键字段  
6. 小批量验证的指标是否够判断 Phase 1 成败

---

## 八、一句话结论

现在的长稿线已经不是“有没有方向”，而是：

**还差 4 步，把 sample 能力升级成可运行的长稿生产闭环。**

这 4 步分别是：

1. 长稿生成器  
2. 主闭环 orchestration  
3. JSON 版小批量实测  
4. 验证通过后再做版本落库

如果这 4 步完成，HumorRL 的长稿 Phase 1 就算真正跑通。
