import { invoke, isTauri } from '@tauri-apps/api/core'
import {persistRequestDiagnostic, requestDiagnostic} from '../ui/requestDiagnostics'
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
  if (!isTauri()) throw new EngineError('BRIDGE_UNAVAILABLE', '当前页面未连接桌面 Engine', '在 StudyFlow 桌面窗口中打开。')
  try {
    response = await invoke<EngineResponse<T>>('engine_call', { request })
  } catch {
    throw new EngineError('CONNECTION_FAILED', '无法连接本地工作区', '保留输入并重新打开软件。')
  }
  if(response.id!==request.id){
    void persistRequestDiagnostic({...requestDiagnostic('engine-response','INVALID_RESPONSE'),operation:method,request_id:String(request.id),response_id:String(response.id)})
    throw new EngineError('INVALID_RESPONSE','响应ID不匹配','写入结果待确认，保留原请求。')
  }
  if (!response.ok) {
    const details = response.error
    throw new EngineError(details?.code || 'ENGINE_ERROR', details?.message || 'StudyFlow Engine 请求失败', (details?.next_action || '') + (details?.diagnostic_id ? ' 诊断编号：' + details.diagnostic_id : ''))
  }
  return response.data as T
}

export async function engineStatus(): Promise<{ running: boolean; managed: boolean }> {
  if (!isTauri()) return { running: false, managed: false }
  return invoke('engine_status')
}
