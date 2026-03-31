import client from './client'

export type ContentType =
  | 'standup'
  | 'cold_joke'
  | 'humor_story'
  | 'crosstalk'
  | 'text_joke'

export interface Score {
  structure: number
  surprise: number
  relatability: number
  language: number
  creativity: number
  safety: number
  reasoning: string
  weighted_total: number
}

export interface Persona {
  id: number
  name: string
  description: string
  style_prompt: string
  is_preset: boolean
}

export interface Joke {
  id: number | null
  content_type: ContentType
  text: string
  persona_id: number | null
  score: Score | null
  human_rating: number | null
  human_reaction: string | null
  created_at: string
  parent_id: number | null
  rewrite_round: number
}

export interface StatsByType {
  type: string
  count: number
  avg_score: number
}

export interface StatsResponse {
  by_type: StatsByType[]
  recent_scores: Array<{ score: number; created_at: string }>
}

export interface CostStatsResponse {
  total_tokens: number
  by_model: Array<{ model: string; role: string; total_tokens: number; calls: number }>
  daily: Array<{ date: string; total_tokens: number }>
}

export interface CalibrationResponse {
  sample_size: number
  pearson_r: number
  p_value: number
  llm_mean: number
  llm_std: number
  human_mean: number
  human_std: number
  avg_gap: number
  interpretation: string
  generated_at: string
  markdown: string
}

export interface DiversityResponse {
  entropy: number
  max_entropy: number
  diversity_ratio: number
  type_distribution: Record<string, number>
  interpretation: string
}

export interface RewardHackingResponse {
  level: number
  score_trend: number
  repetition_rate: number
  message: string
  action: string
}

export interface UCB1Item {
  content_type: string
  label: string
  plays: number
  avg_score: number
  ucb1_value: number | string
  recommended: boolean
}

export interface KnowledgeEntry {
  id: number
  content_type: string | null
  entry_type: string
  content: string
  source_joke_ids: number[]
  relevance_score: number
  used_count: number
  created_at: string
  updated_at: string
}

export interface ReviewResponse {
  skipped: boolean
  reason?: string
  processed_count?: number
  success_patterns: string[]
  failure_patterns: string[]
  humor_rules: string[]
  new_genes: string[]
  insight?: string
  best_joke_id?: number
  confidence?: number
}

export interface SelfLearnResponse {
  skipped: boolean
  reason?: string
  meta_rules: string[]
  contradictions: string[]
  top_features: string[]
  evolution_direction?: string
}

export interface DailyReport {
  id: number
  report_date: string
  total_generated: number
  avg_score: number
  new_patterns: number
  best_joke_id: number | null
  report_md: string
  created_at: string
}

export interface PromptVariant {
  id: number
  prompt_text: string
  generation: number
  uses: number
  avg_score: number
}

export async function listPersonas() {
  const { data } = await client.get<Persona[]>('/personas')
  return data
}

export async function createPersona(payload: Omit<Persona, 'id'>) {
  const { data } = await client.post<Persona>('/personas', payload)
  return data
}

export async function updatePersona(id: number, payload: Pick<Persona, 'name' | 'description' | 'style_prompt'>) {
  const { data } = await client.put<Persona>(`/personas/${id}`, payload)
  return data
}

export async function deletePersona(id: number) {
  const { data } = await client.delete(`/personas/${id}`)
  return data
}

export async function aiGeneratePersona(nameInput: string, background: string) {
  const { data } = await client.post<Pick<Persona, 'name' | 'description' | 'style_prompt'>>(
    '/personas/ai-generate',
    { name_input: nameInput, background },
  )
  return data
}

export async function generateJoke(payload: {
  content_type: ContentType
  persona_id?: number | null
  topic?: string
  n?: number
}) {
  const { data } = await client.post<Joke>('/generate', payload)
  return data
}

export async function listJokes(params?: {
  content_type?: string
  min_score?: number
  unrated_only?: boolean
  limit?: number
}) {
  const { data } = await client.get<Joke[]>('/jokes', { params })
  return data
}

export async function rateJoke(id: number, rating: number, reaction: string) {
  const { data } = await client.put<Joke>(`/jokes/${id}/rating`, { rating, reaction })
  return data
}

export async function rewriteJoke(id: number, payload?: { max_rounds?: number; target_score?: number }) {
  const { data } = await client.post<Joke[]>(`/jokes/${id}/rewrite`, payload ?? {})
  return data
}

export async function getStats() {
  const { data } = await client.get<StatsResponse>('/stats')
  return data
}

export async function getCosts(days = 7) {
  const { data } = await client.get<CostStatsResponse>('/costs', { params: { days } })
  return data
}

export async function getCalibration(content_type?: string) {
  const { data } = await client.get<CalibrationResponse>('/calibration', { params: { content_type } })
  return data
}

export async function getDiversity() {
  const { data } = await client.get<DiversityResponse>('/monitor/diversity')
  return data
}

export async function getRewardHacking() {
  const { data } = await client.get<RewardHackingResponse>('/monitor/hacking')
  return data
}

export async function getUcb1() {
  const { data } = await client.get<UCB1Item[]>('/monitor/ucb1')
  return data
}

export async function getKnowledge(entry_type?: string) {
  const { data } = await client.get<KnowledgeEntry[]>('/knowledge', { params: { entry_type } })
  return data
}

export async function runStrategistReview(since_joke_id?: number) {
  const { data } = await client.post<ReviewResponse>('/strategist/review', { since_joke_id })
  return data
}

export async function runSelfLearn() {
  const { data } = await client.post<SelfLearnResponse>('/strategist/self-learn')
  return data
}

export async function listReports() {
  const { data } = await client.get<DailyReport[]>('/reports')
  return data
}

export async function generateReport(report_date?: string) {
  const { data } = await client.post<DailyReport>('/reports/generate', { report_date })
  return data
}

export async function listVariants(content_type: string) {
  const { data } = await client.get<PromptVariant[]>('/variants', { params: { content_type } })
  return data
}

export interface SchedulerJob {
  job_name: string
  last_run_at: string | null
  last_status: 'idle' | 'running' | 'success' | 'error'
  last_result: string | null
  run_count: number
  updated_at: string
}

export interface SchedulerStatus {
  is_alive: boolean
  jobs: SchedulerJob[]
  training_progress: {
    jokes_since_last_review: number
    trigger_interval: number
    progress_pct: number
  }
  knowledge_stats: {
    total: number
    genes: number
    rules: number
  }
}

export async function getSchedulerStatus() {
  const { data } = await client.get<SchedulerStatus>('/scheduler/status')
  return data
}

export async function evolve(content_type: string) {
  const { data } = await client.post<{
    best_variant_id: number
    best_score: number
    improvement: number
    survivor_ids: number[]
    baseline_best: number
    content_type: string
  }>('/evolve', { content_type })
  return data
}
