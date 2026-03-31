import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

export function getApiErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    const message = error.response?.data?.message
    if (typeof detail === 'string' && detail.trim()) {
      return detail
    }
    if (typeof message === 'string' && message.trim()) {
      return message
    }
    if (typeof error.message === 'string' && error.message.trim()) {
      return error.message
    }
  }
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return '请求失败'
}

export default client
