# HumorRL Stand-up V2 与 RL 目标对齐说明

## 一、结论

**目标没变。**

HumorRL 的核心仍然不是“写完一篇 stand-up 就结束”，而是：

- 通过持续生成
- 持续评估
- 持续修订
- 持续沉淀经验
- 持续改进生成策略

最终形成一个**越写越好、越评越准、越跑越有壁垒**的幽默系统。

所以：

- `STANDUP_V2_PLAN.md` 解决的是“单篇长稿工作流不够强”的问题
- 本文解决的是“如何保证 v2 仍然是 RL 系统，而不是普通多步骤生成器”的问题

一句话说：

**v2 不是替代 RL，而是把 RL 的“单次 episode 质量”做强，同时把每次 episode 变成可训练资产。**

---

## 二、Claude 的提醒哪里是对的

Claude 的核心提醒是成立的：

如果 `v2` 只做成下面这样：

- persona
- planning
- writing
- judge
- strategist
- rewrite

然后产出一篇“更好的稿子”，但不把过程中的信号写回长期系统，

那它确实更像：

**长稿生产工作流**

而不是：

**强化学习式内容系统**

这个判断是对的。

---

## 三、真正不能变的目标

HumorRL 的真正目标不是：

- 多做一个 multi-agent stand-up demo
- 多写几篇更像脱口秀的稿子

而是：

**构建一个可持续积累幽默生成策略的系统。**

它的长期壁垒应该来自 4 件事：

1. `Judge` 越来越懂“什么是真正有效的幽默”
2. `Writer` 越来越知道“哪些策略更容易产出高分内容”
3. `Strategist` 越来越会把失败经验和成功经验转成规则
4. 系统能把这些经验沉淀成可复用、可训练、可回放的数据资产

所以 `v2` 必须回答：

**每跑完一篇稿子，到底给系统留下了什么？**

---

## 四、v2 在 RL 体系里的正确位置

`v2` 最合适的定位不是“最终训练系统”，而是：

**更高质量的 episode generator**

也就是：

- 它负责把单次长稿生成、评估、修订做得更强
- 然后把这一整次过程输出成高质量训练资产

所以应该把整个系统拆成两层：

### 第一层：Episode 层

围绕一篇 stand-up 做：

- persona ingestion
- planning
- drafting
- judging
- strategist revision
- targeted rewrite

这正是 `STANDUP_V2_PLAN.md` 重点解决的。

### 第二层：Learning 层

跨 episode 积累：

- 什么 planning 容易成功
- 什么 premise 更容易工作
- 什么 rewrite 有效
- 什么 judge 误判
- 什么 strategist critique 真的有用

这一层才是 HumorRL 真正的“越跑越强”部分。

---

## 五、v2 要如何重新接回 RL

## 1. 把 Blackboard 当成“状态空间”

`STANDUP_V2_PLAN.md` 里的 blackboard，不该只是协作白板。

在 RL 视角下，它更像：

- 当前 episode 的 `state`

例如：

- `persona_card_public`
- `audience_contract`
- `premise_sheet`
- `beat_outline`
- `material_bank`
- `judge_rubric`
- `revision_queue`

这些就是 stand-up 生成环境的状态描述。

---

## 2. 把每一次改写当成“动作”

在长稿场景里，动作不一定是 token-level 生成。

更合适的 action 粒度是：

- 选哪个 premise
- 选哪个 beat 路径
- 先修哪类问题
- 用哪种 rewrite strategy
- 是补现实性，还是补 escalation，还是补 closer

所以在 `v2` 里，动作空间可以分两层：

### A. 宏动作

- premise selection
- beat ordering
- closer strategy selection

### B. 微动作

- 选择哪条 `revision_task`
- 对哪一段做 targeted rewrite
- 是否采纳当前修改

---

## 3. 把 Judge + Strategist 输出变成“奖励信号”

单纯的 `set_score` 不够。

长稿 RL 更适合多维奖励。

建议把奖励拆成：

- `premise_reward`
- `thread_reward`
- `escalation_reward`
- `persona_reward`
- `audience_reward`
- `reality_reward`
- `closer_reward`

再组合成：

- `total_reward`
- `improvement_delta`

### 关键点

奖励不只来自结果，还来自变化：

- 初稿分数
- 改写后分数
- weakest 是否改善
- persona 是否掉了
- closer 是否更强了

也就是说，真正的 reward 应该包含：

**“这一刀改完之后，系统到底有没有变得更好。”**

---

## 六、v2 必须新增的训练资产

如果想让 `v2` 仍然是 RL 系统，就必须把每次 episode 导出成可以训练的结构化数据。

至少需要 5 类资产。

## 1. `planning_episodes`

记录：

- persona
- topic
- planning artifacts
- 初稿结果
- 最终结果

用途：

- 学什么 planning 更容易成功

## 2. `draft_judgments`

记录：

- draft text
- judge rubric
- paragraph evidence
- critique

用途：

- 训练 Judge
- 校准 Judge
- 分析误判模式

## 3. `revision_episodes`

记录：

- 某个 revision task
- task 前文本
- task 后文本
- score delta
- persona delta
- accepted / rejected

用途：

- 学什么改写有效
- 学什么改写会伤稿

这类数据最像“策略更新样本”。

## 4. `material_failures`

记录：

- 当前失败是 `material_issue` 还是 `writing_issue`
- 如果是素材问题，问题具体在哪

用途：

- 把“模型不会写”和“素材不够硬”分开

## 5. `critique_quality_records`

记录：

- Judge 的 critique
- Strategist 的 critique
- 后续改写是否验证了它是对的

用途：

- 建立 Chumor 风格的 explanation quality 系统

---

## 七、Chumor 2.0 在 RL 体系里的正确位置

Chumor 2.0 最大的价值，不是给 Writer 提供段子内容。

而是给 `Judge` 和 `Strategist` 提供：

- 什么叫好解释
- 什么叫坏解释
- 什么叫表面看起来在分析，实际上没解释到位

所以在 HumorRL 里，Chumor 2.0 应该接到：

### 1. Judge explanation benchmark

衡量：

- 这个批评是否具体
- 是否说到机制
- 是否能被后续修改验证

### 2. Strategist critique benchmark

衡量：

- 这个 revision brief 是否真的可执行
- 还是只是“增强幽默感”式废话

### 3. 幽默机制标签体系

Chumor 2.0 里的幽默类型分类，不该只停留在参考。

建议把它转成 HumorRL 的机制标签层，例如：

- pun / homophonic
- contextual
- situational
- glyph-based
- cross-lingual

同时结合 stand-up 需要的类型再扩充：

- self-deprecation
- status shift
- callback
- persona clash
- escalation absurdity
- observational reveal

这些标签不一定直接决定生成，但会帮助：

- Judge 更清楚这段在干什么
- Strategist 更清楚怎么修

---

## 八、OpenMic 对 RL 最值得借的地方

OpenMic 里对我们最值钱的，不只是 blackboard。

还有这一点：

**把“检索质量”和“写作质量”分开评估。**

这对 RL 非常关键。

因为如果一篇稿子失败了，系统要知道：

1. 是 premise 本身不硬
2. 是素材/details 不真
3. 还是 Writer 把好 premise 写散了

如果这三者不分开，学习信号就会混乱。

所以 `v2` 里建议明确写入两个字段：

- `material_issue`
- `writing_issue`

并且每轮都尝试判定：

- 当前失败更偏哪一类

这一步对长期训练价值极高。

---

## 九、v2 之后，系统应该变成三层闭环

## 第一层：单篇稿件闭环

这是 `STANDUP_V2_PLAN.md` 解决的：

- planning
- writing
- judging
- strategist
- rewrite

## 第二层：跨稿件学习闭环

这是 RL 核心：

- 统计哪些 premise 成功率高
- 哪种 closer strategy 更有效
- 哪种 rewrite action 经常涨分
- 哪种 critique 最有预测力

## 第三层：长期记忆闭环

写回：

- `writer_lesson`
- `judge_lesson`
- `generation_directive`
- `judge_directive`
- `material heuristics`

这样系统才不是“这一篇修完就结束”，而是把这篇的经验反哺后续所有内容。

---

## 十、v2 需要新增的显式字段

为了让 `v2` 真正服务 RL，建议从一开始就把这些字段定义好。

### 在 blackboard 里

- `material_issue`
- `writing_issue`
- `humor_mechanism_tags`
- `closer_strategy`
- `callback_seeds`

### 在 judge 输出里

- `rubric_scores`
- `top_failure_modes`
- `explanation_quality_hint`

### 在 strategist 输出里

- `revision_queue`
- `rubric_update`
- `writer_guidance_update`
- `learning_takeaway`

### 在 revision log 里

- `task_type`
- `before_score`
- `after_score`
- `before_persona`
- `after_persona`
- `accepted`
- `failure_reason_if_rejected`

---

## 十一、推荐的 v2.1 版本目标

为了不让工程量失控，建议把“对齐 RL 目标”的第一步定义成 `v2.1`。

### v2.1 不做的事

- 不做真正的 policy gradient
- 不做大规模 online RL
- 不做重型 RAG
- 不做多模态笑声监督

### v2.1 要做的事

1. `blackboard schema`
2. `revision_log` 升级成训练资产格式
3. `material_issue vs writing_issue` 判定
4. `judge rubric` 多维记录
5. `strategist` 输出 `learning_takeaway`
6. 长稿实验数据可批量导出

也就是说：

**先让 v2 变成“能稳定产出训练资产”的系统。**

---

## 十二、最终判断

Claude 的提醒是对的：

如果只做 `STANDUP_V2_PLAN.md`，而不补训练资产层，

那它会更像：

**更强的 stand-up 生产工作流**

而不是：

**更强的 RL 系统**

但这不意味着方向错了。

正确理解应该是：

### `STANDUP_V2_PLAN.md`

解决：

- 单篇 longform stand-up 的生成、评审、修订机制

### `STANDUP_V2_RL_ALIGNMENT.md`

解决：

- 如何让这些 episode 不白跑
- 如何把它们转成长期学习资产

所以目标没有变。

我们真正要做的是：

**让 stand-up v2 工作流，成为 HumorRL 强化学习体系里的高质量 episode 生产器。**
