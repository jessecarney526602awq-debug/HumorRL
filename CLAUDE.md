# HumorRL — AI 协作指南

## 仓库信息
- **GitHub**: https://github.com/jessecarney526602awq-debug/HumorRL
- **本地路径**: /Users/milo/Documents/Claude/HumorRL/
- **主分支**: main
- **语言**: Python 3.11+

## 项目简介
基于 LLM 的幽默内容生成与强化学习优化系统。
- **生成模型**: DeepSeek（deepseek-chat，temperature 0.9）
- **评分模型**: MiniMax（MiniMax-M2.7，temperature 0.3）
- **UI**: Streamlit（端口 8501）
- **数据库**: SQLite（data/humor.db）

## 核心文件
```
contract.py        # 所有数据结构（ContentType, JokeRecord, ScoreResult…）
humor_engine.py    # 生成 + 评分核心逻辑
db.py              # SQLite CRUD
app.py             # Streamlit UI
init_db.py         # 数据库初始化脚本
prompts/
  generate/        # 5种内容类型的生成 Prompt
  evaluate/        # 评分 Prompt
data/
  seed_jokes.json  # 种子数据（不提交 humor.db）
```

## 环境配置
```bash
cp .env.example .env   # 填入真实 API Key
pip install -r requirements.txt
python init_db.py      # 初始化数据库
streamlit run app.py   # 启动 UI
```

## 当前阶段：P1 完成，P2 开发中
P2 待开发：
- [ ] 人工标注 UI（打分 + 雷达图）
- [ ] 迭代改写器（低分内容自动改写）
- [ ] Persona 管理页面
- [ ] LLM Judge 校准报告

## 提交时绝对不能包含
- `.env`（含 API Key）
- `data/humor.db`（本地数据库）
- `__pycache__/`

## 架构约束
- `ContentType` 枚举是扩展点，新类型只需加 Enum + Prompt 模板
- `ScoreResult.weighted_total` 权重在 `contract.py` 中定义，可按类型微调
- 评分用 MiniMax，生成用 DeepSeek，两个客户端严格分离
