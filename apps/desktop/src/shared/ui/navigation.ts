import { windowStorageKey } from './workspace'

export function statusLabel(status: string) {
  const labels: Record<string, string> = { DRAFT: '草稿', WAITING_REVIEW: '等待批改', NEEDS_REVISION: '需要修正', REVISION_REQUIRED: '需要修正', RETEST_REQUIRED: '需要复测', PASSED: '已通过', REVIEWED: '已批阅', RECHECKED: '已复核', ACTIVE: '进行中', NOT_STARTED: '未开始', IN_PROGRESS: '学习中', COMPLETED: '已读完', ARCHIVED: '已归档', PAUSED: '已暂停', PARTIAL_FEEDBACK: '部分反馈已返回', READ_COMPLETED: '本次阅读已完成' }
  return labels[status] || status
}
let navigationGuard: ((path: string) => Promise<boolean>) | null = null
let approvedPath: string | null = null
export function setNavigationGuard(guard: (path: string) => Promise<boolean>) {
  navigationGuard = guard
  return () => {if(navigationGuard === guard) navigationGuard = null}
}
export async function confirmNavigation(path: string) {
  if(approvedPath === path) {approvedPath = null; return true}
  return navigationGuard ? navigationGuard(path) : true
}
export async function navigate(path: string) {
  if(window.location.hash.slice(1) === path) return
  if(!await confirmNavigation(path)) return
  approvedPath = path
  window.location.hash = path
  try{localStorage.setItem(windowStorageKey('last-route'),path)}catch{/* Navigation is never gated by optional storage. */}
}
export function makeRequestKey(operation: string) { return operation + ':' + crypto.randomUUID() }
