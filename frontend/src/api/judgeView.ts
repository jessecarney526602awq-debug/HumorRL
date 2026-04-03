import type { Joke, Score } from './endpoints'

export function getDisplayScore(score: Score | null | undefined): number {
  return Number(score?.display_score ?? score?.weighted_total ?? 0)
}

export function getDisplayBand(score: Score | null | undefined): string {
  return score?.display_band?.trim() || ''
}

export function getDisplayReason(score: Score | null | undefined): string {
  return (
    score?.benchmark_reason?.trim() ||
    score?.critique?.trim() ||
    score?.reasoning?.trim() ||
    ''
  )
}

export function getTrainingReward(joke: Joke | null | undefined): number | null {
  if (joke?.rank_score == null) {
    return null
  }
  return Number(joke.rank_score)
}

export function getTrainingStateLabel(joke: Joke | null | undefined): string {
  if (joke?.rank_score == null) {
    return '未进入训练排序'
  }
  return joke.is_funny === false ? '训练轨判定：不过关' : '训练轨判定：有效样本'
}
