import { useEffect, useState } from 'react'
import {
  getDiversity,
  getRewardHacking,
  getUcb1,
  getKnowledge,
  listReports,
  generateReport,
  runStrategistReview,
  runSelfLearn,
  listVariants,
  evolve,
  getSchedulerStatus,
  type SchedulerStatus,
  type SchedulerJob,
  type DiversityResponse,
  type RewardHackingResponse,
  type UCB1Item,
  type KnowledgeEntry,
  type DailyReport,
  type PromptVariant,
} from '../api/endpoints'
import { CONTENT_TYPE_OPTIONS } from './shared'

// ── 时间格式化 ──────────────────────────────────────────────────
function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${Math.floor(diff / 86400)}天前`
}

const JOB_LABELS: Record<string, string> = {
  batch_generate: '批量生成',
  health_check: '健康检查',
  evolution: 'Prompt 进化',
  daily_report: '每日日报',
}

const JOB_NEXT: Record<string, string> = {
  batch_generate: '每小时整点',
  health_check: '每6小时',
  evolution: '每天 02:00',
  daily_report: '每天 23:55',
}

// ── Training Engine 组件 ────────────────────────────────────────
function TrainingEngine() {
  const [status, setStatus] = useState<SchedulerStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const fetch = async () => {
    try {
      const data = await getSchedulerStatus()
      setStatus(data)
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetch()
    const timer = setInterval(fetch, 30_000)
    return () => clearInterval(timer)
  }, [])

  if (loading) {
    return (
      <div className="bg-[#1C1B1B] rounded-sm p-5 mb-6 animate-pulse h-40" />
    )
  }

  const alive = status?.is_alive ?? false
  const progress = status?.training_progress
  const kb = status?.knowledge_stats
  const jobs = status?.jobs ?? []
  const pct = progress?.progress_pct ?? 0

  const barColor =
    pct >= 80 ? '#FFB689' : pct >= 50 ? '#A3C9FF' : '#4169E1'

  return (
    <div
      className="rounded-sm p-5 mb-6 border"
      style={{
        background: '#131313',
        borderColor: alive ? '#2a3a2a' : '#3a2a2a',
      }}
    >
      {/* 标题行 */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <div
            className="w-2.5 h-2.5 rounded-full"
            style={{
              background: alive ? '#4ade80' : '#f87171',
              boxShadow: alive ? '0 0 6px #4ade80' : '0 0 6px #f87171',
            }}
          />
          <span
            className="text-sm font-mono font-semibold tracking-widest uppercase"
            style={{ color: alive ? '#4ade80' : '#f87171' }}
          >
            Training Engine — {alive ? 'RUNNING' : 'OFFLINE'}
          </span>
        </div>
        {kb && (
          <div className="flex gap-4 text-xs" style={{ color: '#777' }}>
            <span>知识库 <strong style={{ color: '#C0C7D4' }}>{kb.total}</strong></span>
            <span>基因 <strong style={{ color: '#A3C9FF' }}>{kb.genes}</strong></span>
            <span>规律 <strong style={{ color: '#FFB689' }}>{kb.rules}</strong></span>
          </div>
        )}
      </div>

      {/* 进度条 */}
      {progress && (
        <div className="mb-5">
          <div className="flex justify-between text-xs mb-1.5" style={{ color: '#777' }}>
            <span>战略师复盘进度</span>
            <span style={{ color: '#C0C7D4' }}>
              {progress.jokes_since_last_review} / {progress.trigger_interval} 条
              {pct >= 80 && <span style={{ color: '#FFB689' }}>  即将触发</span>}
            </span>
          </div>
          <div
            className="w-full h-1.5 rounded-full overflow-hidden"
            style={{ background: '#2A2A2A' }}
          >
            <div
              className="h-full rounded-full transition-all duration-500"
              style={{ width: `${pct}%`, background: barColor }}
            />
          </div>
        </div>
      )}

      {/* Job 卡片行 */}
      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {(['batch_generate', 'health_check', 'evolution', 'daily_report'] as const).map(
          (name) => {
            const job: SchedulerJob | undefined = jobs.find((j) => j.job_name === name)
            const st = job?.last_status ?? 'idle'
            const statusIcon =
              st === 'success' ? '✅' : st === 'error' ? '❌' : st === 'running' ? '⏳' : '⬜'
            return (
              <div
                key={name}
                className="rounded-sm px-3 py-2.5"
                style={{ background: '#1C1B1B' }}
              >
                <div
                  className="text-xs font-medium mb-1"
                  style={{ color: '#C0C7D4' }}
                >
                  {statusIcon} {JOB_LABELS[name]}
                </div>
                <div className="text-xs" style={{ color: '#777' }}>
                  {timeAgo(job?.last_run_at ?? null)}
                </div>
                <div className="text-xs mt-0.5" style={{ color: '#555' }}>
                  {JOB_NEXT[name]}
                </div>
              </div>
            )
          },
        )}
      </div>
    </div>
  )
}

// ── Reward Hacking 面板 ─────────────────────────────────────────
function RewardHackingPanel() {
  const [data, setData] = useState<RewardHackingResponse | null>(null)

  useEffect(() => {
    getRewardHacking().then(setData).catch(() => {})
  }, [])

  if (!data) return null

  const levelColor = ['#4ade80', '#FFB689', '#f87171', '#dc2626'][data.level] ?? '#777'
  const levelLabel = ['✅ 正常', '⚠️ L1 预警', '🚨 L2 警告', '🛑 L3 严重'][data.level] ?? '未知'

  return (
    <div
      className="rounded-sm p-4 mb-4 border-l-2"
      style={{ background: '#1C1B1B', borderColor: levelColor }}
    >
      <div className="text-xs mb-1" style={{ color: '#777' }}>Reward Hacking 检测</div>
      <div className="text-base font-semibold mb-1" style={{ color: levelColor }}>
        {levelLabel}
      </div>
      <div className="text-xs" style={{ color: '#C0C7D4' }}>{data.message}</div>
      {data.level > 0 && (
        <div className="text-xs mt-1.5" style={{ color: '#FFB689' }}>建议：{data.action}</div>
      )}
    </div>
  )
}

// ── 多样性 + 成本面板 ───────────────────────────────────────────
function DiversityPanel() {
  const [data, setData] = useState<DiversityResponse | null>(null)

  useEffect(() => {
    getDiversity().then(setData).catch(() => {})
  }, [])

  if (!data) return <div className="h-24 rounded-sm bg-[#1C1B1B] animate-pulse" />

  const pct = Math.round(data.diversity_ratio * 100)
  const color = pct >= 80 ? '#4ade80' : pct >= 50 ? '#FFB689' : '#f87171'

  return (
    <div className="rounded-sm p-4" style={{ background: '#1C1B1B' }}>
      <div className="text-xs mb-3" style={{ color: '#777' }}>内容多样性</div>
      <div className="text-4xl font-bold font-mono mb-1" style={{ color }}>
        {pct}%
      </div>
      <div className="text-xs mb-3" style={{ color: '#777' }}>{data.interpretation}</div>
      <div className="space-y-1">
        {Object.entries(data.type_distribution).map(([type, count]) => {
          const label = CONTENT_TYPE_OPTIONS.find((o) => o.value === type)?.label ?? type
          const w = Math.round((count / Math.max(...Object.values(data.type_distribution))) * 100)
          return (
            <div key={type} className="flex items-center gap-2 text-xs">
              <div className="w-16 truncate" style={{ color: '#777' }}>{label}</div>
              <div className="flex-1 h-1 rounded-full" style={{ background: '#2A2A2A' }}>
                <div className="h-full rounded-full" style={{ width: `${w}%`, background: '#4169E1' }} />
              </div>
              <div style={{ color: '#C0C7D4' }}>{count}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── UCB1 面板 ───────────────────────────────────────────────────
function UCB1Panel() {
  const [items, setItems] = useState<UCB1Item[]>([])

  useEffect(() => {
    getUcb1().then(setItems).catch(() => {})
  }, [])

  if (!items.length) return null

  const maxUcb = Math.max(
    ...items.map((i) => (typeof i.ucb1_value === 'number' ? i.ucb1_value : 99)),
  )

  return (
    <div className="rounded-sm p-4 mt-4" style={{ background: '#1C1B1B' }}>
      <div className="text-xs mb-3" style={{ color: '#777' }}>UCB1 内容策略</div>
      <div className="space-y-2">
        {items.map((item) => {
          const ucb = typeof item.ucb1_value === 'number' ? item.ucb1_value : 99
          const w = maxUcb > 0 ? Math.min(Math.round((ucb / maxUcb) * 100), 100) : 0
          return (
            <div key={item.content_type} className="flex items-center gap-3">
              <div className="w-20 text-xs truncate" style={{ color: item.recommended ? '#A3C9FF' : '#777' }}>
                {item.label}
                {item.recommended && <span className="ml-1 text-[10px]" style={{ color: '#4169E1' }}>推荐</span>}
              </div>
              <div className="flex-1 h-1.5 rounded-full" style={{ background: '#2A2A2A' }}>
                <div
                  className="h-full rounded-full"
                  style={{ width: `${w}%`, background: item.recommended ? '#A3C9FF' : '#4169E1' }}
                />
              </div>
              <div className="text-xs w-28 text-right" style={{ color: '#555' }}>
                {item.plays}次 · 均{item.avg_score.toFixed(1)}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── 知识库面板 ──────────────────────────────────────────────────
const KB_TYPES = [
  { value: '', label: '🔍 全部' },
  { value: 'success_pattern', label: '✅ 成功规律' },
  { value: 'failure_pattern', label: '❌ 失败规律' },
  { value: 'humor_rule', label: '🎭 幽默规律' },
  { value: 'gene', label: '🧬 基因' },
  { value: 'insight', label: '💡 洞察' },
]

function KnowledgePanel() {
  const [entries, setEntries] = useState<KnowledgeEntry[]>([])
  const [filter, setFilter] = useState('')
  const [reviewing, setReviewing] = useState(false)
  const [training, setTraining] = useState(false)
  const [msg, setMsg] = useState('')

  const load = (type = filter) =>
    getKnowledge(type || undefined).then(setEntries).catch(() => {})

  useEffect(() => { load() }, [filter])

  const handleReview = async () => {
    setReviewing(true)
    setMsg('')
    try {
      const r = await runStrategistReview()
      if (r.skipped) setMsg(`数据不足：${r.reason}`)
      else setMsg(`完成！新基因 ${r.new_genes.length} 条，洞察：${r.insight ?? ''}`)
      load()
    } catch (e: any) {
      setMsg(`复盘失败：${e?.message}`)
    } finally {
      setReviewing(false)
    }
  }

  const handleTrain = async () => {
    setTraining(true)
    setMsg('')
    try {
      const r = await runSelfLearn()
      if (r.skipped) setMsg(`跳过：${r.reason}`)
      else setMsg(`自主训练完成！提炼了 ${r.meta_rules.length} 条元规律。进化方向：${r.evolution_direction ?? ''}`)
      load()
    } catch (e: any) {
      setMsg(`自主训练失败：${e?.message}`)
    } finally {
      setTraining(false)
    }
  }

  return (
    <div>
      {/* 筛选 + 按钮 */}
      <div className="flex flex-wrap gap-2 mb-3 items-center justify-between">
        <div className="flex gap-1 flex-wrap">
          {KB_TYPES.map((t) => (
            <button
              key={t.value}
              onClick={() => setFilter(t.value)}
              className="px-2.5 py-1 text-xs rounded-sm transition-colors"
              style={{
                background: filter === t.value ? '#4169E1' : '#2A2A2A',
                color: filter === t.value ? '#fff' : '#777',
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleReview}
            disabled={reviewing}
            className="px-3 py-1.5 text-xs rounded-sm font-medium disabled:opacity-50"
            style={{ background: '#1C1B1B', color: '#A3C9FF', border: '1px solid #2A2A2A' }}
          >
            {reviewing ? '分析中…' : '🔬 立即复盘'}
          </button>
          <button
            onClick={handleTrain}
            disabled={training}
            className="px-3 py-1.5 text-xs rounded-sm font-medium disabled:opacity-50"
            style={{ background: '#1C1B1B', color: '#FFB689', border: '1px solid #2A2A2A' }}
          >
            {training ? '训练中…' : '🏋️ 自主训练'}
          </button>
        </div>
      </div>

      {msg && (
        <div
          className="text-xs px-3 py-2 rounded-sm mb-3"
          style={{ background: '#2A2A2A', color: '#C0C7D4' }}
        >
          {msg}
        </div>
      )}

      {/* 条目列表 */}
      {entries.length === 0 ? (
        <div className="text-xs py-6 text-center" style={{ color: '#555' }}>
          知识库为空，等待战略师复盘后自动填充（每50条触发一次）
        </div>
      ) : (
        <div className="space-y-1.5 max-h-64 overflow-y-auto pr-1">
          {entries.map((e) => {
            const icon = { success_pattern: '✅', failure_pattern: '❌', humor_rule: '🎭', gene: '🧬', insight: '💡' }[e.entry_type] ?? '📌'
            return (
              <div
                key={e.id}
                className="flex gap-3 items-start px-3 py-2 rounded-sm"
                style={{ background: '#1C1B1B' }}
              >
                <span className="mt-0.5 flex-shrink-0">{icon}</span>
                <div className="flex-1 text-xs leading-relaxed" style={{ color: '#C0C7D4' }}>
                  {e.content}
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="text-xs" style={{ color: '#555' }}>⭐{e.relevance_score.toFixed(1)}</div>
                  <div className="text-xs" style={{ color: '#555' }}>用{e.used_count}次</div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── 日报面板 ────────────────────────────────────────────────────
function ReportPanel() {
  const [reports, setReports] = useState<DailyReport[]>([])
  const [selected, setSelected] = useState<DailyReport | null>(null)
  const [generating, setGenerating] = useState(false)

  const load = () =>
    listReports()
      .then((data) => {
        setReports(data)
        if (data.length && !selected) setSelected(data[0])
      })
      .catch(() => {})

  useEffect(() => { load() }, [])

  const handleGenerate = async () => {
    setGenerating(true)
    try {
      const r = await generateReport()
      setReports((prev) => [r, ...prev.filter((p) => p.report_date !== r.report_date)])
      setSelected(r)
    } catch {
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div>
      <div className="flex gap-2 items-center mb-3 flex-wrap">
        {reports.map((r) => (
          <button
            key={r.report_date}
            onClick={() => setSelected(r)}
            className="px-2.5 py-1 text-xs rounded-sm"
            style={{
              background: selected?.report_date === r.report_date ? '#4169E1' : '#2A2A2A',
              color: selected?.report_date === r.report_date ? '#fff' : '#777',
            }}
          >
            {r.report_date}
          </button>
        ))}
        <button
          onClick={handleGenerate}
          disabled={generating}
          className="ml-auto px-3 py-1.5 text-xs rounded-sm disabled:opacity-50"
          style={{ background: '#1C1B1B', color: '#A3C9FF', border: '1px solid #2A2A2A' }}
        >
          {generating ? '生成中…' : '📝 生成今日日报'}
        </button>
      </div>

      {selected ? (
        <div>
          <div className="grid grid-cols-3 gap-2 mb-4">
            {[
              { label: '当日生成', value: selected.total_generated },
              { label: '平均分', value: selected.avg_score.toFixed(2) },
              { label: '新规律', value: selected.new_patterns },
            ].map((s) => (
              <div key={s.label} className="rounded-sm p-3 text-center" style={{ background: '#1C1B1B' }}>
                <div className="text-2xl font-bold font-mono" style={{ color: '#C0C7D4' }}>{s.value}</div>
                <div className="text-xs mt-1" style={{ color: '#777' }}>{s.label}</div>
              </div>
            ))}
          </div>
          <div
            className="text-xs leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto"
            style={{ color: '#C0C7D4' }}
          >
            {selected.report_md}
          </div>
        </div>
      ) : (
        <div className="text-xs text-center py-6" style={{ color: '#555' }}>
          暂无日报，每天 23:55 自动生成
        </div>
      )}
    </div>
  )
}

// ── Prompt 进化面板 ─────────────────────────────────────────────
function EvolutionPanel() {
  const [ct, setCt] = useState('standup')
  const [variants, setVariants] = useState<PromptVariant[]>([])
  const [evolving, setEvolving] = useState(false)
  const [result, setResult] = useState('')

  const load = (type = ct) =>
    listVariants(type).then(setVariants).catch(() => {})

  useEffect(() => { load() }, [ct])

  const handleEvolve = async () => {
    setEvolving(true)
    setResult('')
    try {
      const r = await evolve(ct)
      setResult(`进化完成！最佳 #${r.best_variant_id} 得分 ${r.best_score.toFixed(2)} 提升 ${r.improvement >= 0 ? '+' : ''}${r.improvement.toFixed(2)}`)
      load()
    } catch (e: any) {
      setResult(`进化失败：${e?.message}`)
    } finally {
      setEvolving(false)
    }
  }

  return (
    <div>
      <div className="flex gap-2 items-center mb-3 flex-wrap">
        {CONTENT_TYPE_OPTIONS.map((o) => (
          <button
            key={o.value}
            onClick={() => setCt(o.value)}
            className="px-2.5 py-1 text-xs rounded-sm"
            style={{
              background: ct === o.value ? '#4169E1' : '#2A2A2A',
              color: ct === o.value ? '#fff' : '#777',
            }}
          >
            {o.label}
          </button>
        ))}
        <button
          onClick={handleEvolve}
          disabled={evolving}
          className="ml-auto px-3 py-1.5 text-xs rounded-sm disabled:opacity-50"
          style={{ background: '#1C1B1B', color: '#FFB689', border: '1px solid #2A2A2A' }}
        >
          {evolving ? '进化中…' : '⚡ 立即进化'}
        </button>
      </div>

      {result && (
        <div className="text-xs px-3 py-2 rounded-sm mb-3" style={{ background: '#2A2A2A', color: '#C0C7D4' }}>
          {result}
        </div>
      )}

      <div className="space-y-2 max-h-56 overflow-y-auto">
        {variants.map((v) => (
          <div key={v.id} className="rounded-sm px-3 py-2.5" style={{ background: '#1C1B1B' }}>
            <div className="flex justify-between items-center mb-1.5">
              <span className="text-xs font-medium" style={{ color: '#C0C7D4' }}>
                变体 #{v.id} · 第 {v.generation} 代
              </span>
              <span
                className="text-sm font-bold font-mono"
                style={{ color: v.avg_score >= 7 ? '#4ade80' : v.avg_score >= 4.5 ? '#FFB689' : '#f87171' }}
              >
                {v.avg_score.toFixed(2)}
              </span>
            </div>
            <div className="text-xs" style={{ color: '#555' }}>使用 {v.uses} 次</div>
          </div>
        ))}
        {!variants.length && (
          <div className="text-xs text-center py-4" style={{ color: '#555' }}>
            暂无变体，点击「立即进化」生成初始种群
          </div>
        )}
      </div>
    </div>
  )
}

// ── Collapsible Section ─────────────────────────────────────────
function Section({ title, children, defaultOpen = false }: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-sm mb-3 overflow-hidden" style={{ background: '#131313', border: '1px solid #1e1e1e' }}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex justify-between items-center px-4 py-3 text-left"
        style={{ background: '#1C1B1B' }}
      >
        <span className="text-sm font-medium" style={{ color: '#C0C7D4' }}>{title}</span>
        <span style={{ color: '#555', fontSize: 12 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="px-4 py-4">{children}</div>}
    </div>
  )
}

// ── 主页面 ──────────────────────────────────────────────────────
export default function MonitorPage() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold mb-1" style={{ color: '#C0C7D4' }}>监控中心</h1>
        <p className="text-xs" style={{ color: '#777' }}>训练引擎状态、质量检测与策略分析</p>
      </div>

      {/* Training Engine — 始终展开 */}
      <TrainingEngine />

      {/* Reward Hacking */}
      <RewardHackingPanel />

      {/* 两列：多样性 + UCB1 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <DiversityPanel />
        <UCB1Panel />
      </div>

      {/* 折叠面板 */}
      <Section title="📚 知识库">
        <KnowledgePanel />
      </Section>

      <Section title="📰 项目日报">
        <ReportPanel />
      </Section>

      <Section title="🧬 Prompt 进化">
        <EvolutionPanel />
      </Section>
    </div>
  )
}
