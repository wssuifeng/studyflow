import {computed, onBeforeUnmount, ref} from 'vue'
import {engineCall} from '../../../shared/api'
import {makeRequestKey, windowStorageKey} from '../../../shared/ui'
import type {EnglishDifference} from '../../../shared/api/contracts/english'

type Result = {matched: boolean; status: string; differences: EnglishDifference[]; answer_version?: number}
type Task = {task_id: string; title: string; prompt: string; token_count: number; status: string; answer_text: string; answer_version: number; result: Result | null}
type Pending = {method: 'course.english.retest-save' | 'course.english.retest-check'; params: {task_id: string; answer_text: string; expected_version: number; idempotency_key: string}}

export function useEnglishRetest(taskId: string) {
  const task = ref<Task | null>(null), tokens = ref<string[]>([]), busy = ref(false), failed = ref('')
  const result = ref<Result | null>(null), pending = ref<Pending | null>(null), recovery = ref<{text: string} | null>(null)
  const baseline = ref(''), text = computed(() => tokens.value.join(' ').trim()), dirty = computed(() => text.value !== baseline.value)
  let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, suspended = false, checking = false
  const cacheKey = () => windowStorageKey('english-retest-draft:' + taskId)
  function cache() {
    try {
      if (dirty.value || pending.value) localStorage.setItem(cacheKey(), JSON.stringify({text: text.value, pending: pending.value}))
      else if (!recovery.value) localStorage.removeItem(cacheKey())
    } catch { /* Recovery is best effort; exit/export remain available. */ }
  }
  async function load() {
    task.value = await engineCall<Task>('course.english.retest-get', {task_id: taskId})
    baseline.value = task.value.answer_text
    tokens.value = baseline.value ? baseline.value.split(/\s+/) : Array(task.value.token_count).fill('')
    result.value = task.value.result
    try {
      const raw = localStorage.getItem(cacheKey())
      if (raw && !result.value) {
        const value = JSON.parse(raw)
        if (typeof value.text === 'string') recovery.value = {text: value.text}
        const p = value.pending
        if (p && ['course.english.retest-save', 'course.english.retest-check'].includes(p.method) && p.params?.task_id === taskId && typeof p.params?.idempotency_key === 'string' && typeof p.params?.answer_text === 'string' && Number.isInteger(p.params?.expected_version)) pending.value = p
      } else if (result.value) localStorage.removeItem(cacheKey())
    } catch { failed.value = '本机恢复缓存不可读，可保留当前输入或导出。' }
  }
  async function retryPending() {
    if (busy.value || disposed || suspended) return false
    if (!pending.value) return true
    const request = pending.value; busy.value = true
    try {
      const response = await engineCall<Result>(request.method, request.params)
      if (disposed || suspended) return false
      if (task.value) {task.value.answer_version = response.answer_version!; task.value.answer_text = request.params.answer_text; task.value.status = response.status}
      baseline.value = request.params.answer_text
      if (request.method === 'course.english.retest-check') result.value = response
      pending.value = null; failed.value = ''; cache(); return true
    } catch (cause) {failed.value = (cause as Error).message; cache(); return false}
    finally {busy.value = false}
  }
  async function save() {
    clearTimeout(timer)
    if (busy.value || disposed || suspended || recovery.value) return false
    if (pending.value && !await retryPending()) return false
    if (!task.value) return false
    if (result.value || !dirty.value) return true
    pending.value = {method: 'course.english.retest-save', params: {task_id: taskId, answer_text: text.value, expected_version: task.value.answer_version, idempotency_key: makeRequestKey('english-retest-save')}}
    cache(); return retryPending()
  }
  function edited() {
    cache(); clearTimeout(timer)
    if (!failed.value && !pending.value && !recovery.value) timer = setTimeout(() => {void save()}, 750)
  }
  async function check() {
    if (checking || busy.value || result.value) return
    checking = true
    try {
      if (!await save() || !task.value || result.value) return
      pending.value = {method: 'course.english.retest-check', params: {task_id: taskId, answer_text: text.value, expected_version: task.value.answer_version, idempotency_key: makeRequestKey('english-retest')}}
      cache(); await retryPending()
    } finally {checking = false}
  }
  function restore() {if (!recovery.value) return; tokens.value = recovery.value.text.split(/\s+/); recovery.value = null; cache()}
  async function discardRecovery() {
    if (busy.value) return
    try {
      task.value = await engineCall<Task>('course.english.retest-get', {task_id: taskId})
      baseline.value = task.value.answer_text; tokens.value = baseline.value ? baseline.value.split(/\s+/) : Array(task.value.token_count).fill('')
      result.value = task.value.result; recovery.value = null; pending.value = null; failed.value = ''
      try {localStorage.removeItem(cacheKey())} catch { /* best effort */ }
    } catch (cause) {failed.value = (cause as Error).message}
  }
  function exportInput() {
    const blob = new Blob([JSON.stringify({task_id: taskId, answer_text: text.value, recovery: recovery.value, pending: pending.value}, null, 2)], {type: 'application/json'})
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'StudyFlow-英语复测未保存输入.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function suspend() {suspended = true; clearTimeout(timer); cache()}
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); cache()})
  return {task, tokens, busy, failed, pending, recovery, result, dirty, load, save, edited, check, retryPending, restore, discardRecovery, exportInput, suspend}
}
