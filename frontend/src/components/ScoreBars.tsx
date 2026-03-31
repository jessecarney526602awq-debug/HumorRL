import type { Score } from '../api/endpoints'

const dimensions: Array<{ key: keyof Score; label: string }> = [
  { key: 'structure', label: '结构张力 / Structure' },
  { key: 'surprise', label: '意料之外 / Surprise' },
  { key: 'relatability', label: '共鸣阈值 / Resonance' },
  { key: 'language', label: '语言密度 / Density' },
  { key: 'creativity', label: '创意势能 / Creativity' },
  { key: 'safety', label: '安全边界 / Safety' },
]

export default function ScoreBars({ score }: { score: Score | null }) {
  if (!score) {
    return (
      <div className="rounded-xl border border-dashed border-black/10 bg-surface-container-low p-8 text-sm text-outline">
        暂无评分数据
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8 rounded-xl border border-black/5 bg-surface-container-lowest p-8 lg:flex-row">
      <div className="grid flex-1 grid-cols-1 gap-4 md:grid-cols-2">
        {dimensions.map((dimension) => {
          const value = Number(score[dimension.key] ?? 0)
          const percentage = Math.max(0, Math.min(100, value * 10))
          return (
            <div key={dimension.key} className="space-y-2">
              <div className="flex justify-between text-[10px] font-bold uppercase tracking-wider text-gray-400">
                <span>{dimension.label}</span>
                <span>{Math.round(percentage)}%</span>
              </div>
              <div className="relative h-[2px] w-full bg-gray-100">
                <div className="absolute left-0 top-0 h-full bg-black" style={{ width: `${percentage}%` }} />
              </div>
            </div>
          )
        })}
      </div>
      <div className="border-l border-black/5 pl-0 lg:w-[180px] lg:pl-12">
        <div className="text-[10px] font-bold uppercase tracking-widest text-gray-400">
          综合质量评分
        </div>
        <div className="mt-2 flex items-end gap-1">
          <span className="font-headline text-6xl font-black tracking-tighter text-black">
            {score.weighted_total.toFixed(1)}
          </span>
          <span className="pb-2 text-sm font-bold text-gray-300">/ 10</span>
        </div>
        <p className="mt-4 text-sm leading-relaxed text-outline">{score.reasoning}</p>
      </div>
    </div>
  )
}
