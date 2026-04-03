import { useEffect, useMemo, useState } from 'react'
import { getCosts, getStats, type CostStatsResponse, type StatsResponse } from '../api/endpoints'
import { contentTypeLabelMap } from './shared'

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function LineChart({ values }: { values: number[] }) {
  if (values.length === 0) {
    return <div className="rounded-xl border border-dashed border-black/10 p-6 text-sm text-outline">暂无趋势数据</div>
  }

  const max = Math.max(...values, 10)
  const min = Math.min(...values, 0)
  const range = Math.max(max - min, 1)
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * 100
      const y = 100 - ((value - min) / range) * 100
      return `${x},${y}`
    })
    .join(' ')

  return (
    <div className="relative aspect-[16/8] overflow-hidden rounded-xl border border-black/5 bg-white p-4">
      <div className="subtle-grid absolute inset-0 opacity-50" />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="relative h-full w-full">
        <polyline fill="none" stroke="black" strokeWidth="1.5" points={points} vectorEffect="non-scaling-stroke" />
      </svg>
    </div>
  )
}

export default function StatsPage() {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [costs, setCosts] = useState<CostStatsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const [statsData, costData] = await Promise.all([getStats(), getCosts(14)])
        if (cancelled) return
        setStats(statsData)
        setCosts(costData)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '统计数据加载失败')
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [])

  const totalCount = useMemo(() => (stats?.by_type ?? []).reduce((sum, item) => sum + item.count, 0), [stats])
  const averageReward = useMemo(() => {
    const items = stats?.by_type ?? []
    const denominator = items.reduce((sum, item) => sum + item.count, 0)
    if (denominator === 0) return 0
    const numerator = items.reduce((sum, item) => sum + item.avg_score * item.count, 0)
    return numerator / denominator
  }, [stats])
  const recentScores = useMemo(() => [...(stats?.recent_scores ?? [])].reverse().map((item) => item.score), [stats])

  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <h1 className="page-title">统计数据概要</h1>
        <p className="text-sm font-medium text-outline">这里看的是系统内部 reward 轨迹，不等同于生成页对外展示的 display score。</p>
      </header>

      {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}

      <section className="grid gap-6 md:grid-cols-3">
        <div className="panel p-8">
          <div className="eyebrow">总生成数量</div>
          <div className="metric-value mt-4">{loading ? '...' : formatCompactNumber(totalCount)}</div>
        </div>
        <div className="panel p-8">
          <div className="eyebrow">平均系统奖励</div>
          <div className="metric-value mt-4">{loading ? '...' : averageReward.toFixed(2)}</div>
        </div>
        <div className="panel p-8">
          <div className="eyebrow">近 14 天 Token</div>
          <div className="metric-value mt-4">{loading ? '...' : formatCompactNumber(costs?.total_tokens ?? 0)}</div>
        </div>
      </section>

      <section className="grid gap-10 lg:grid-cols-2">
        <div className="space-y-5">
          <div>
            <h2 className="font-headline text-lg font-extrabold tracking-tight">按类型分布统计</h2>
            <p className="mt-1 text-xs text-outline">各内容类型的绝对生成数量</p>
          </div>
          <div className="panel min-h-[320px] p-8">
            {loading ? (
              <div className="text-sm text-outline">统计中...</div>
            ) : (
              <div className="flex h-52 items-end justify-between gap-4">
                {(stats?.by_type ?? []).map((item) => {
                  const height = totalCount === 0 ? 0 : (item.count / totalCount) * 100
                  return (
                    <div key={item.type} className="flex flex-1 flex-col items-center gap-3">
                      <div className="relative flex h-44 w-full items-end rounded-t-sm bg-surface-container-low">
                        <div className="w-full bg-black transition-all" style={{ height: `${Math.max(height, 8)}%` }} />
                      </div>
                      <div className="text-center">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-outline">
                          {contentTypeLabelMap[item.type as keyof typeof contentTypeLabelMap] ?? item.type}
                        </div>
                        <div className="mt-1 text-xs font-semibold text-black">{item.count}</div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="space-y-5">
          <div>
            <h2 className="font-headline text-lg font-extrabold tracking-tight">平均评分分布</h2>
            <p className="mt-1 text-xs text-outline">各类型当前的 reward 均值，用于训练观察，不是前台展示分。</p>
          </div>
          <div className="panel min-h-[320px] p-8">
            {loading ? (
              <div className="text-sm text-outline">统计中...</div>
            ) : (
              <div className="space-y-5">
                {(stats?.by_type ?? []).map((item) => (
                  <div key={item.type}>
                    <div className="mb-2 flex items-center justify-between text-xs font-bold tracking-tight">
                      <span>{contentTypeLabelMap[item.type as keyof typeof contentTypeLabelMap] ?? item.type}</span>
                      <span>{item.avg_score.toFixed(2)}</span>
                    </div>
                    <div className="h-3 w-full bg-surface-container-low">
                      <div className="h-full bg-black" style={{ width: `${Math.max(item.avg_score * 10, 2)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-10 lg:grid-cols-[1.6fr_1fr]">
        <div className="space-y-5">
          <div>
            <h2 className="font-headline text-lg font-extrabold tracking-tight">最近 100 条奖励趋势</h2>
            <p className="mt-1 text-xs text-outline">按时间顺序观察系统主奖励波动</p>
          </div>
          <LineChart values={recentScores} />
        </div>

        <div className="space-y-5">
          <div>
            <h2 className="font-headline text-lg font-extrabold tracking-tight">运行速览</h2>
            <p className="mt-1 text-xs text-outline">帮助你快速判断当前系统状态</p>
          </div>
          <div className="panel space-y-6 p-8">
            <div>
              <div className="eyebrow">近 100 条样本</div>
              <div className="mt-2 text-3xl font-headline font-extrabold tracking-tight">{recentScores.length}</div>
            </div>
            <div>
              <div className="eyebrow">活跃模型数</div>
              <div className="mt-2 text-3xl font-headline font-extrabold tracking-tight">{costs?.by_model.length ?? 0}</div>
            </div>
            <div>
              <div className="eyebrow">每日 token 轨迹</div>
              <div className="mt-2 text-3xl font-headline font-extrabold tracking-tight">{costs?.daily.length ?? 0}</div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
