import { useEffect, useMemo, useState } from 'react'
import { getCalibration, listJokes, type CalibrationResponse, type Joke } from '../api/endpoints'
import { CONTENT_TYPE_OPTIONS } from './shared'

function ScatterPlot({ jokes }: { jokes: Joke[] }) {
  const points = jokes
    .filter((joke) => joke.human_rating != null && joke.score?.weighted_total != null)
    .map((joke, index) => ({
      x: ((joke.human_rating ?? 0) / 10) * 100,
      y: 100 - (((joke.score?.weighted_total ?? 0) / 10) * 100),
      id: `${joke.id ?? 'joke'}-${index}`,
    }))

  if (points.length === 0) {
    return <div className="rounded-xl border border-dashed border-black/10 p-8 text-sm text-outline">暂无可视化散点数据</div>
  }

  return (
    <div className="relative aspect-[16/10] overflow-hidden rounded-xl border border-black/10 bg-white">
      <div className="subtle-grid absolute inset-0 opacity-60" />
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="relative h-full w-full">
        <line x1="10" y1="90" x2="95" y2="10" stroke="#c6c6c6" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
      </svg>
      {points.map((point) => (
        <div
          key={point.id}
          className="absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-black"
          style={{ left: `${Math.max(point.x, 4)}%`, top: `${Math.min(Math.max(point.y, 4), 96)}%` }}
        />
      ))}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
        Human Expert Score
      </div>
      <div className="absolute left-4 top-1/2 -translate-y-1/2 -rotate-90 text-[10px] font-bold uppercase tracking-[0.2em] text-outline">
        Diagnostic Score
      </div>
    </div>
  )
}

export default function CalibrationPage() {
  const [contentType, setContentType] = useState('')
  const [report, setReport] = useState<CalibrationResponse | null>(null)
  const [points, setPoints] = useState<Joke[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleGenerate(type = contentType) {
    setLoading(true)
    setError(null)
    try {
      const [reportData, jokes] = await Promise.all([
        getCalibration(type || undefined),
        listJokes({ content_type: type || undefined, limit: 200 }),
      ])
      setReport(reportData)
      setPoints(jokes.filter((item) => item.human_rating != null))
    } catch (err) {
      setError(err instanceof Error ? err.message : '生成校准报告失败')
      setReport(null)
      setPoints([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void handleGenerate('')
    // intentionally load a default report on first paint
  }, [])

  const markdownSections = useMemo(
    () =>
      (report?.markdown ?? '')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean),
    [report],
  )

  return (
    <div className="space-y-10">
      <header className="space-y-3 text-center">
        <h1 className="page-title">校准报告系统</h1>
        <p className="mx-auto max-w-2xl text-sm font-medium leading-relaxed text-outline">
          这里校准的是 Judge 的诊断分，而不是训练轨 reward；它主要回答“系统解释得准不准”。
        </p>
      </header>

      <section className="mx-auto flex max-w-xl flex-col gap-3 rounded-xl border border-black/5 bg-white p-2 shadow-[0_20px_60px_-32px_rgba(0,0,0,0.18)] md:flex-row">
        <select
          value={contentType}
          onChange={(event) => setContentType(event.target.value)}
          className="flex-1 rounded-lg border-none bg-transparent px-4 py-3 text-sm font-medium outline-none"
        >
          <option value="">全部类型</option>
          {CONTENT_TYPE_OPTIONS.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void handleGenerate()}
          disabled={loading}
          className="rounded-lg bg-black px-6 py-3 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {loading ? '生成中...' : '生成校准报告'}
        </button>
      </section>

      {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}

      <section className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
        <article className="panel space-y-6 p-8">
          <div className="flex items-center justify-between">
            <h2 className="font-headline text-lg font-extrabold tracking-tight">分析综述</h2>
            <span className="rounded-full bg-surface-container-low px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
              Report v1
            </span>
          </div>
          {report ? (
            <>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <div className="eyebrow">样本量</div>
                  <div className="mt-2 text-3xl font-headline font-extrabold">{report.sample_size}</div>
                </div>
                <div>
                  <div className="eyebrow">Pearson r</div>
                  <div className="mt-2 text-3xl font-headline font-extrabold">{report.pearson_r.toFixed(3)}</div>
                </div>
              </div>
              <div className="space-y-3 text-sm leading-7 text-outline">
                {markdownSections.map((section) => (
                  <p key={section}>{section}</p>
                ))}
              </div>
              <div className="rounded-xl border-l-2 border-black bg-surface-container-low p-4 text-sm italic text-black">
                {report.interpretation}
              </div>
            </>
          ) : (
            <div className="text-sm text-outline">还没有生成校准报告。</div>
          )}
        </article>

        <article className="panel space-y-6 p-8">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="font-headline text-lg font-extrabold tracking-tight">得分相关性分布</h2>
              <p className="mt-1 text-[11px] text-outline">
                {report ? `N = ${report.sample_size} samples · diagnostic track` : '等待报告生成'}
              </p>
            </div>
            {report ? (
              <div className="rounded-full border border-black/10 px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
                avg gap {report.avg_gap.toFixed(2)}
              </div>
            ) : null}
          </div>
          <ScatterPlot jokes={points} />
        </article>
      </section>
    </div>
  )
}
