# HumorRL Stand-up V2 重构计划

## 一、结论

Stand-up `v2` 的重点不是“再加几个 agent”或者“再调一轮 prompt”，而是把现有的：

- persona
- planning
- writer
- judge
- strategist
- rewrite

从“串行文本调用”重构成一个**共享 blackboard 驱动的工作流**。

一句话说：

**v1 更像有多个角色在接力；v2 要变成多个角色围着同一份中间产物协作。**

---

## 二、为什么要做 v2

当前 stand-up `v1` 已经证明了几件事：

1. persona-first 长稿可以稳定生成 `6.5-7.0` 左右的初稿
2. Judge 已经能指出较明确的问题
3. Strategist 已经能输出比以前更具体的修订方向
4. targeted rewrite 比整段重写有效

但 `v1` 也暴露了稳定瓶颈：

1. `persona` 只是输入材料，不是流程级约束
2. `planning` 产物没有成为后续所有环节的统一依据
3. Judge 的评分、Strategist 的建议、Rewrite 的执行还没有真正共享同一套 typed artifacts
4. Rewrite 还是偏“改 weakest segment”，还不够像真正的 task-list 修订
5. 当前 critique 质量不稳定，偶尔仍会滑向泛泛点评、过度分析或空洞抽象
6. 长稿链路每轮都在“重新解释问题”，而不是围绕同一份中间状态持续推进

所以 `v2` 的目标不是“多做一点”，而是：

**让 stand-up 生成、评审、修订、复评真正形成一个共享状态的闭环。**

---

## 三、v2 的设计来源

### 1. 从 OpenMic 借的 5 件事

我们最值得吸收的不是“多智能体”四个字，而是这 5 个工程思想：

1. `blackboard`
2. `检索/写作分离评估`
3. `targeted rewrite`
4. `低温、强结构写作`
5. `performance DSL`

其中前 4 件适合直接进入 `v2`，第 5 件先做轻量保留，不作为第一阶段硬目标。

### 2. 从 Chumor 2.0 借的 2 件事

Chumor 2.0 对我们最值钱的不是内容本身，而是：

1. **Judge / Strategist 的 critique 必须是“解释到位”的**
2. **过度分析会伤害幽默判断**

所以 `v2` 里不能只追求“点评很多”，而要追求：

- 定位准确
- 机制明确
- 可执行
- 不胡编理由

---

## 四、v2 的核心原则

### 原则 1：后台人物是冰山，台上只露一角

人物主档是后台约束，不是台词素材库。

`v2` 的任何环节都不能默认把人物资料直接搬上台面。

### 原则 2：先有舞台 premise，再有故事

stand-up 优先级不是“我真实经历了什么”，而是：

- 这篇稿子在台上讲的到底是什么局面
- 观众为什么愿意继续听
- 它如何持续升级

### 原则 3：长稿优化必须从整段改写，升级为 task-list 局部修订

不再默认：

- 找 weakest segment
- 整段重写

而是优先：

- 找原子问题
- 生成 revision queue
- 一刀一刀修

### 原则 4：评分不只是总分，而是 stand-up rubric

`v2` 中，Judge 不再主要依赖一个 `set_score`。

它必须显式判断：

- premise 是否成立
- running thread 是否稳定
- escalation 是否在工作
- persona 是否统一
- audience readability 是否够
- closer 是否真正回收

### 原则 5：批评必须能指导下一刀修改

Judge 和 Strategist 的输出如果不能直接指导下一刀改写，就不算有效输出。

---

## 五、v2 角色设计

`v2` 不建议扩成 5 个角色。

当前最稳的结构是：

1. `Persona/Planning`
2. `Writer`
3. `Judge`
4. `Strategist / Revision Manager`
5. `Blackboard`（共享对象，不是角色）

### 为什么暂时不单独拆 AudienceAnalyzer

Audience 这层很重要，但目前不值得单独变成一个新角色。

更合适的做法是把它并入 `Planning`，产出一份明确的：

- `audience_contract`
- `audience_filters`
- `audience_confusion_risks`

等 `v2` 稳定后，如果 audience modeling 复杂度显著上升，再考虑拆角色。

---

## 六、v2 的 Blackboard 设计

每篇 stand-up 稿子，在 `v2` 里都应该有一份 blackboard。

它不是日志，而是这篇稿子的共享工作台。

### 建议的 typed artifacts

#### 1. `persona_card_public`

台上允许露出的那一角。

包含：

- one-line identity
- speaking object
- voice guardrails
- emotion surface
- observable contradictions

#### 2. `persona_iceberg_hidden`

后台约束。

包含：

- hidden biography
- private motivations
- should-not-say list
- audience filter list

#### 3. `audience_contract`

这篇稿子在台上是讲给谁听的。

包含：

- audience type
- familiarity assumptions
- taboo/confusion risks
- what must be translated into public language

#### 4. `premise_sheet`

整篇稿子的核心舞台合同。

包含：

- title hint
- theme angle
- central premise
- running thread
- narrative contract
- comedic engine
- closer goal
- callback seeds

#### 5. `material_bank`

素材与观察池。

包含：

- usable observations
- usable exaggerated situations
- composite characters
- valid details
- risky details
- realism checks

#### 6. `beat_outline`

结构推进图。

建议 5-8 个 beat：

- opening
- premise confirmation
- escalation 1
- escalation 2
- escalation 3
- optional callback
- closer

#### 7. `draft`

当前正文版本。

#### 8. `judge_rubric`

当前这一篇稿子的评分重点。

不是通用固定模板，而是：

- 本轮更该盯什么
- 哪类错误这轮必须压分
- 哪类优点不能被误伤

#### 9. `revision_queue`

当前待修问题列表。

每条任务都应该是原子化的。

#### 10. `revision_log`

记录每一刀修改：

- 改了什么
- 为什么
- 是否采纳
- 对分数/人设/结构有什么影响

---

## 七、v2 各角色职责

## 1. Persona/Planning

### 主要职责

- 把完整人物主档压缩成台前可用的 persona
- 建立 `audience_contract`
- 建立 `premise_sheet`
- 建立 `beat_outline`
- 把后台资料转成台前可用素材约束

### 相比 v1 的升级

不是只生成一个 planning JSON，而是生成：

- public persona
- hidden iceberg
- premise sheet
- beat outline
- audience filters
- complaint traps
- realism checks

### 核心要求

- 人设不上台面
- premise 必须可持续
- 先讲局面，不先讲观点
- 不要把稿子规划成 memoir

---

## 2. Writer

### 主要职责

根据 blackboard 写稿。

输入优先级：

1. `premise_sheet`
2. `beat_outline`
3. `persona_card_public`
4. `material_bank`
5. `audience_contract`

### Writer 在 v2 的新要求

- 低温生成
- 强结构写作
- 真实经历只做 15% 底色
- 优先写“舞台处境”
- 不能把 hidden iceberg 直接写出来

### Writer 不该做的事

- 不该替 Strategist 解决所有结构问题
- 不该把人物档案直接翻译成台词
- 不该用感慨和总结填结尾

---

## 3. Judge

### 主要职责

Judge 在 `v2` 要从“总编印象分”升级成 stand-up 专向 rubric。

### 建议的一级维度

1. `Premise Strength`
2. `Running Thread Integrity`
3. `Escalation / Density`
4. `Persona Fidelity`
5. `Audience Readability`
6. `Reality / Logic`
7. `Closer Quality`

### 输出层级

#### A. 总体层

- `set_score`
- `persona_consistency`
- `top_issues`

#### B. 证据层

- strongest paragraph / beat
- weakest paragraph / beat
- evidence-based reasons

#### C. 反应层

- predicted laughs
- applause candidates
- dead zones

#### D. critique layer

- 什么问题该扣分
- 什么优点不能虚伤

### 从 Chumor 2.0 借来的约束

Judge 的 critique 必须满足：

1. 说到具体位置
2. 说到具体机制
3. 说到为什么失效
4. 不能只是抽象褒贬
5. 不能通过“多说几句”伪装为分析

### Judge v2 的目标

不是“解释很多”，而是：

**把 stand-up 的失败方式说准。**

---

## 4. Strategist / Revision Manager

### 主要职责

Strategist 在 `v2` 中不再主要是评论员，而是：

**修订经理**

它负责：

1. 把 Judge 发现转成 `revision_queue`
2. 更新 `judge_rubric`
3. 更新 `writer_guidance`
4. 判定这是“素材问题”还是“写法问题”

### 它的输出必须是

- 小颗粒
- 可执行
- 可验证
- 能写回 blackboard

### revision task 的建议结构

每条 task 至少包含：

- `task_id`
- `priority`
- `issue_type`
- `target_paragraphs`
- `problem`
- `rewrite_goal`
- `acceptance_check`

### Strategist 不该再做的事

- 不该只写一段泛泛总结
- 不该只说“增强幽默感”
- 不该只说“人物更真实一点”

---

## 八、v2 的流程设计

## Step 1：Persona ingestion

输入：

- 人物 markdown / structured profile

输出到 blackboard：

- `persona_card_public`
- `persona_iceberg_hidden`
- `audience_contract`

## Step 2：Planning

输入：

- persona artifacts
- 主题
- 参考材料

输出到 blackboard：

- `premise_sheet`
- `beat_outline`
- `material_bank`

## Step 3：Draft writing

Writer 根据 planning artifacts 写出初稿。

输出：

- `draft_v1`

## Step 4：Judge v2

Judge 对初稿做 stand-up rubric 评审。

输出：

- `set_score`
- rubric details
- paragraph evidence
- laugh map
- critique

## Step 5：Strategist / Revision Manager

Strategist 把 Judge 结果整理成：

- `revision_queue`
- `judge_rubric_update`
- `writer_guidance_update`

## Step 6：Targeted rewrite

Rewrite 按 queue 逐刀修。

每刀：

- 只改最小必要范围
- 优先 1 段或几句
- 改完后 selective rejudge

## Step 7：Selective rejudge / resegment

不是每刀都全量重评。

优先：

- quick judge
- 只在必要时重拆段
- 只在结构变化明显时重跑 strategist

## Step 8：Version acceptance

记录：

- 是否采纳
- 采纳原因
- 对分数/人设/closer 的影响

---

## 九、v2 的 targeted rewrite 规则

这是 `v2` 必须重构的部分。

### v1 的问题

- 默认以 weakest segment 为主
- 经常整段重写
- 会把已经成立的东西一起改掉
- 改写和采纳逻辑耦合太粗

### v2 的新规则

1. 先改 `revision_queue` 中最高优先级 task
2. 默认一刀只处理最小必要范围
3. 如果只是句子问题，不允许整段重写
4. 只有满足以下情况才允许 3 段以上联动修：
   - closer 全局回收
   - escalation 跨段承接
   - callback seed 补链

### 采纳判断

不只看 `set_score`。

应综合看：

- `set_score`
- `persona_consistency`
- 目标问题是否被移除
- strongest/weakest 是否有改善
- 是否破坏了 must_keep

---

## 十、v2 的“素材问题 vs 写法问题”区分

OpenMic 对我们最值钱的一个点是：

**把检索质量和写作质量分开判。**

我们在 `v2` 里先做轻量版，不一定马上上完整 RAG。

### 1. 素材问题

例如：

- premise 不够硬
- 观察点太普通
- material bank 太少
- details 不真

### 2. 写法问题

例如：

- premise 有了但 running thread 写散了
- escalation 不成立
- closer 没回收
- 句子说透了

### Strategist 要能明确判

- `material_issue`
或
- `writing_issue`

这样下一步才知道该：

- 回 planning/material bank
还是
- 直接局部改稿

---

## 十一、v2 是否引入 performance DSL

### 结论

引入，但先做轻量版，不做完整版。

### v2.0

先只在 blackboard 里保留：

- `pause_candidates`
- `callback_seeds`
- `applause_candidates`
- `high-pressure beats`

### v2.2 再考虑

正式写进脚本的标记，例如：

- `[PAUSE]`
- `[EMPH]`
- `[CALLBACK]`
- `[APPLAUSE]`

原因：

- 现在文本层还没完全稳定
- 太早做 DSL 会分散重构重点

---

## 十二、v2 的阶段划分

## Phase 1：Blackboard 最小闭环

目标：

- 定义 artifacts
- 让 planning / writer / judge / strategist / rewrite 都围绕同一份 blackboard 工作

不做：

- performance DSL
- material retrieval engine
- 外部数据自动对接

## Phase 2：Judge / Strategist 强化

目标：

- Judge v2 rubric
- critique quality checker
- Strategist 成为 revision manager

不做：

- 完整多模态笑声监督

## Phase 3：Material Bank / Retrieval Quality

目标：

- 区分素材问题和写法问题
- 开始建立 stand-up material bank

## Phase 4：Light performance layer

目标：

- callback / pause / applause candidate 进入 blackboard

---

## 十三、推荐的落地顺序

### 第一刀

先定义 `blackboard schema`。

这是 `v2` 的地基。

### 第二刀

重构 planning，让它稳定产出：

- `persona_card_public`
- `persona_iceberg_hidden`
- `audience_contract`
- `premise_sheet`
- `beat_outline`

### 第三刀

重构 Judge，做 stand-up rubric v2。

### 第四刀

重构 Strategist，让它输出真正的 `revision_queue` 和 `rubric updates`。

### 第五刀

重构 Rewrite，让它变成 task-list 驱动，而不是 weakest segment 驱动。

### 第六刀

补“素材问题 vs 写法问题”的判定。

### 第七刀

再考虑轻量 performance layer。

---

## 十四、v2 的成功标准

如果 `v2` 成功，应该能看到这些变化：

1. 初稿不再频繁滑向 memoir / 碎碎念 / 抱怨
2. Judge 的批评更短，但更准、更可执行
3. Strategist 的意见能直接变成 revision tasks
4. Rewrite 不再靠整段推倒重来，而是逐刀修
5. 同一篇稿子的中间产物可读、可追踪、可复盘
6. 每一轮修改都能回答：
   - 改了什么
   - 为什么
   - 有没有变好
   - 有没有更像这个人

---

## 十五、当前建议

现在最值得做的不是继续盲修某一篇稿子，而是先做 `v2` 的最小地基：

1. `blackboard schema`
2. `planning v2`
3. `judge rubric v2`
4. `strategist as revision manager`

这四步做完，后面的 stand-up 长稿实验才会真正进入“系统迭代”阶段，而不是继续在 prompt 层面做局部加法。
