import { reactive, ref } from 'vue'
import { EngineError } from './bridge'

export const notice = reactive({ message: '', tone: 'success', action: '' })
export const workspaceScope = ref('unconnected')
let timer: ReturnType<typeof setTimeout>
export function notify(message: string, tone = 'success', action = '') {
  clearTimeout(timer)
  Object.assign(notice, { message, tone, action })
  if (tone === 'success') timer = setTimeout(() => { notice.message = '' }, 4500)
}
export function reportError(cause: unknown) {
  notify(cause instanceof Error ? cause.message : '操作未完成，请重试', 'error', cause instanceof EngineError ? cause.nextAction : '')
}
export function storageKey(name: string) { return 'studyflow:' + workspaceScope.value + ':' + name }
export function statusLabel(status: string) {
  const labels: Record<string, string> = { DRAFT: '草稿', WAITING_REVIEW: '等待批改', NEEDS_REVISION: '需要修正', REVISION_REQUIRED: '需要修正', RETEST_REQUIRED: '需要复测', PASSED: '已通过', REVIEWED: '已批阅', RECHECKED: '已复核', ACTIVE: '进行中', NOT_STARTED: '未开始', IN_PROGRESS: '阅读中', COMPLETED: '已读完', PAUSED: '已暂停' }
  return labels[status] || status
}
export function navigate(path: string) {
  window.location.hash = path
  localStorage.setItem(storageKey('last-route'), path)
}
export function makeRequestKey(operation: string) { return operation + ':' + crypto.randomUUID() }
