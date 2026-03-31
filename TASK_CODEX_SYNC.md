# Codex 任务单 — 前端同步 + 训练功能集成

> 仓库：https://github.com/jessecarney526602awq-debug/HumorRL
> **先 `git pull origin main`，再动手。**

---

## 背景

最近4个提交（bb0b255 → 68afa58）新增了以下功能，需要同步到前端：

1. **训练周期控制**：`POST /api/training/trigger` 和 `POST /api/training/stop`
2. **调度器状态新字段**：`GET /api/scheduler/status` 返回增加了 `is_training: boolean`
3. **Sidebar 训练按钮**：已在 `Sidebar.tsx` 实现，需验证样式正常
4. **RL 闭环**：后端战略师现在每轮生成后自动复盘并下发指令，前端无需改动

---

## 任务一：验证并修复 Sidebar 训练按钮

查看 `frontend/src/components/Sidebar.tsx`，其中新增了 `TrainingButton` 组件。

确认行为：
- 空闲时：黑底白字「开始训练 →」
- 训练中：白底黑字「● 训练中  终止」（● 有 `animate-pulse` 闪烁效果）
- 每 5 秒轮询 `/api/scheduler/status` 的 `is_training` 字段切换状态

如果样式有问题（颜色、间距、圆角等）对照其他按钮风格修正，保持 Only Funs 设计一致性。

---

## 任务二：MonitorPage 训练面板确认

`frontend/src/pages/MonitorPage.tsx` 已有 `TrainingEngine` 组件，检查：

1. 组件已导入 `getSchedulerStatus` — 如果没有，从 `../api/endpoints` 补充
2. `is_alive`（调度器心跳）和 `is_training`（当前是否在跑生成）都展示在面板上
3. 如果目前只展示了 `is_alive`，在 Training Engine 卡片里增加「训练中」状态指示：
   - `is_alive && is_training` → 状态点绿色 + 文字「正在训练」
   - `is_alive && !is_training` → 状态点蓝色 + 文字「调度器运行中，等待下一轮」
   - `!is_alive` → 状态点红色 + 文字「调度器离线」

---

## 任务三：`frontend/src/api/endpoints.ts` 确认

文件中应已包含以下内容，如果缺失则补充：

```typescript
// SchedulerStatus 接口新增字段
export interface SchedulerStatus {
  is_alive: boolean
  is_training: boolean   // ← 确认有这个
  jobs: SchedulerJob[]
  training_progress: { ... }
  knowledge_stats: { ... }
}

// 新增函数
export async function triggerTraining() {
  const { data } = await client.post<{ started: boolean }>('/training/trigger')
  return data
}

export async function stopTraining() {
  const { data } = await client.post<{ stop_requested: boolean }>('/training/stop')
  return data
}
```

---

## 任务四：构建验证

```bash
cd frontend
npm install
npm run build
```

确保无 TypeScript 错误和构建报错。

---

## 完成后提交

```bash
cd /Users/milo/Documents/Claude/HumorRL
git add frontend/
git commit -m "fix(frontend): sync training button + monitor panel is_training state"
git push origin main
```

---

## 验收标准

- [ ] `npm run build` 零报错
- [ ] Sidebar 按钮根据 `is_training` 切换「开始训练」/「训练中  终止」两种状态
- [ ] MonitorPage Training Engine 面板区分「正在训练」/「等待」/「离线」三种状态
- [ ] `endpoints.ts` 包含 `triggerTraining`、`stopTraining`、`is_training` 字段
