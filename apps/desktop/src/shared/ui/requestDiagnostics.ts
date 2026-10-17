import {invoke, isTauri} from '@tauri-apps/api/core'

export type DiagnosticContext = 'english-training' | 'english-retest' | 'engine-response'
export type RequestDiagnostic = {event_id: string; context: DiagnosticContext; code: string; operation?: string; request_id?: string; response_id?: string}

export function describeRequestProblem(error: unknown) {
  const raw = typeof error === 'string' ? error : error instanceof Error ? error.message : ''
  const explicit = typeof error === 'object' && error !== null ? (error as {code?: unknown}).code : null
  const code = typeof explicit === 'string' && /^[A-Z][A-Z0-9_]{0,63}$/.test(explicit) ? explicit
    : /响应\s*ID不匹配|INVALID_RESPONSE/i.test(raw) ? 'INVALID_RESPONSE'
    : /ENGINE_BUSY|尚未发送/.test(raw) ? 'ENGINE_BUSY'
    : /ENGINE_TIMEOUT|请求超时/.test(raw) ? 'ENGINE_TIMEOUT'
    : /VERSION_CONFLICT|版本冲突/.test(raw) ? 'VERSION_CONFLICT'
    : /缓存|恢复副本/.test(raw) ? 'DRAFT_CACHE_UNAVAILABLE' : 'OPERATION_UNCONFIRMED'
  return {code, title: '保存尚未确认', description: code === 'VERSION_CONFLICT'
    ? '工作区中的记录已经变化。当前输入仍保留在本窗口，请先导出，再核对工作区中的内容。'
    : '没有收到可确认的操作结果。当前输入仍保留在本窗口；可以重试原操作，或先导出输入。'}
}

export function requestDiagnostic(context: DiagnosticContext, error: unknown): RequestDiagnostic {
  return {event_id: 'ui-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10), context, code: describeRequestProblem(error).code}
}

/** No error message, stack, request payload or learner content crosses this logging boundary. */
export async function persistRequestDiagnostic(event: RequestDiagnostic): Promise<boolean> {
  const allowed: RequestDiagnostic = {event_id: event.event_id, context: event.context, code: event.code}
  if (event.operation && /^[a-z][a-z0-9_.-]{0,79}$/.test(event.operation)) allowed.operation = event.operation
  for (const key of ['request_id', 'response_id'] as const) {
    if (event[key] && /^[a-zA-Z0-9_-]{1,80}$/.test(event[key])) allowed[key] = event[key]
  }
  console.error('[StudyFlow diagnostic]', allowed)
  if (!isTauri()) return false
  try {await invoke('record_ui_diagnostic', {event: allowed}); return true}
  catch {return false} // A full disk or a down logger must not discard input or pretend logging succeeded.
}
