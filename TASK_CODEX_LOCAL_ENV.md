# Codex 任务单 — 本地开发环境配置

> 本地路径：/Users/milo/Documents/Claude/HumorRL/
> **不需要 git pull，只操作本地文件。**

---

## 前提说明

`.env` 文件包含 API Key，不能提交到 git（已在 .gitignore 中）。
用户需要自己去豆包控制台拿 API Key，Codex 只负责准备好配置文件框架。

---

## 任务一：检查 `.env` 是否存在并补全本地开发参数

检查 `/Users/milo/Documents/Claude/HumorRL/.env` 是否存在：

**如果不存在**，从 `.env.example` 复制：
```bash
cp /Users/milo/Documents/Claude/HumorRL/.env.example /Users/milo/Documents/Claude/HumorRL/.env
```

**无论是否存在**，确保 `.env` 里包含以下参数（追加或更新，不要覆盖已有的 API Key）：

```
# 本地开发加速参数
DAILY_CONTENT_TYPE=text_joke
BATCH_SIZE=3
CYCLE_INTERVAL_MINUTES=10
GENERATE_WINDOW_MINUTES=7
STRATEGIST_TRIGGER_INTERVAL=5
DAILY_TOKEN_LIMIT=100000
```

操作方式：逐行检查，如果已存在该 key 则跳过，不存在则追加到文件末尾。

---

## 任务二：提示用户填写 API Key

完成后在终端打印以下提示：

```
========================================
⚠️  需要你手动完成：

1. 打开文件：/Users/milo/Documents/Claude/HumorRL/.env
2. 找到 DOUBAO_API_KEY=
3. 填入你在豆包控制台获取的 API Key
   控制台地址：https://console.volcengine.com
   路径：模型推理 → 在线推理 → API Key 管理

4. 确认模型名称与控制台中开通的端点一致：
   DOUBAO_WRITER_MODEL=doubao-seed-2.0-lite-250315
   DOUBAO_JUDGE_MODEL=doubao-seed-2.0-lite-250315
   DOUBAO_STRATEGIST_MODEL=doubao-seed-2.0-pro-250315

填好后告诉我，我来重启 API 并验证连通性。
========================================
```

---

## 任务三：重启 API 服务（等用户填好 key 后执行）

等用户确认填好 Key 后，运行：

```bash
pkill -f "uvicorn api:app" 2>/dev/null; sleep 1
cd /Users/milo/Documents/Claude/HumorRL
python3 -m uvicorn api:app --host 0.0.0.0 --port 8000 --reload &
sleep 3
curl -s http://localhost:8000/api/personas | python3 -c "import sys,json; print('API OK, personas:', len(json.load(sys.stdin)))"
```

---

## 任务四：验证生成端连通性

API 启动后，测试一次真实生成：

```bash
curl -s -X POST http://localhost:8000/api/generate \
  -H "Content-Type: application/json" \
  -d '{"content_type": "text_joke", "n": 1}' | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'text' in d:
    print('生成成功！内容预览：', d['text'][:50])
elif 'detail' in d:
    print('生成失败：', d['detail'])
"
```

如果返回生成成功，说明本地环境配置完毕。
如果返回模型 404 错误，提示用户检查控制台中的模型端点名称是否与 .env 一致。

---

## 注意事项

- `.env` 已在 `.gitignore` 中，不会被提交
- 不要打印或输出 API Key 的值
- 不要修改 `.env.example`
