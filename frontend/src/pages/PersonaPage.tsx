import { useEffect, useMemo, useState } from 'react'
import {
  aiGeneratePersona,
  createPersona,
  deletePersona,
  listPersonas,
  updatePersona,
  type Persona,
} from '../api/endpoints'

type EditorMode = 'list' | 'create'

interface PersonaDraft {
  name: string
  description: string
  style_prompt: string
}

const emptyDraft: PersonaDraft = {
  name: '',
  description: '',
  style_prompt: '',
}

export default function PersonaPage() {
  const [mode, setMode] = useState<EditorMode>('list')
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<PersonaDraft>(emptyDraft)
  const [background, setBackground] = useState('')
  const [preview, setPreview] = useState<PersonaDraft | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const data = await listPersonas()
        if (cancelled) return
        setPersonas(data)
        const firstCustom = data.find((item) => !item.is_preset) ?? data[0] ?? null
        setSelectedId(firstCustom?.id ?? null)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Persona 加载失败')
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

  const selectedPersona = useMemo(
    () => personas.find((persona) => persona.id === selectedId) ?? null,
    [personas, selectedId],
  )

  useEffect(() => {
    if (mode !== 'list' || !selectedPersona) return
    setDraft({
      name: selectedPersona.name,
      description: selectedPersona.description,
      style_prompt: selectedPersona.style_prompt,
    })
  }, [mode, selectedPersona])

  function updateDraft<K extends keyof PersonaDraft>(key: K, value: PersonaDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }))
  }

  async function refreshPersonas(selectId?: number | null) {
    const data = await listPersonas()
    setPersonas(data)
    setSelectedId(selectId ?? data.find((item) => !item.is_preset)?.id ?? data[0]?.id ?? null)
  }

  async function handleSaveEdit() {
    if (!selectedPersona) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const updated = await updatePersona(selectedPersona.id, draft)
      setPersonas((current) => current.map((item) => (item.id === updated.id ? updated : item)))
      setNotice('Persona 已更新')
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!selectedPersona || selectedPersona.is_preset) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      await deletePersona(selectedPersona.id)
      await refreshPersonas()
      setNotice('Persona 已删除')
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败')
    } finally {
      setSaving(false)
    }
  }

  async function handleGeneratePreview() {
    setGenerating(true)
    setError(null)
    setNotice(null)
    try {
      const generated = await aiGeneratePersona(draft.name, background)
      setPreview(generated)
      setMode('create')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'AI 生成人设失败')
    } finally {
      setGenerating(false)
    }
  }

  async function handleCreatePersona() {
    const payload = preview ?? draft
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      const created = await createPersona({ ...payload, is_preset: false })
      await refreshPersonas(created.id)
      setMode('list')
      setDraft(emptyDraft)
      setBackground('')
      setPreview(null)
      setNotice('新 Persona 已创建')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-10">
      <header className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="eyebrow">Persona Overview</div>
          <h1 className="page-title mt-3">策展你的数字人格</h1>
        </div>
        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => setMode('list')}
            className={[
              'border-b-2 pb-2 text-sm font-bold tracking-tight transition-colors',
              mode === 'list' ? 'border-black text-black' : 'border-transparent text-gray-400 hover:text-black',
            ].join(' ')}
          >
            角色列表
          </button>
          <button
            type="button"
            onClick={() => setMode('create')}
            className={[
              'border-b-2 pb-2 text-sm font-bold tracking-tight transition-colors',
              mode === 'create' ? 'border-black text-black' : 'border-transparent text-gray-400 hover:text-black',
            ].join(' ')}
          >
            创建新角色
          </button>
        </div>
      </header>

      {error ? <div className="rounded-lg bg-error-container px-4 py-3 text-sm text-error">{error}</div> : null}
      {notice ? <div className="rounded-lg bg-surface-container-high px-4 py-3 text-sm text-black">{notice}</div> : null}

      <section className="grid gap-8 lg:grid-cols-[1.35fr_1fr]">
        <div className="space-y-4">
          {loading ? (
            <div className="panel p-8 text-sm text-outline">正在加载 Persona...</div>
          ) : (
            personas.map((persona) => {
              const isActive = persona.id === selectedId
              return (
                <button
                  key={persona.id}
                  type="button"
                  onClick={() => {
                    setSelectedId(persona.id)
                    setMode('list')
                    setNotice(null)
                  }}
                  className={[
                    'group w-full rounded-xl border p-6 text-left transition-all',
                    isActive
                      ? 'border-black/10 bg-surface-container-low'
                      : 'border-transparent bg-white hover:border-black/10 hover:bg-surface-container-low',
                  ].join(' ')}
                >
                  <div className="flex items-start gap-5">
                    <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-lg bg-surface-container-low text-2xl font-headline font-black text-black">
                      {persona.name.slice(0, 1)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <h2 className="font-headline text-lg font-bold tracking-tight">{persona.name}</h2>
                          <p className="mt-1 text-sm text-outline">{persona.description}</p>
                        </div>
                        <span className="rounded-full border border-black/5 px-2 py-1 text-[10px] font-bold uppercase tracking-widest text-outline">
                          {persona.is_preset ? 'Preset' : 'Custom'}
                        </span>
                      </div>
                      <div className="mt-4 rounded-lg bg-white/80 p-3">
                        <div className="eyebrow">Style Prompt</div>
                        <p className="mt-2 text-xs leading-6 text-outline">{persona.style_prompt}</p>
                      </div>
                    </div>
                  </div>
                </button>
              )
            })
          )}

          <button
            type="button"
            onClick={() => {
              setMode('create')
              setDraft(emptyDraft)
              setBackground('')
              setPreview(null)
              setNotice(null)
            }}
            className="flex w-full items-center justify-center gap-3 rounded-xl border-2 border-dashed border-black/10 px-6 py-10 text-sm font-bold text-outline transition-all hover:border-black hover:bg-white hover:text-black"
          >
            <span className="material-symbols-outlined">add_circle</span>
            点击创建新角色
          </button>
        </div>

        <div className="space-y-6 lg:sticky lg:top-24">
          {mode === 'list' ? (
            <div className="panel space-y-6 p-8">
              <div className="flex items-center gap-2">
                <span className="flex h-5 w-5 items-center justify-center rounded-full bg-black text-[10px] font-bold text-white">01</span>
                <h3 className="text-xs font-headline font-extrabold uppercase tracking-[0.2em]">编辑 Persona</h3>
              </div>
              {selectedPersona ? (
                <>
                  <div>
                    <label className="eyebrow block">角色名称</label>
                    <input
                      value={draft.name}
                      onChange={(event) => updateDraft('name', event.target.value)}
                      className="mt-2 w-full border-b border-outline-variant bg-transparent px-0 py-2 text-lg font-medium outline-none transition-colors focus:border-black"
                    />
                  </div>
                  <div>
                    <label className="eyebrow block">背景描述</label>
                    <textarea
                      rows={3}
                      value={draft.description}
                      onChange={(event) => updateDraft('description', event.target.value)}
                      className="mt-2 w-full resize-none border-b border-outline-variant bg-transparent px-0 py-2 text-sm outline-none transition-colors focus:border-black"
                    />
                  </div>
                  <div>
                    <label className="eyebrow block">Style Prompt</label>
                    <textarea
                      rows={8}
                      value={draft.style_prompt}
                      onChange={(event) => updateDraft('style_prompt', event.target.value)}
                      className="mt-2 w-full resize-none border-b border-outline-variant bg-transparent px-0 py-2 text-sm leading-6 outline-none transition-colors focus:border-black"
                    />
                  </div>
                  <div className="flex flex-col gap-3 sm:flex-row">
                    <button
                      type="button"
                      onClick={handleSaveEdit}
                      disabled={saving}
                      className="flex-1 rounded-lg bg-black py-4 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                    >
                      {saving ? '保存中...' : '保存修改'}
                    </button>
                    <button
                      type="button"
                      onClick={handleDelete}
                      disabled={saving || selectedPersona.is_preset}
                      className="flex-1 rounded-lg border border-black/10 py-4 text-sm font-bold transition-all hover:border-error hover:text-error disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      删除角色
                    </button>
                  </div>
                  {selectedPersona.is_preset ? <p className="text-xs text-outline">预设 Persona 不支持删除。</p> : null}
                </>
              ) : (
                <div className="text-sm text-outline">选择左侧 Persona 以开始编辑。</div>
              )}
            </div>
          ) : (
            <>
              <div className="panel space-y-6 p-8">
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-black text-[10px] font-bold text-white">01</span>
                  <h3 className="text-xs font-headline font-extrabold uppercase tracking-[0.2em]">定义基础人设</h3>
                </div>
                <div>
                  <label className="eyebrow block">角色名称</label>
                  <input
                    value={draft.name}
                    onChange={(event) => updateDraft('name', event.target.value)}
                    placeholder="例如：社死观察员"
                    className="mt-2 w-full border-b border-outline-variant bg-transparent px-0 py-2 text-lg font-medium outline-none transition-colors focus:border-black"
                  />
                </div>
                <div>
                  <label className="eyebrow block">背景描述</label>
                  <textarea
                    rows={4}
                    value={background}
                    onChange={(event) => setBackground(event.target.value)}
                    placeholder="描述角色的语气、生活经历、偏见或观察角度。"
                    className="mt-2 w-full resize-none border-b border-outline-variant bg-transparent px-0 py-2 text-sm outline-none transition-colors focus:border-black"
                  />
                </div>
                <button
                  type="button"
                  onClick={handleGeneratePreview}
                  disabled={generating || draft.name.trim() === ''}
                  className="flex w-full items-center justify-center gap-2 rounded-lg bg-surface-container-high py-4 text-sm font-bold transition-all hover:bg-black hover:text-white disabled:opacity-50"
                >
                  <span className="material-symbols-outlined text-lg">psychology</span>
                  {generating ? 'AI 生成人设中...' : 'AI 生成人设'}
                </button>
              </div>

              <div className={['panel space-y-6 p-8 transition-all', preview ? 'opacity-100' : 'opacity-50 grayscale'].join(' ')}>
                <div className="flex items-center gap-2">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-black text-[10px] font-bold text-white">02</span>
                  <h3 className="text-xs font-headline font-extrabold uppercase tracking-[0.2em]">预览与调校</h3>
                </div>
                {preview ? (
                  <>
                    <div className="rounded-xl bg-surface-container-low p-4">
                      <div className="flex items-center gap-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-white text-xl font-headline font-black">
                          {preview.name.slice(0, 1)}
                        </div>
                        <div>
                          <h3 className="font-headline text-lg font-extrabold tracking-tight">{preview.name}</h3>
                          <p className="text-sm text-outline">{preview.description}</p>
                        </div>
                      </div>
                    </div>
                    <div>
                      <label className="eyebrow block">可继续手动微调</label>
                      <textarea
                        rows={8}
                        value={preview.style_prompt}
                        onChange={(event) =>
                          setPreview((current) => (current ? { ...current, style_prompt: event.target.value } : current))
                        }
                        className="mt-2 w-full resize-none border-b border-outline-variant bg-transparent px-0 py-2 text-sm leading-6 outline-none transition-colors focus:border-black"
                      />
                    </div>
                    <div className="flex flex-col gap-3 sm:flex-row">
                      <button
                        type="button"
                        onClick={handleCreatePersona}
                        disabled={saving}
                        className="flex-1 rounded-lg bg-black py-4 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                      >
                        {saving ? '创建中...' : '保存为新 Persona'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setPreview(null)}
                        className="flex-1 rounded-lg border border-black/10 py-4 text-sm font-bold transition-all hover:border-black"
                      >
                        清空预览
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-outline">先输入角色名称和背景，再让 AI 生成初稿。</div>
                )}
              </div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
