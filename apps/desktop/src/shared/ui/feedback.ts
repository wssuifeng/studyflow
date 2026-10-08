import { reactive } from 'vue'
import { EngineError } from '../api/engine'

export const notice = reactive({ message: '', tone: 'success', action: '' })
let timer: ReturnType<typeof setTimeout>
export function notify(message: string, tone = 'success', action = '') {
  clearTimeout(timer)
  Object.assign(notice, { message, tone, action })
  if (tone === 'success' || tone === 'info') timer = setTimeout(() => { notice.message = '' }, 4500)
}
export function reportError(cause: unknown) {
  notify(cause instanceof Error ? cause.message : '操作未完成，请重试', 'error', cause instanceof EngineError ? cause.nextAction : '')
}
