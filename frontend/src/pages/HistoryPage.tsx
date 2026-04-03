import { useEffect, useMemo, useState } from 'react'
import JokeCard from '../components/JokeCard'
import { listJokes, rateJoke, type Joke } from '../api/endpoints'
import { getDisplayScore, getTrainingReward } from '../api/judgeView'
import { CONTENT_TYPE_OPTIONS, contentTypeLabelMap } from './shared'

const filterOptions = [{ value: '', label: '全部' }, ...CONTENT_TYPE_OPTIONS]

export default function HistoryPage() {
  const [contentType, setContentType] = useState('')
  const [minScore, setMinScore] = useState(0)
  const [unratedOnly, setUnratedOnly] = useState(false)
  const [jokes, setJokes] = useState<Joke[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await listJokes({
          content_type: contentType || undefined,
          min_score: minScore > 0 ? minScore : undefined,
          unrated_only: unratedOnly,
          limit: 100,
        })
        if (cancelled) return
        setJokes(data)
        setExpandedId((current) => (current !== null && data.some((item) => item.id === current) ? current : data[0]?.id ?? null))
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : '历史记录加载失败')
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
  }, [contentType, minScore, unratedOnly])

  async function handleRating(jokeId: number, rating: number, reaction: string) {
    const updated = await rateJoke(jokeId, rating, reaction)
    setJokes((current) => current.map((item) => (item.id === jokeId ? updated : item)))
  }

  const averageDisplayScore = useMemo(() => {
    const scored = jokes.filter((joke) => joke.score)
    if (scored.length === 0) return 0
    const total = scored.reduce((sum, joke) => sum + getDisplayScore(joke.score), 0)
    return total / scored.length
  }, [jokes])

  const averageTrainingReward = useMemo(() => {
    const rewards = jokes.map((joke) => getTrainingReward(joke)).filter((value): value is number => value != null)
    if (rewards.length === 0) return null
    const total = rewards.reduce((sum, value) => sum + value, 0)
    return total / rewards.length
  }, [jokes])

  const dominantType = useMemo(() => {
    const counts = jokes.reduce<Record<string, number>>((acc, joke) => {
      acc[joke.content_type] = (acc[joke.content_type] ?? 0) + 1
      return acc
    }, {})
    const topEntry = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]
    return topEntry?.[0] ?? null
  }, [jokes])

  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <h1 className="page-title">历史记录</h1>
        <p className="text-sm font-medium text-outline">查看并修正每一条生成内容的自动判断，让训练闭环继续变准。</p>
      </header>

      <section className="panel flex flex-col gap-6 p-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          {filterOptions.map((option) => (
            <button
              key={option.value || 'all'}
              type="button"
              onClick={() => setContentType(option.value)}
              className={[
                'rounded-full border px-4 py-1.5 text-xs font-semibold tracking-wide transition-all',
                contentType === option.value
                  ? 'border-black bg-black text-white'
                  : 'border-black/5 bg-white text-gray-500 hover:border-gray-300 hover:text-black',
              ].join(' ')}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <div className="space-y-2">
            <div className="eyebrow">训练奖励阈值</div>
            <div className="flex items-center gap-3">
              <span className="text-[10px] font-bold text-outline">0</span>
              <input
                type="range"
                min={0}
                max={10}
                step={1}
                value={minScore}
                onChange={(event) => setMinScore(Number(event.target.value))}
                className="h-0.5 w-40 cursor-pointer appearance-none bg-gray-200 accent-black"
              />
              <span className="min-w-8 text-right text-[10px] font-bold text-black">{minScore}</span>
            </div>
            <p className="text-[11px] text-outline">当前筛选按训练轨 reward 过滤，不按前台展示分过滤。</p>
          </div>

          <button
            type="button"
            onClick={() => setUnratedOnly((value) => !value)}
            className="flex items-center gap-3"
          >
            <span className="eyebrow">仅看未标注</span>
            <span className={['relative h-5 w-9 rounded-full transition-colors', unratedOnly ? 'bg-black' : 'bg-gray-200'].join(' ')}>
              <span
                className={[
                  'absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all',
                  unratedOnly ? 'left-[18px]' : 'left-[2px]',
                ].join(' ')}
              />
            </span>
          </button>
        </div>
      </section>

      {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}

      {loading ? (
        <div className="panel p-10 text-sm text-outline">正在加载历史记录...</div>
      ) : jokes.length === 0 ? (
        <div className="panel p-10 text-sm text-outline">当前筛选条件下还没有记录。</div>
      ) : (
        <section className="space-y-6">
          {jokes.map((joke) => {
            const jokeId = joke.id
            return (
              <JokeCard
                key={jokeId ?? `${joke.created_at}-${joke.text.slice(0, 12)}`}
                joke={joke}
                expanded={expandedId === jokeId}
                onToggle={() => setExpandedId((current) => (current === jokeId ? null : jokeId))}
                onSubmitRating={jokeId !== null ? (rating, reaction) => handleRating(jokeId, rating, reaction) : undefined}
              />
            )
          })}
        </section>
      )}

      {jokes.length > 0 ? (
        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="panel p-6">
            <div className="eyebrow">当前样本数</div>
            <div className="metric-value mt-3">{jokes.length}</div>
          </div>
          <div className="panel p-6">
            <div className="eyebrow">平均展示分</div>
            <div className="metric-value mt-3">{averageDisplayScore.toFixed(1)}</div>
          </div>
          <div className="panel p-6">
            <div className="eyebrow">平均训练奖励</div>
            <div className="metric-value mt-3">{averageTrainingReward != null ? averageTrainingReward.toFixed(1) : '--'}</div>
          </div>
          <div className="panel p-6">
            <div className="eyebrow">主导类型</div>
            <div className="mt-3 text-2xl font-headline font-extrabold tracking-tight">
              {dominantType ? contentTypeLabelMap[dominantType as keyof typeof contentTypeLabelMap] : '暂无'}
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
