import type { Score } from '../api/endpoints'
import { getDisplayBand, getDisplayReason, getDisplayScore } from '../api/judgeView'

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

  const displayScore = getDisplayScore(score)
  const displayBand = getDisplayBand(score)
  const displayReason = getDisplayReason(score)
  const showDiagnosticScore = Math.abs(displayScore - score.weighted_total) > 0.05

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
        <div className="text-[10px] font-bold uppercase tracking-widest text-gray-400">展示分 / Display Track</div>
        <div className="mt-2 flex items-end gap-1">
          <span className="font-headline text-6xl font-black tracking-tighter text-black">
            {displayScore.toFixed(1)}
          </span>
          <span className="pb-2 text-sm font-bold text-gray-300">/ 10</span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {displayBand ? (
            <span className="rounded-full border border-black/10 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
              {displayBand}
            </span>
          ) : null}
          {score.judge_shape ? (
            <span className="rounded-full border border-black/10 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
              {score.judge_shape}
            </span>
          ) : null}
          {score.judge_subtype ? (
            <span className="rounded-full border border-black/10 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
              {score.judge_subtype}
            </span>
          ) : null}
        </div>
        <p className="mt-4 text-sm leading-relaxed text-outline">{displayReason}</p>
        {score.judge_shape === 'long' && (score.structure_summary || score.best_moment || score.weakest_moment) ? (
          <div className="mt-5 space-y-3 rounded-xl border border-black/5 bg-white p-4">
            <div className="text-[10px] font-bold uppercase tracking-widest text-gray-400">长内容结构预分析</div>
            {score.structure_summary ? (
              <p className="text-sm leading-relaxed text-outline">{score.structure_summary}</p>
            ) : null}
            {score.best_moment ? (
              <p className="text-xs leading-relaxed text-gray-500">最强点：{score.best_moment}</p>
            ) : null}
            {score.weakest_moment ? (
              <p className="text-xs leading-relaxed text-gray-500">最弱点：{score.weakest_moment}</p>
            ) : null}
          </div>
        ) : null}
        {showDiagnosticScore ? (
          <p className="mt-4 text-[11px] font-medium text-gray-400">
            诊断分 {score.weighted_total.toFixed(1)}，用于 calibration 和维度解释，不是训练主奖励。
          </p>
        ) : null}
      </div>
    </div>
  )
}
