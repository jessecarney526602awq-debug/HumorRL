# Codex 任务单 — React 前端收尾 + Docker 部署打通

> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **先 `git pull origin main`，再动手。**

---

## 背景

React 前端（`frontend/`）已经基本建好（Vite + Tailwind + React Router）。
FastAPI 后端（`api.py`）也已完成，提供所有 `/api/*` 接口。
`docker-compose.yml` 启动三个服务：`api`（:8000）、`frontend`（:3000）、`scheduler`。

**你的任务：确保前端能在 Docker 里构建并正确连到后端。**

---

## 任务一：重命名 Dockerfile（必须做）

`docker-compose.yml` 已改为：
```yaml
frontend:
  build:
    context: ./frontend
    dockerfile: Dockerfile   # ← 注意，不再是 Dockerfile.frontend
```

当前文件是 `frontend/Dockerfile.frontend`，需要重命名为 `frontend/Dockerfile`：
```bash
mv frontend/Dockerfile.frontend frontend/Dockerfile
```

---

## 任务二：检查 `frontend/Dockerfile` 内容

确认 `frontend/Dockerfile`（重命名后）内容如下，如有差异按此修正：

```dockerfile
# Build stage
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

---

## 任务三：检查 `frontend/nginx.conf`

已有内容如下，确认与此一致（不要动它）：
```nginx
server {
  listen 80;
  root /usr/share/nginx/html;
  index index.html;

  location /api/ {
    proxy_pass http://api:8000;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
```

---

## 任务四：检查 `frontend/src/api/client.ts`

在 Docker 里，前端和 API 在同一个 Docker 网络，浏览器发出的请求经过 nginx 反代到 `http://api:8000`。
所以 `client.ts` 的 `baseURL` 应该是 `/api`（相对路径），不能是 `http://localhost:8000/api`。

检查并确保：
```typescript
const client = axios.create({
  baseURL: '/api',
})
```

---

## 任务五：MonitorPage.tsx — TrainingEngine 面板（已有，不要改）

`frontend/src/pages/MonitorPage.tsx` 已经包含完整的 `TrainingEngine` 组件：
- 每 30 秒轮询 `/api/scheduler/status`
- 显示 🟢 RUNNING / 🔴 OFFLINE 状态点
- 训练进度条（jokes_since / trigger_interval）
- 4 个 job 卡片（batch_generate / health_check / evolution / daily_report）
- 知识库统计（total / genes / rules）

**不要修改这个文件。** 只需确认它在 `App.tsx` 中已被路由（已有 `/monitor` → `<MonitorPage />`）。

---

## 任务六：本地验证构建

```bash
cd frontend
npm install
npm run build   # 确保无 TypeScript/构建报错
```

如果有报错，修复后再提交。

---

## 完成后提交

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add frontend/Dockerfile frontend/
git commit -m "fix(deploy): rename Dockerfile.frontend → Dockerfile, verify baseURL"
git push origin main
```

---

## 验收

在服务器上执行后应能访问：
- `http://服务器IP:3000` — React 前端
- `http://服务器IP:3000/monitor` — 监控页，Training Engine 面板可见
- API 请求走 nginx 反代，无跨域错误
