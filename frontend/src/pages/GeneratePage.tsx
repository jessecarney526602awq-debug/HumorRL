import { useEffect, useState } from 'react'
import {
  type ContentType,
  type Joke,
  type Persona,
  generateJoke,
  listPersonas,
  rewriteJoke,
} from '../api/endpoints'
import { getApiErrorMessage } from '../api/client'
import { getDisplayBand, getDisplayScore, getTrainingReward, getTrainingStateLabel } from '../api/judgeView'
import ScoreBars from '../components/ScoreBars'

const contentTypes: Array<{ value: ContentType; label: string }> = [
  { value: 'standup', label: '脱口秀段子' },
  { value: 'cold_joke', label: '冷笑话' },
  { value: 'humor_story', label: '幽默故事' },
  { value: 'crosstalk', label: '相声段子' },
  { value: 'text_joke', label: '文字笑话' },
]

export default function GeneratePage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [contentType, setContentType] = useState<ContentType>('text_joke')
  const [topic, setTopic] = useState('')
  const [personaEnabled, setPersonaEnabled] = useState(true)
  const [personaId, setPersonaId] = useState<number | null>(null)
  const [generated, setGenerated] = useState<Joke | null>(null)
  const [rewrites, setRewrites] = useState<Joke[]>([])
  const [loading, setLoading] = useState(false)
  const [rewriting, setRewriting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listPersonas()
      .then((items) => {
        setPersonas(items)
        const first = items.find((item) => !item.is_preset) ?? items[0]
        setPersonaId(first?.id ?? null)
      })
      .catch((err) => {
        setError(getApiErrorMessage(err))
      })
  }, [])

  async function handleGenerate() {
    setLoading(true)
    setError(null)
    setRewrites([])
    try {
      const joke = await generateJoke({
        content_type: contentType,
        topic: topic || undefined,
        n: 1,
        persona_id: personaEnabled ? personaId : null,
      })
      setGenerated(joke)
    } catch (err) {
      setError(getApiErrorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function handleRewrite() {
    if (!generated?.id) return
    setRewriting(true)
    setError(null)
    try {
      setRewrites(await rewriteJoke(generated.id))
    } catch (err) {
      setError(getApiErrorMessage(err))
    } finally {
      setRewriting(false)
    }
  }

  const generatedDisplayScore = getDisplayScore(generated?.score)
  const generatedDisplayBand = getDisplayBand(generated?.score)
  const generatedTrainingReward = getTrainingReward(generated)
  const generatedTrainingState = getTrainingStateLabel(generated)

  return (
    <div className="flex flex-col gap-12 lg:flex-row">
      <section className="w-full shrink-0 space-y-10 lg:w-[320px]">
        <div>
          <label className="eyebrow mb-4 block">内容类型 / Content Type</label>
          <div className="flex flex-wrap gap-2">
            {contentTypes.map((item) => (
              <button
                key={item.value}
                className={[
                  'rounded-full border px-4 py-1.5 text-xs font-semibold transition-all',
                  item.value === contentType
                    ? 'border-black bg-black text-white'
                    : 'border-black/5 bg-white text-gray-500 hover:border-gray-300',
                ].join(' ')}
                onClick={() => setContentType(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="eyebrow mb-4 block">创作主题 / Topic</label>
          <textarea
            rows={4}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="输入关键词或具体场景描述..."
            className="w-full resize-none border-b border-gray-200 bg-transparent p-0 text-sm leading-relaxed placeholder:text-gray-300 focus:border-black focus:ring-0"
          />
        </div>

        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <label className="eyebrow">Persona 模拟</label>
            <button
              onClick={() => setPersonaEnabled((value) => !value)}
              className={[
                'relative h-5 w-9 rounded-full transition-colors',
                personaEnabled ? 'bg-black' : 'bg-gray-200',
              ].join(' ')}
            >
              <span
                className={[
                  'absolute top-[2px] h-4 w-4 rounded-full bg-white transition-all',
                  personaEnabled ? 'left-[18px]' : 'left-[2px]',
                ].join(' ')}
              />
            </button>
          </div>
          <select
            value={personaId ?? ''}
            disabled={!personaEnabled}
            onChange={(event) => setPersonaId(Number(event.target.value))}
            className="w-full rounded-lg border border-black/5 bg-white px-4 py-3 text-sm font-medium outline-none transition-all focus:border-black disabled:opacity-50"
          >
            {personas.map((persona) => (
              <option key={persona.id} value={persona.id}>
                {persona.name}
              </option>
            ))}
          </select>
        </div>

        <button
          onClick={handleGenerate}
          disabled={loading}
          className="group flex w-full items-center justify-center gap-3 rounded-lg bg-black py-5 font-bold tracking-[0.1em] text-white transition-all duration-300 hover:-translate-y-1 hover:shadow-[0_20px_60px_-32px_rgba(0,0,0,0.18)] disabled:opacity-50"
        >
          <span>{loading ? '生成中...' : '开始生成'}</span>
          <span className="material-symbols-outlined transition-transform group-hover:translate-x-1">
            arrow_forward
          </span>
        </button>
      </section>

      <section className="flex-1 space-y-8">
        <div className="group relative flex min-h-[400px] flex-col justify-center overflow-hidden rounded-xl border border-black/5 bg-white p-12">
          <div className="absolute left-0 top-0 h-full w-1 bg-black opacity-0 transition-opacity group-hover:opacity-100" />
          <p className="text-balance text-3xl font-light leading-relaxed text-black">
            {generated?.text ?? '点击左侧「开始生成」，让 Only Funs 为你产出一条新的文字幽默内容。'}
          </p>
          <p className="mt-8 text-sm italic text-gray-400">
            {generated && personaEnabled && personaId
              ? `— 已自动保存，并代入 Persona #${personaId}`
              : '— 结果会自动写入历史记录'}
          </p>
        </div>

        <ScoreBars score={generated?.score ?? null} />

        {generated?.score ? (
          <div className="grid gap-4 md:grid-cols-3">
            <div className="panel p-5">
              <div className="eyebrow">前台展示轨</div>
              <div className="mt-3 text-3xl font-headline font-extrabold tracking-tight">{generatedDisplayScore.toFixed(1)}</div>
              <p className="mt-2 text-xs text-outline">{generatedDisplayBand || '当前展示分由诊断轨回退生成。'}</p>
            </div>
            <div className="panel p-5">
              <div className="eyebrow">Judge 路由</div>
              <div className="mt-3 text-lg font-headline font-extrabold tracking-tight">
                {generated.score.judge_shape || 'short'} / {generated.score.judge_subtype || 'general'}
              </div>
              <p className="mt-2 text-xs text-outline">{generated.score.route_reason || '当前未返回额外路由说明。'}</p>
            </div>
            <div className="panel p-5">
              <div className="eyebrow">训练轨状态</div>
              <div className="mt-3 text-lg font-headline font-extrabold tracking-tight">
                {generatedTrainingReward !== null ? generatedTrainingReward.toFixed(1) : 'display-only'}
              </div>
              <p className="mt-2 text-xs text-outline">
                {generatedTrainingReward !== null
                  ? generatedTrainingState
                  : '当前单条前台生成主要用于展示，不直接进入 group ranking 训练奖励。'}
              </p>
            </div>
          </div>
        ) : null}

        <div className="flex flex-col gap-4 md:flex-row">
          <button className="flex-1 rounded-lg border border-black py-4 text-sm font-bold transition-all hover:bg-black hover:text-white">
            已自动保存
          </button>
          <button
            className="flex-1 rounded-lg border border-gray-200 py-4 text-sm font-bold transition-all hover:border-black"
            onClick={handleGenerate}
          >
            再来一条
          </button>
          <button
            className="flex-1 rounded-lg border border-gray-200 py-4 text-sm font-bold transition-all hover:border-black disabled:opacity-50"
            disabled={!generated?.id || rewriting}
            onClick={handleRewrite}
          >
            {rewriting ? '改写中...' : '改写建议'}
          </button>
        </div>

        {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}

        {rewrites.length > 0 ? (
          <div className="space-y-4">
            <div>
              <h3 className="font-headline text-lg font-bold tracking-tight">改写版本</h3>
              <p className="mt-1 text-xs text-outline">来自 `rewrite_until_good()` 的自动迭代结果</p>
            </div>
            {rewrites.map((rewrite) => (
              <div key={rewrite.id ?? rewrite.rewrite_round} className="panel p-6">
                <div className="mb-3 flex items-center justify-between">
                  <span className="eyebrow">Round {rewrite.rewrite_round}</span>
                  <span className="font-headline text-2xl font-black">
                    {getDisplayScore(rewrite.score).toFixed(1)}
                  </span>
                </div>
                <p className="text-sm leading-7 text-black">{rewrite.text}</p>
              </div>
            ))}
          </div>
        ) : null}
      </section>
    </div>
  )
}
