import { useEffect, useState } from 'react'
import type { Joke } from '../api/endpoints'
import ScoreBars from './ScoreBars'

const reactions = ['好笑', '一般', '不好笑']

export default function JokeCard({
  joke,
  expanded,
  onToggle,
  onSubmitRating,
}: {
  joke: Joke
  expanded: boolean
  onToggle: () => void
  onSubmitRating?: (rating: number, reaction: string) => Promise<void> | void
}) {
  const [rating, setRating] = useState(joke.human_rating ?? 7)
  const [reaction, setReaction] = useState(joke.human_reaction ?? '一般')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setRating(joke.human_rating ?? 7)
    setReaction(joke.human_reaction ?? '一般')
  }, [joke.human_rating, joke.human_reaction])

  async function submit() {
    if (!onSubmitRating) return
    setSubmitting(true)
    try {
      await onSubmitRating(rating, reaction)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <article className="overflow-hidden rounded-xl border border-black/5 bg-white shadow-[0_20px_60px_-32px_rgba(0,0,0,0.18)] transition-all">
      <button className="w-full p-6 text-left transition-colors hover:bg-surface-container-low" onClick={onToggle}>
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-3">
              <span className="border border-black px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest">
                {joke.content_type}
              </span>
              <span className="text-[11px] font-medium tracking-tight text-gray-400">
                {new Date(joke.created_at).toLocaleString('zh-CN')}
              </span>
            </div>
            <p className="max-w-3xl text-lg font-medium leading-relaxed text-black">
              {expanded ? joke.text : `${joke.text.slice(0, 90)}${joke.text.length > 90 ? '…' : ''}`}
            </p>
          </div>
          <div className="text-right">
            <div className="mb-1 text-xs font-bold uppercase tracking-widest text-gray-400">AI Score</div>
            <div className="text-3xl font-black tracking-tighter text-black">
              {(joke.score?.weighted_total ?? 0).toFixed(1)}
            </div>
          </div>
        </div>
      </button>
      {expanded ? (
        <div className="grid grid-cols-1 gap-10 border-t border-black/5 p-8 lg:grid-cols-2">
          <div>
            <h4 className="mb-6 text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">
              维度评估 / Dimension Analysis
            </h4>
            <ScoreBars score={joke.score} />
          </div>
          <div className="flex flex-col justify-between">
            <div>
              <h4 className="mb-6 text-[10px] font-bold uppercase tracking-[0.2em] text-gray-400">
                人工评分 / Human Review
              </h4>
              <div className="mb-8">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-xs font-medium">评分 (1-10)</span>
                  <span className="text-lg font-black tracking-tighter">{rating.toFixed(1)}</span>
                </div>
                <input
                  type="range"
                  min={1}
                  max={10}
                  step={1}
                  value={rating}
                  onChange={(event) => setRating(Number(event.target.value))}
                  className="h-0.5 w-full cursor-pointer appearance-none bg-gray-100 accent-black"
                />
              </div>
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                {reactions.map((item) => (
                  <button
                    key={item}
                    className={[
                      'border px-4 py-2 text-xs font-bold uppercase tracking-widest transition-all',
                      reaction === item
                        ? 'border-black bg-black text-white'
                        : 'border-gray-100 hover:border-black hover:bg-black hover:text-white',
                    ].join(' ')}
                    onClick={() => setReaction(item)}
                  >
                    {item}
                  </button>
                ))}
              </div>
              {onSubmitRating ? (
                <button
                  onClick={submit}
                  disabled={submitting}
                  className="w-full rounded-lg bg-black py-3 text-sm font-bold tracking-widest text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                >
                  {submitting ? '提交中...' : '提交人工评分'}
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </article>
  )
}
