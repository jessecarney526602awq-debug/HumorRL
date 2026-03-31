import { useEffect, useMemo, useState } from 'react'
import {
  type ContentType,
  evolve,
  generateReport,
  getCosts,
  getDiversity,
  getKnowledge,
  getRewardHacking,
  getSchedulerStatus,
  getUcb1,
  listReports,
  listVariants,
  runSelfLearn,
  runStrategistReview,
  type CostStatsResponse,
  type DailyReport,
  type DiversityResponse,
  type KnowledgeEntry,
  type PromptVariant,
  type RewardHackingResponse,
  type SchedulerStatus,
  type UCB1Item,
} from '../api/endpoints'
import { CONTENT_TYPE_OPTIONS, contentTypeLabelMap } from './shared'

const alertStyles: Record<number, { label: string; borderClass: string; dotClass: string }> = {
  0: { label: 'Normal', borderClass: 'border-black', dotClass: 'bg-black' },
  1: { label: 'Warning', borderClass: 'border-black', dotClass: 'bg-black' },
  2: { label: 'High', borderClass: 'border-error', dotClass: 'bg-error' },
  3: { label: 'Critical', borderClass: 'border-error', dotClass: 'bg-error' },
}

export default function MonitorPage() {
  const defaultType: ContentType = CONTENT_TYPE_OPTIONS[0]?.value ?? 'standup'
  const [diversity, setDiversity] = useState<DiversityResponse | null>(null)
  const [rewardHacking, setRewardHacking] = useState<RewardHackingResponse | null>(null)
  const [ucb1, setUcb1] = useState<UCB1Item[]>([])
  const [knowledge, setKnowledge] = useState<KnowledgeEntry[]>([])
  const [reports, setReports] = useState<DailyReport[]>([])
  const [costs, setCosts] = useState<CostStatsResponse | null>(null)
  const [variants, setVariants] = useState<PromptVariant[]>([])
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null)
  const [variantType, setVariantType] = useState<ContentType>(defaultType)
  const [loading, setLoading] = useState(true)
  const [schedulerLoading, setSchedulerLoading] = useState(true)
  const [busyAction, setBusyAction] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function loadDashboard(targetType = variantType) {
    setLoading(true)
    setError(null)
    try {
      const [diversityData, hackingData, ucbData, knowledgeData, reportData, costData, variantData] = await Promise.all([
        getDiversity(),
        getRewardHacking(),
        getUcb1(),
        getKnowledge(),
        listReports(),
        getCosts(7),
        listVariants(targetType),
      ])
      setDiversity(diversityData)
      setRewardHacking(hackingData)
      setUcb1(ucbData)
      setKnowledge(knowledgeData)
      setReports(reportData)
      setCosts(costData)
      setVariants(variantData)
    } catch (err) {
      setError(err instanceof Error ? err.message : '监控数据加载失败')
    } finally {
      setLoading(false)
    }
  }

  async function loadScheduler() {
    try {
      const data = await getSchedulerStatus()
      setScheduler(data)
    } catch {
      setScheduler(null)
    } finally {
      setSchedulerLoading(false)
    }
  }

  useEffect(() => {
    void loadDashboard(variantType)
    // load on first paint and whenever the selected content type changes
  }, [variantType])

  useEffect(() => {
    void loadScheduler()
    const timer = window.setInterval(() => {
      void loadScheduler()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [])

  async function runAction(action: 'review' | 'self-learn' | 'report' | 'evolve') {
    setBusyAction(action)
    setActionMessage(null)
    setError(null)
    try {
      if (action === 'review') {
        const result = await runStrategistReview()
        setActionMessage(result.skipped ? result.reason ?? '已跳过复盘' : `复盘完成，新增 ${result.new_genes.length} 条基因。`)
      } else if (action === 'self-learn') {
        const result = await runSelfLearn()
        setActionMessage(
          result.skipped
            ? result.reason ?? '当前知识库不足以训练'
            : `提炼了 ${result.meta_rules.length} 条元规律。进化方向：${result.evolution_direction ?? '待下一轮形成'}`,
        )
      } else if (action === 'report') {
        const result = await generateReport()
        setActionMessage(`已生成 ${result.report_date} 的日报`)
      } else {
        const result = await evolve(variantType)
        const label = contentTypeLabelMap[result.content_type as keyof typeof contentTypeLabelMap] ?? result.content_type
        setActionMessage(`完成一轮 ${label} 进化，最佳分数 ${result.best_score.toFixed(2)}`)
      }
      await loadDashboard(variantType)
    } catch (err) {
      setError(err instanceof Error ? err.message : '监控操作失败')
    } finally {
      setBusyAction(null)
    }
  }

  const budgetPct = useMemo(() => {
    const total = costs?.total_tokens ?? 0
    return Math.min(100, Math.round((total / 200000) * 100))
  }, [costs])
  const alertStyle = alertStyles[rewardHacking?.level ?? 0] ?? alertStyles[0]
  const trainingState = useMemo(() => {
    if (!scheduler?.is_alive) {
      return {
        dotClass: 'bg-error',
        badgeClass: 'border-error/20 bg-error/10 text-error',
        label: '调度器离线',
        detail: '训练循环当前不可用，需检查服务或心跳。',
      }
    }
    if (scheduler.is_training) {
      return {
        dotClass: 'bg-emerald-500',
        badgeClass: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        label: '正在训练',
        detail: '生成器正在跑新一轮样本与评分。',
      }
    }
    return {
      dotClass: 'bg-sky-500',
      badgeClass: 'border-sky-200 bg-sky-50 text-sky-700',
      label: '调度器运行中，等待下一轮',
      detail: '心跳正常，正在等待达到下一次触发阈值。',
    }
  }, [scheduler])

  function formatDate(value: string | null) {
    if (!value) return '未运行'
    return new Date(value).toLocaleString('zh-CN')
  }

  return (
    <div className="space-y-6">
      {rewardHacking ? (
        <section className={`border-l-4 bg-white px-6 py-4 ${alertStyle.borderClass}`}>
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-start gap-4">
              <div className={`mt-2 h-2 w-2 rounded-full ${alertStyle.dotClass}`} />
              <div>
                <h1 className="text-xs font-black uppercase tracking-[0.2em]">
                  Reward Hacking Alert Level: {alertStyle.label}
                </h1>
                <p className="mt-1 text-sm text-outline">{rewardHacking.message}</p>
              </div>
            </div>
            <div className="rounded-full bg-surface-container-low px-3 py-1 text-[10px] font-mono uppercase tracking-widest text-outline">
              repetition {rewardHacking.repetition_rate.toFixed(2)}
            </div>
          </div>
        </section>
      ) : null}

      {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}
      {actionMessage ? <div className="rounded-lg bg-surface-container-high px-4 py-3 text-sm text-black">{actionMessage}</div> : null}

      <section className="panel p-8">
        <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="eyebrow">Training Engine</div>
            <h2 className="mt-3 font-headline text-2xl font-extrabold tracking-tight">训练控制台</h2>
          </div>
          <div className={`inline-flex items-center gap-2 rounded-full border px-4 py-2 text-xs font-bold ${trainingState.badgeClass}`}>
            <span className={`h-2 w-2 rounded-full ${trainingState.dotClass} ${scheduler?.is_training ? 'animate-pulse' : ''}`} />
            <span>{schedulerLoading ? '状态加载中...' : trainingState.label}</span>
          </div>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
          <div className="space-y-6">
            <div className="rounded-xl bg-surface-container-low p-5">
              <div className="mb-3 flex items-center justify-between">
                <span className="eyebrow">训练进度</span>
                <span className="text-sm font-bold text-black">
                  {scheduler?.training_progress.jokes_since_last_review ?? 0}/{scheduler?.training_progress.trigger_interval ?? 0}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-white">
                <div
                  className="h-full bg-black transition-all"
                  style={{ width: `${Math.max(Math.min(scheduler?.training_progress.progress_pct ?? 0, 100), 0)}%` }}
                />
              </div>
              <p className="mt-3 text-sm text-outline">{trainingState.detail}</p>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-black/5 bg-white p-5">
                <div className="eyebrow">知识条目</div>
                <div className="mt-2 text-3xl font-headline font-extrabold">{scheduler?.knowledge_stats.total ?? 0}</div>
              </div>
              <div className="rounded-xl border border-black/5 bg-white p-5">
                <div className="eyebrow">基因池</div>
                <div className="mt-2 text-3xl font-headline font-extrabold">{scheduler?.knowledge_stats.genes ?? 0}</div>
              </div>
              <div className="rounded-xl border border-black/5 bg-white p-5">
                <div className="eyebrow">规则数</div>
                <div className="mt-2 text-3xl font-headline font-extrabold">{scheduler?.knowledge_stats.rules ?? 0}</div>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {(scheduler?.jobs ?? []).map((job) => (
              <div key={job.job_name} className="rounded-xl border border-black/5 bg-white p-5">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <div className="font-headline text-base font-extrabold tracking-tight">{job.job_name}</div>
                    <div className="mt-1 text-xs text-outline">{formatDate(job.last_run_at)}</div>
                  </div>
                  <span className="rounded-full bg-surface-container-low px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
                    {job.last_status}
                  </span>
                </div>
                <div className="mt-4 flex items-center justify-between text-sm text-outline">
                  <span>累计运行</span>
                  <span className="font-semibold text-black">{job.run_count}</span>
                </div>
              </div>
            ))}
            {!schedulerLoading && (scheduler?.jobs ?? []).length === 0 ? (
              <div className="rounded-xl border border-dashed border-black/10 p-5 text-sm text-outline">当前没有调度任务数据。</div>
            ) : null}
          </div>
        </div>
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        <div className="panel p-8">
          <div className="flex items-start justify-between">
            <div>
              <div className="eyebrow">Diversity Index</div>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="font-headline text-6xl font-black tracking-tighter">
                  {loading ? '...' : ((diversity?.diversity_ratio ?? 0) * 100).toFixed(1)}
                </span>
                <span className="text-2xl text-outline-variant">%</span>
              </div>
            </div>
            <span className="material-symbols-outlined text-black/20">hub</span>
          </div>
          <div className="mt-8 border-t border-black/5 pt-6">
            <p className="max-w-xs text-[11px] leading-relaxed text-outline">{diversity?.interpretation ?? '等待多样性数据'}</p>
          </div>
        </div>

        <div className="panel p-8">
          <div className="flex items-start justify-between">
            <div>
              <div className="eyebrow">API Consumption</div>
              <div className="mt-4 flex items-baseline gap-2">
                <span className="font-headline text-6xl font-black tracking-tighter">
                  {loading ? '...' : ((costs?.total_tokens ?? 0) / 1000).toFixed(0)}
                </span>
                <span className="text-2xl text-outline-variant">k</span>
              </div>
            </div>
            <span className="material-symbols-outlined text-black/20">receipt_long</span>
          </div>
          <div className="mt-8 border-t border-black/5 pt-6">
            <div className="mb-2 flex items-center justify-between text-[10px] font-bold uppercase tracking-[0.15em]">
              <span>Budget Utilization</span>
              <span>{budgetPct}%</span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-container-low">
              <div className="h-full bg-black" style={{ width: `${budgetPct}%` }} />
            </div>
          </div>
        </div>
      </section>

      <section className="panel p-8">
        <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 className="font-headline text-lg font-extrabold tracking-tight">UCB1 Strategy Distribution</h2>
            <p className="mt-1 text-xs italic text-outline">Upper Confidence Bound allocation for the next generation round</p>
          </div>
          <button
            type="button"
            onClick={() => void runAction('review')}
            disabled={busyAction === 'review'}
            className="rounded border border-black px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all hover:bg-black hover:text-white disabled:opacity-50"
          >
            {busyAction === 'review' ? '复盘中...' : 'Update Weights'}
          </button>
        </div>
        <div className="space-y-5">
          {ucb1.map((item) => (
            <div key={item.content_type}>
              <div className="mb-2 flex items-center justify-between text-[11px] font-bold tracking-tight">
                <span>{item.label}</span>
                <span className="font-mono">
                  {typeof item.ucb1_value === 'number' ? item.ucb1_value.toFixed(3) : item.ucb1_value}
                </span>
              </div>
              <div className="h-3 w-full bg-surface-container-low">
                <div
                  className={`relative h-full ${item.recommended ? 'bg-black' : 'bg-black/55'}`}
                  style={{ width: `${Math.max((item.avg_score / 10) * 100, 6)}%` }}
                >
                  <span className="absolute -right-8 top-1/2 -translate-y-1/2 text-[10px] font-bold">
                    {item.avg_score.toFixed(1)}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
        <div className="panel p-8">
          <div className="mb-6 flex items-center justify-between">
            <div>
              <h2 className="font-headline text-lg font-extrabold tracking-tight">知识库</h2>
              <p className="mt-1 text-xs text-outline">战略师近几轮总结出的可迁移规律</p>
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => void runAction('review')}
                disabled={busyAction === 'review'}
                className="rounded border border-black px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all hover:bg-black hover:text-white disabled:opacity-50"
              >
                {busyAction === 'review' ? '复盘中...' : '🔬 立即复盘'}
              </button>
              <button
                type="button"
                onClick={() => void runAction('self-learn')}
                disabled={busyAction === 'self-learn'}
                className="rounded border border-black px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all hover:bg-black hover:text-white disabled:opacity-50"
              >
                {busyAction === 'self-learn' ? '训练中...' : '🏋️ 自主训练'}
              </button>
            </div>
          </div>
          <div className="space-y-4">
            {knowledge.slice(0, 8).map((entry) => (
              <div key={entry.id} className="border-b border-black/5 pb-4">
                <div className="mb-1 flex items-center gap-2">
                  <span className="rounded-full bg-surface-container-low px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
                    {entry.entry_type}
                  </span>
                  <span className="text-[10px] text-outline">{entry.content_type ?? 'all'}</span>
                </div>
                <p className="text-sm leading-6 text-black">{entry.content}</p>
              </div>
            ))}
            {!loading && knowledge.length === 0 ? <div className="text-sm text-outline">知识库还没有条目。</div> : null}
          </div>
        </div>

        <div className="space-y-6">
          <div className="panel p-8">
            <div className="mb-6 flex items-center justify-between">
              <div>
                <h2 className="font-headline text-lg font-extrabold tracking-tight">项目日报</h2>
                <p className="mt-1 text-xs text-outline">最近几天的自动复盘纪要</p>
              </div>
              <button
                type="button"
                onClick={() => void runAction('report')}
                disabled={busyAction === 'report'}
                className="rounded border border-black px-3 py-2 text-[10px] font-bold uppercase tracking-[0.2em] transition-all hover:bg-black hover:text-white disabled:opacity-50"
              >
                {busyAction === 'report' ? '生成中...' : '生成日报'}
              </button>
            </div>
            <div className="space-y-4">
              {reports.slice(0, 4).map((report) => (
                <div key={report.id} className="rounded-xl bg-surface-container-low p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-headline text-sm font-extrabold">{report.report_date}</div>
                    <div className="text-xs font-bold text-outline">{report.avg_score.toFixed(2)}</div>
                  </div>
                  <p className="mt-2 text-sm leading-6 text-outline">
                    {report.report_md.length > 180 ? `${report.report_md.slice(0, 180)}...` : report.report_md}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="panel p-8">
            <div className="mb-6 flex items-center justify-between">
              <div>
                <h2 className="font-headline text-lg font-extrabold tracking-tight">Prompt 进化状态</h2>
                <p className="mt-1 text-xs text-outline">观察每个类型当前的高分变体</p>
              </div>
              <select
                value={variantType}
                onChange={(event) => setVariantType(event.target.value as ContentType)}
                className="rounded-full border border-black/10 bg-white px-3 py-2 text-xs font-semibold outline-none"
              >
                {CONTENT_TYPE_OPTIONS.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-4">
              {variants.slice(0, 4).map((variant) => (
                <div key={variant.id} className="rounded-xl bg-surface-container-low p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-headline text-sm font-extrabold">Variant #{variant.id}</div>
                    <div className="text-xs font-bold text-outline">{variant.avg_score.toFixed(2)}</div>
                  </div>
                  <p className="mt-2 text-xs leading-6 text-outline">
                    {variant.prompt_text.length > 180 ? `${variant.prompt_text.slice(0, 180)}...` : variant.prompt_text}
                  </p>
                </div>
              ))}
              {!loading && variants.length === 0 ? <div className="text-sm text-outline">当前类型暂无激活变体。</div> : null}
            </div>
            <button
              type="button"
              onClick={() => void runAction('evolve')}
              disabled={busyAction === 'evolve'}
              className="mt-6 w-full rounded-lg bg-black py-4 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busyAction === 'evolve' ? '进化中...' : '立即进化一轮'}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
