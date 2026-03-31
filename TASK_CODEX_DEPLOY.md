# Codex 任务单 — 腾讯云服务器部署

> 服务器：175.24.198.241
> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **在服务器上执行，不是本地。**

---

## 前提

需要能 SSH 登录服务器。如果有 SSH 私钥路径，替换下面命令里的 `-i` 参数。

---

## 任务一：登录服务器，检查环境

```bash
ssh root@175.24.198.241
```

检查 Docker 是否已安装：
```bash
docker --version && docker compose version
```

如果没有 Docker，安装：
```bash
curl -fsSL https://get.docker.com | sh
systemctl start docker && systemctl enable docker
```

---

## 任务二：拉取代码

```bash
cd ~

# 如果目录已存在就 pull，否则 clone
if [ -d "HumorRL" ]; then
  cd HumorRL && git pull origin main
else
  git clone https://github.com/jessecarney526602awq-debug/HumorRL.git
  cd HumorRL
fi
```

---

## 任务三：创建 `.env`（如果不存在）

```bash
if [ ! -f .env ]; then
  cat > .env << 'EOF'
# ⚠️  DOUBAO_API_KEY 必须填入真实值，否则训练无法运行
DOUBAO_API_KEY=FILL_IN_YOUR_KEY_HERE
DOUBAO_WRITER_MODEL=doubao-seed-2.0-lite-250315
DOUBAO_JUDGE_MODEL=doubao-seed-2.0-lite-250315
DOUBAO_STRATEGIST_MODEL=doubao-seed-2.0-pro-250315

DAILY_CONTENT_TYPE=text_joke
BATCH_SIZE=5
CYCLE_INTERVAL_MINUTES=40
GENERATE_WINDOW_MINUTES=28
STRATEGIST_TRIGGER_INTERVAL=10
DAILY_TOKEN_LIMIT=500000
EOF
  echo "⚠️  .env 已创建，请编辑填入 DOUBAO_API_KEY："
  echo "    vi ~/HumorRL/.env"
else
  echo ".env 已存在，跳过创建"
fi
```

**等用户确认已填写 DOUBAO_API_KEY 后再继续。**

---

## 任务四：创建数据目录并启动服务

```bash
cd ~/HumorRL
mkdir -p data

# 构建并后台启动三个服务
docker compose up -d --build
```

等待构建完成（约 3-5 分钟）。

---

## 任务五：验证服务状态

```bash
cd ~/HumorRL

# 检查三个容器是否都在运行
docker compose ps

# 检查 API 是否响应
sleep 5
curl -s http://localhost:8000/api/personas | python3 -c "import sys,json; print('API OK, personas:', len(json.load(sys.stdin)))"

# 检查 scheduler 日志（应看到"调度器启动"）
docker compose logs scheduler --tail=20

# 检查前端是否可访问
curl -s -o /dev/null -w "Frontend HTTP: %{http_code}\n" http://localhost:3000
```

---

## 任务六：开放防火墙端口（如未开放）

腾讯云控制台需要放行端口，或者用命令行：

```bash
# 检查 iptables 是否放行了 3000 和 8000
iptables -L INPUT -n | grep -E "3000|8000"

# 如果没有，添加规则
iptables -I INPUT -p tcp --dport 3000 -j ACCEPT
iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
```

同时去腾讯云控制台 → 安全组 → 入站规则，确认 3000 和 8000 端口已放行。

---

## 验收

完成后输出以下信息：

```
========================================
✅ 部署完成

前端地址：http://175.24.198.241:3000
API 地址： http://175.24.198.241:8000

运行中的服务：
- humorrl-api       FastAPI 后端
- humorrl-frontend  React 前端（nginx）
- humorrl-scheduler 自动训练调度器（24小时运行）

查看日志：
  docker compose logs -f scheduler   # 训练日志
  docker compose logs -f api         # API 日志

更新代码：
  cd ~/HumorRL && git pull && docker compose up -d --build
========================================
```

---

## 注意事项

- `.env` 不在 git 里，每次重新克隆都需要重新创建
- `data/humor.db` 通过 volume 挂载到 `~/HumorRL/data/`，重启容器不丢失
- 如果 scheduler 日志里看到豆包 404 错误，检查 `.env` 里的模型名称是否与控制台一致
