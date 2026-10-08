import { onBeforeUnmount, ref } from 'vue'
import { reportError, setNavigationGuard } from '../../../shared/ui'

type ExitOptions = {
  busy: () => boolean; hasProblem: () => boolean; flush: () => Promise<boolean>
  retry: () => Promise<void>; suspend: () => void; timeoutMs?: number
}
export function useSafeStudyExit(options: ExitOptions) {
  const leaving = ref(false)
  const dialog = ref<{path: string; reason: string; retrying: boolean} | null>(null)
  let dialogPromise: Promise<boolean> | null = null
  let resolveDialog: ((allowed: boolean) => void) | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let disposed = false
  function ask(path: string, reason: string): Promise<boolean> {
    if (dialogPromise) return dialogPromise
    dialog.value = {path, reason, retrying: false}
    dialogPromise = new Promise(resolve => {resolveDialog = resolve})
    return dialogPromise
  }
  function finish(allowed: boolean, discard = false) {
    if (discard) {leaving.value = true; options.suspend()}
    const resolve = resolveDialog
    dialog.value = null; dialogPromise = null; resolveDialog = null
    resolve?.(allowed)
  }
  async function retry() {
    if (!dialog.value || dialog.value.retrying) return
    const current = dialog.value; current.retrying = true
    try {
      await options.retry()
      if (leaving.value || disposed || dialog.value !== current) return
      if (await options.flush()) finish(true)
      else current.reason = '保存仍未完成，或本机恢复内容尚未确认。可以返回学习处理，也可以明确选择不保存离开。'
    } catch (cause) {reportError(cause)}
    finally {if (dialog.value === current) current.retrying = false}
  }
  const removeGuard = setNavigationGuard(async path => {
    if (leaving.value) return true
    if (dialogPromise) return dialogPromise
    if (options.busy()) return ask(path, '保存或提交尚未确认完成。你不需要等待无限期保存才能退出。')
    if (options.hasProblem()) return ask(path, '上次保存未完成，或还有本机内容需要确认；没有覆盖工作区已有记录。')
    let timedOut = false
    try {
      const ok = await Promise.race([options.flush(), new Promise<boolean>(resolve => {
        timer = setTimeout(() => {timedOut = true; resolve(false)}, options.timeoutMs ?? 8000)
      })])
      if (disposed) return false
      return ok || ask(path, timedOut ? '保存长时间没有确认结果。可以重试，也可以不保存离开。' : '当前内容未能保存；本机缓存不能保证恢复。')
    } catch (cause) {reportError(cause); return ask(path, '保存发生异常。可以返回学习处理，也可以不保存离开。')}
    finally {clearTimeout(timer)}
  })
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); removeGuard(); resolveDialog?.(false)})
  return {leaving, dialog, finish, retry}
}
