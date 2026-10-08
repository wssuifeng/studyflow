import { invoke, isTauri } from '@tauri-apps/api/core'
export { isTauri } from '@tauri-apps/api/core'

export type EngineResponse<T = unknown> = {
  id: number | string | null
  ok: boolean
  data?: T
  error?: { code: string; message: string; next_action?: string; diagnostic_id?: string }
}

export class EngineError extends Error {
  constructor(public code: string, message: string, public nextAction: string) { super(message); this.name = 'EngineError' }
}

let requestId = 0

export async function engineCall<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const request = { id: ++requestId, method, params }
  let response: EngineResponse<T>
  try {
    if (isTauri()) response = await invoke<EngineResponse<T>>('engine_call', { request })
    else {
      const controller=new AbortController()
      const deadline=setTimeout(()=>controller.abort(),method.startsWith('workspace.')?125000:25000)
      let result:Response
      try {
        result = await fetch('/api/engine', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-StudyFlow-Client': 'studyflow-ui' },
          body: JSON.stringify(request), signal:controller.signal,
        })
        if (!result.ok) throw new EngineError('BRIDGE_UNAVAILABLE', '本地工作区暂时无法连接', '检查开发服务后点击重试。')
        response = await result.json()
      } finally {clearTimeout(deadline)}
    }
  } catch (cause) {
    if ((cause as Error)?.name==='AbortError')throw new EngineError('ENGINE_TIMEOUT','请求超时，写入结果待确认','保留输入与原幂等键，回读后再重试。')
    if (cause instanceof EngineError) throw cause
    throw new EngineError('CONNECTION_FAILED', '无法连接本地工作区', '请重新打开软件，或恢复开发服务后重试。')
  }
  if(response.id!==request.id)throw new EngineError('INVALID_RESPONSE','响应ID不匹配','写入结果待确认，保留原请求。')
  if (!response.ok) {
    const details = response.error
    throw new EngineError(details?.code || 'ENGINE_ERROR', details?.message || 'StudyFlow Engine 请求失败', (details?.next_action || '') + (details?.diagnostic_id ? ' 诊断编号：' + details.diagnostic_id : ''))
  }
  return response.data as T
}

export async function engineStatus(): Promise<{ running: boolean; managed: boolean }> {
  if (isTauri()) return invoke('engine_status')
  await engineCall('system.version')
  return { running: true, managed: false }
}
