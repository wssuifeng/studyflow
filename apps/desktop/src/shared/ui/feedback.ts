import { reactive } from 'vue'
import { EngineError } from '../api/engine'

export type FeedbackTone = 'success' | 'error' | 'info'
export const notice = reactive<{ message: string; tone: FeedbackTone; action: string }>({ message: '', tone: 'success', action: '' })
let timer: ReturnType<typeof setTimeout>
export function notify(message: string, tone: FeedbackTone = 'success', action = '') {
  clearTimeout(timer)
  Object.assign(notice, { message, tone, action })
  if (tone === 'success' || tone === 'info') timer = setTimeout(() => { notice.message = '' }, 4500)
}
export function reportError(cause: unknown) {
  notify(cause instanceof Error ? cause.message : '操作未完成，请重试', 'error', cause instanceof EngineError ? cause.nextAction : '')
}
