import type { ContentType } from '../api/endpoints'

export const CONTENT_TYPE_OPTIONS: Array<{ value: ContentType; label: string }> = [
  { value: 'standup', label: '脱口秀段子' },
  { value: 'cold_joke', label: '冷笑话' },
  { value: 'humor_story', label: '幽默故事' },
  { value: 'crosstalk', label: '相声段子' },
  { value: 'text_joke', label: '文字笑话' },
]

export const contentTypeLabelMap: Record<ContentType, string> = CONTENT_TYPE_OPTIONS.reduce(
  (acc, item) => {
    acc[item.value] = item.label
    return acc
  },
  {} as Record<ContentType, string>,
)
