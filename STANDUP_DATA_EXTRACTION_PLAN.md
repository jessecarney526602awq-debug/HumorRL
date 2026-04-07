# HumorRL 脱口秀数据抽取方案

## 一、目标

这份方案不追求一步到位把脱口秀文稿拆成完美的结构化数据。

Phase 1 的目标只有一个：

**把带笑声标记的脱口秀文稿，稳定转换成可供 Judge 和 Strategist 使用的基础 JSON。**

也就是说，先解决：

- 文稿能读出来
- 每篇内容能分开
- 笑声标记能保留下来
- 后续长内容 Judge 能引用这些信息

而不是一开始就解决：

- 完美 segment 切分
- 精准 punchline 定位
- 复杂角色标注

---

## 二、输入源

当前主要输入源：

- [脱口秀文稿合集.docx](/Users/milo/Downloads/脱口秀文稿合集.docx)

从目前内容观察，这份文稿具备这些特点：

1. 顶部有总标题和目录
2. 内容按演员与作品标题组织
3. 正文中混有：
   - `[笑]`
   - `[爆笑]`
   - `[爆笑/欢呼]`
   - `[爆笑/掌声]`
   - `[掌声]`
4. 每篇稿子可能是完整段子，也可能是节选高光

这意味着数据抽取时必须区分：

- 元信息
- 正文
- 观众反应标记

---

## 三、Phase 1 的输出目标

Phase 1 只生成一份基础数据文件：

- `data/standup_sets.json`

先不生成：

- `standup_segments.json`
- `standup_punchlines.json`

原因很简单：

- segment 切分还没有稳妥规则
- punchline 抽取更依赖上游结构质量
- 先把 set-level 资产做稳，比早拆细粒度更重要

---

## 四、`standup_sets.json` 的建议结构

每条记录代表一篇完整 stand-up 文稿。

建议字段：

```json
{
  "id": "standup_fu_hang_jiqinggaibianrensheng",
  "performer": "付航",
  "section": "第一部分：付航《喜剧之王单口季》",
  "title": "激情改变人生",
  "source_file": "脱口秀文稿合集.docx",
  "source_type": "docx_compilation",
  "full_text": "……",
  "clean_text": "……",
  "paragraphs": [
    "大家好，我是付航……",
    "但是我还是觉得……"
  ],
  "markers": [
    {
      "index": 0,
      "marker": "笑",
      "level": 1,
      "char_offset": 123
    },
    {
      "index": 1,
      "marker": "爆笑",
      "level": 2,
      "char_offset": 402
    }
  ],
  "reaction_summary": {
    "laugh_count": 8,
    "big_laugh_count": 3,
    "applause_count": 1
  }
}
```

### 字段说明

#### `full_text`

保留原始拼接文本，允许包含正文中的自然断段，但不混入单独的笑声标记行。

#### `clean_text`

进一步清洗后的版本：

- 去掉多余空白
- 统一引号、括号和标点
- 不删除正文信息

#### `paragraphs`

保留原始段落数组，后续方便：

- 做 LLM 粗拆段
- 找回上下文
- 做 segment 边界实验

#### `markers`

只记录反应标记的位置，不在 Phase 1 把它们转换成“绝对分数”。

#### `reaction_summary`

做简单计数，用于后续：

- 初步排序候选
- 筛选高峰较多的稿子
- 做 set-level 分布分析

---

## 五、笑声标记的处理原则

这部分必须严格收口，否则后面很容易误用。

### 原则 1：保留位置，不直接转总分

Phase 1 不做：

- “笑 = 7 分”
- “爆笑 = 9 分”
- “掌声 = 8 分”

只做：

- 记录位置
- 记录标记类型
- 做基础统计

### 原则 2：`掌声` 单独记，不混成笑声等级

建议映射：

- `笑` -> `marker=笑, level=1`
- `爆笑` -> `marker=爆笑, level=2`
- `爆笑/欢呼` -> `marker=爆笑/欢呼, level=3`
- `爆笑/掌声` -> `marker=爆笑/掌声, level=2`
- `掌声` -> `marker=掌声, level=null`

这里 `掌声` 暂不赋予“笑点强度”含义。

### 原则 3：笑声标记不作为 Phase 1 切段边界

这是一个关键施工决定。

原因：

- 有的标记可能对应一句
- 有的标记可能对应前面几句累积后的释放
- 相邻笑声间距非常不均匀

所以在 Phase 1：

- 标记只记录
- 不负责切段

---

## 六、文稿解析的推荐流程

### Step 1：从 `.docx` 里抽原始段落

优先目标：

- 不丢段落
- 不丢笑声标记
- 不提前做复杂判断

实现上可用两种方式：

1. `python-docx`
2. 直接读取 docx zip 内的 `word/document.xml`

当前环境如果没有 `python-docx`，可先用第二种。

### Step 2：过滤目录和非正文内容

需要排除：

- 总标题
- 目录
- 页码提示
- “第一部分/第二部分”这种章节标题本身

但要保留：

- 演员名
- 节目标题
- 作品标题

### Step 3：识别作品起始点

建议优先用这些信号组合：

1. 类似 `《标题》` 的作品名
2. 后面紧跟若干正文段
3. 正文中穿插笑声标记

也就是说，一篇稿子的开始，优先以：

- `《作品名》`

为主锚点。

### Step 4：将正文与笑声标记分离

遍历作品区域时：

- 普通段落进入 `paragraphs`
- 单独的 `【笑】/【爆笑】/【掌声】` 进入 `markers`

如果一个段落里混有正文和标记：

- 从文本中切出 marker
- marker 记录位置
- 正文保留在 `paragraphs`

### Step 5：生成 `full_text` 和 `clean_text`

`full_text`：

- 用换行连接正文段落

`clean_text`：

- 压缩冗余空白
- 保留自然句读
- 不移除关键语气词

### Step 6：生成简单统计

例如：

- `laugh_count`
- `big_laugh_count`
- `applause_count`
- `paragraph_count`
- `char_count`

这些先作为 Phase 1 的辅助信息。

---

## 七、关于切段，Phase 1 暂时怎么处理

当前不做正式 segment 数据集，但要为后续留接口。

所以在 `standup_sets.json` 里建议保留：

- `paragraphs`
- `markers`
- `full_text`

后续 LLM 粗拆段时，直接读取这些字段即可。

这比现在硬做：

- `opening`
- `premise`
- `build`
- `punch`
- `closer`

要更稳。

---

## 八、Phase 1 的成功标准

只要达到以下标准，就算成功：

1. 文稿中大部分 stand-up 作品都能被独立抽出来
2. 每篇稿子的正文完整，不混入目录噪声
3. 笑声标记位置保留下来
4. 每篇稿子有稳定的 `performer / title / full_text / markers`
5. 文件可直接被 Judge 和 Strategist 后续读取

Phase 1 不要求：

- 完美边界
- 完美切段
- 完美角色分类

---

## 九、Phase 2 再做什么

等 `standup_sets.json` 稳定后，再进入下一步：

### Phase 2A：验证长稿 Generator

目标：

- 先确认系统能不能稳定生成“像样的 stand-up 初稿”

### Phase 2B：做 LLM 粗拆段

目标：

- 把一篇稿子粗拆成 5-7 段
- 给后续 weakest segment 改写提供操作单元

### Phase 2C：做 set-level Judge

目标：

- 让 Judge 先能指出 strongest / weakest segment
- 而不是立刻做精细 role 标注

---

## 十、推荐的文件与脚本

建议新增：

- `scripts/parse_standup_docx.py`

输入：

- `脱口秀文稿合集.docx`

输出：

- `data/standup_sets.json`

脚本职责只做三件事：

1. 读 docx
2. 拆作品
3. 记录 marker

不要在这个脚本里做：

- LLM 调用
- segment 判断
- Judge 评分

---

## 十一、风险备忘

### 风险 1：作品边界不总是规则化

同一份合集里，有的地方是完整文稿，有的地方是高光节选。

解决方式：

- Phase 1 接受“有些是完整 set，有些是 excerpt”
- 后续加 `is_excerpt` 字段修正

### 风险 2：笑声标记可能不稳定

不同来源版本、不同整理方式，笑声标记未必一致。

解决方式：

- 把它当结构参考，不当绝对分数

### 风险 3：过早切段会污染后续 Judge

如果一开始就用硬规则切坏了，后面 weakest segment 和 punchline 分析都会被污染。

解决方式：

- Phase 1 不做强切段
- 等 set-level 数据稳定后再做 LLM 粗拆段

---

## 十二、一句话执行原则

这份脱口秀文稿的 Phase 1 抽取原则不是：

`现在就把所有结构都识别出来。`

而是：

`先把作品、正文和笑声标记稳定保存下来，为后续 Judge 和 Strategist 的结构分析打地基。`
