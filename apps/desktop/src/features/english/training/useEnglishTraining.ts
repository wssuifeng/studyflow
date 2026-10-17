import {computed, onBeforeUnmount, ref} from 'vue'
import {engineCall} from '../../../shared/api'
import {makeRequestKey, windowStorageKey} from '../../../shared/ui'
import type {EnglishStudy, EnglishReference, EnglishDifference} from '../../../shared/api/contracts/english'

type Pending = {method: string; params: Record<string, unknown>; exerciseId: string; text: string; revealMode?: 'hint'|'answer'}
type WriteResult = Partial<EnglishReference> & {answer_version?: number; state_version?: number; matched?: boolean | null; differences?: EnglishDifference[]; status?: string; completed?: boolean; position?: number; error_count?: number}
const writeMethods = new Set(['course.english.save','course.english.check','course.english.reveal','course.english.navigate','course.english.submit','course.english.request-review'])

export function useEnglishTraining(studyId: string) {
  const data = ref<EnglishStudy | null>(null), tokens = ref<string[]>([]), position = ref(0), busy = ref(false), failed = ref('')
  const superseded = ref(false)
  const hintMode = ref<'word'|'sentence'|null>(null), navigationNotice=ref('')
  const validationNotice = ref('')
  const reference = ref<EnglishReference | null>(null), phase = ref<'input'|'correction'|'answer'|'result'>('input')
  const pending = ref<Pending | null>(null), recovery = ref<{exerciseId: string; text: string} | null>(null), baseline = ref('')
  const item = computed(() => data.value?.items[position.value]), text = computed(() => tokens.value.join(' ').trim())
  const dirty = computed(() => text.value !== baseline.value)
  let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, suspended = false
  let requestFlight: Promise<boolean> | null = null, saveFlight: Promise<boolean> | null = null
  const actionIntent = ref('')
  const actionInFlight = ref(false), actionBusy = computed(() => busy.value || actionInFlight.value)
  function exclusive<T extends (...args: any[]) => Promise<any>>(fn: T, intent: string) {
    return async (...args: Parameters<T>): Promise<Awaited<ReturnType<T>> | undefined> => {
      if (actionInFlight.value || suspended || disposed) return
      actionInFlight.value = true; actionIntent.value = intent
      try {return await fn(...args)} finally {actionInFlight.value = false; actionIntent.value = ''}
    }
  }
  const cacheKey = () => windowStorageKey('english-draft:' + studyId)
  function cache() {
    try {
      if (item.value && (dirty.value || pending.value)) localStorage.setItem(cacheKey(), JSON.stringify({exerciseId: item.value.exercise_id, text: text.value, pending: pending.value}))
      else if (!recovery.value) localStorage.removeItem(cacheKey())
    } catch { /* Best effort, not a durable-save claim. */ }
  }
  function bind() {
    const current = item.value; if (!current) return
    baseline.value = current.answer_text
    tokens.value = current.answer_text ? current.answer_text.split(/\s+/) : Array(current.token_count).fill('')
    reference.value = null; hintMode.value = null; validationNotice.value = ''
    phase.value = current.matched || ['PASSED','RECHECKED','REVIEWED'].includes(current.status) ? 'answer' : 'input'
  }
  async function load() {
    data.value = await engineCall<EnglishStudy>('course.english.get', {study_session_id: studyId})
    position.value = Math.min(data.value.position, data.value.items.length-1); bind()
    try {
      const raw = localStorage.getItem(cacheKey())
      if (raw) {
        const c = JSON.parse(raw)
        if (typeof c.exerciseId === 'string' && typeof c.text === 'string' && data.value.items.some(i => i.exercise_id === c.exerciseId)) {
          recovery.value = c
          if (writeMethods.has(c.pending?.method) && c.pending?.params?.study_session_id === studyId && typeof c.pending?.params?.idempotency_key === 'string' && c.pending.exerciseId === c.exerciseId) pending.value = c.pending
        }
      }
    } catch {failed.value = '本机草稿缓存无法读取；可继续查看或导出当前输入。'}
  }
  function edited() {
    if (phase.value !== 'correction') phase.value = 'input'
    if (item.value) item.value.matched = false
    if (!hintMode.value) reference.value = null
    validationNotice.value = ''
    cache(); clearTimeout(timer)
    if (!failed.value && !pending.value && !recovery.value && !superseded.value) timer = setTimeout(() => {void save()}, 750)
  }
  async function performPending() {
    if (!pending.value) return true
    const request = pending.value; busy.value = true
    try {
      const result = await engineCall<WriteResult>(request.method, request.params)
      if (disposed || suspended) return false
      const row = data.value?.items.find(i => i.exercise_id === request.exerciseId)
      const current = item.value?.exercise_id === request.exerciseId
      if (data.value && result.state_version !== undefined) data.value.state_version = result.state_version
      if (row && result.answer_version !== undefined) row.answer_version = result.answer_version
      if (request.method === 'course.english.save' && row) {
        row.answer_text = request.text; row.matched = false; row.skipped = request.params.skipped === true
        if (current) baseline.value = request.text
      } else if (request.method === 'course.english.check' && row) {
        row.differences = result.differences || []; row.matched = result.matched ?? null; row.skipped = false; row.error_count = result.error_count ?? (result.matched ? 0 : (row.error_count || 0)+1)
        if (current) {
          if (text.value !== request.text) row.matched = false
          else phase.value = result.matched ? 'answer' : 'correction'
        }
      } else if (request.method === 'course.english.reveal' && row) {
        row.assisted = true
        if (current) {reference.value = result as EnglishReference; hintMode.value = request.revealMode === 'hint' ? 'word' : 'sentence'}
      } else if (request.method === 'course.english.navigate') {
        position.value = Number(request.params.position); bind()
      } else if (request.method === 'course.english.submit' && data.value) {
        data.value.completed = result.completed === true; phase.value = 'result'
      } else if (request.method === 'course.english.request-review' && row) row.status = result.status || row.status
      pending.value = null; failed.value = ''; validationNotice.value = ''; cache()
      if (request.method === 'course.english.check' && result.matched && current && text.value === request.text) {
        // The write is already confirmed. A failed reference read must never replay the check.
        try {reference.value = await engineCall<EnglishReference>('course.english.answer', {study_session_id: studyId, exercise_id: request.exerciseId})}
        catch {reference.value = null}
      }
      return true
    } catch (cause) {
      if (request.method==='course.english.submit' && (cause as {code?:string}).code==='COURSE_INCOMPLETE') {
        pending.value=null;failed.value='';navigationNotice.value='还有未完成项，请继续训练。';cache();return false
      }
      if ((cause as {code?:string}).code==='STUDY_ROUND_SUPERSEDED') {
        // The round was sealed by a course revision reset; further writes can never land.
        superseded.value = true; pending.value = null; cache(); return false
      }
      if (request.method==='course.english.check' && (cause as {code?:string}).code==='ANSWER_EMPTY') {
        // 空输入是校验提示（§7.1）：不进保存失败横幅、不清自动保存，焦点交回输入行。
        pending.value = null; validationNotice.value = (cause as Error).message; cache(); return false
      }
      failed.value = (cause as Error).message; cache(); return false
    }
    finally {
      busy.value = false
      if (!disposed && !suspended && dirty.value && !failed.value && !pending.value && !recovery.value && !superseded.value && !actionInFlight.value) {
        clearTimeout(timer); timer = setTimeout(() => {void save()}, 750)
      }
    }
  }
  function retryPending(): Promise<boolean> {
    if (disposed || suspended) return Promise.resolve(false)
    if (requestFlight) return requestFlight
    if (!pending.value) return Promise.resolve(true)
    const flight = performPending()
    requestFlight = flight
    void flight.finally(() => {if (requestFlight === flight) requestFlight = null})
    return flight
  }
  async function write(method: string, params: Record<string, unknown>, prefix: string, revealMode?: 'hint'|'answer') {
    if (!item.value || pending.value || busy.value || disposed || suspended) return false
    pending.value = {method, exerciseId: item.value.exercise_id, text: text.value, revealMode, params: {study_session_id: studyId, ...params, idempotency_key: makeRequestKey(prefix)}}
    cache(); return retryPending()
  }
  async function saveLatest(skipped: boolean) {
    if (suspended || disposed || recovery.value || superseded.value) return false
    if (requestFlight && !await requestFlight) return false
    if (pending.value && !await retryPending()) return false
    if (!item.value) return false
    if (!dirty.value && (!skipped || item.value.skipped)) return true
    return write('course.english.save', {exercise_id: item.value.exercise_id, answer_text: text.value, expected_version: item.value.answer_version, skipped}, 'english-save')
  }
  async function save(skipped = false): Promise<boolean> {
    clearTimeout(timer)
    if (suspended || disposed || recovery.value) return false
    if (saveFlight) {
      if (!await saveFlight) return false
      return save(skipped)
    }
    const flight = saveLatest(skipped)
    saveFlight = flight
    try {return await flight} finally {if (saveFlight === flight) saveFlight = null}
  }
  async function check() {
    // Retry a previously sent check rather than issuing a fresh attempt after a lost reply.
    if (pending.value?.method === 'course.english.check') {
      if (!await retryPending() || !item.value) return null
      return {matched: item.value.matched, differences: item.value.differences}
    }
    // §7.1：空输入是本地校验提示，不触发引擎（避免Core对无草稿项抛VERSION_CONFLICT或ANSWER_EMPTY落到保存失败横幅）。
    // 只提示、不动 pending/failed：此处 pending 可能是尚未确认的 save/reveal 写入，清掉会丢掉重试路径。
    if (!text.value.trim()) {
      validationNotice.value = '先输入答案；跳过不算答错。'
      return null
    }
    if (!await save() || !item.value) return null
    if (!await write('course.english.check', {exercise_id: item.value.exercise_id, expected_version: item.value.answer_version}, 'english-check')) return null
    return {matched: item.value.matched, differences: item.value.differences}
  }
  async function reveal(mode: 'hint'|'answer' = 'answer') {
    if (!await save() || !item.value) return
    await write('course.english.reveal', {exercise_id: item.value.exercise_id}, 'english-reveal', mode)
  }
  async function move(next: number) {
    if (!data.value || next < 0 || next >= data.value.items.length || !await save()) return false
    return write('course.english.navigate', {position: next, expected_version: data.value.state_version}, 'english-move')
  }
  async function firstIncomplete() {
    const fresh=await engineCall<EnglishStudy>('course.english.get',{study_session_id:studyId})
    if(disposed||suspended)return null
    data.value=fresh
    // Mirror Core submit: an existing review-queue record is already submitted, not a missing draft.
    // Accepting that record does not make it locally correct or resolve its review.
    return fresh.items.findIndex(row=>!['WAITING_REVIEW','PASSED','RECHECKED','REVIEWED'].includes(row.status)&&(row.skipped||!row.answer_text.trim()||!row.matched))
  }
  async function submit() {
    if (pending.value?.method === 'course.english.submit') {await retryPending(); return}
    if (!data.value || !await save()) return
    navigationNotice.value=''
    try {
      const missing=await firstIncomplete()
      if(missing===null)return
      if(missing>=0){
        const moved=await write('course.english.navigate',{position:missing,expected_version:data.value!.state_version},'english-missing')
        if(moved)navigationNotice.value='已返回第 '+(missing+1)+' 项，请完成后再提交。'
        return {incomplete:true,position:missing}
      }
      const submitted=await write('course.english.submit', {expected_versions: Object.fromEntries(data.value!.items.map(i => [i.exercise_id, i.answer_version]))}, 'english-submit')
      if(!submitted&&!pending.value){
        const missing=await firstIncomplete()
        if(missing!==null&&missing>=0)await write('course.english.navigate',{position:missing,expected_version:data.value!.state_version},'english-missing')
      }
    } catch(cause){navigationNotice.value='完成状态暂未确认，请稍后重试；输入已保留。'}
  }
  async function requestReview() {
    if (pending.value?.method === 'course.english.request-review') {await retryPending(); return}
    if (!item.value || !await save()) return
    await write('course.english.request-review', {exercise_id: item.value.exercise_id, expected_version: item.value.answer_version}, 'english-review')
  }
  function restore() {
    if (!recovery.value || !data.value) return
    position.value = data.value.items.findIndex(i => i.exercise_id === recovery.value!.exerciseId); bind()
    tokens.value = recovery.value.text.split(/\s+/); recovery.value = null; cache()
  }
  async function discardRecovery() {
    if (busy.value) return
    try {
      const fresh = await engineCall<EnglishStudy>('course.english.get', {study_session_id: studyId})
      data.value = fresh; position.value = Math.min(fresh.position, fresh.items.length-1); bind()
      recovery.value = null; pending.value = null; failed.value = ''
      try {localStorage.removeItem(cacheKey())} catch { /* best effort */ }
    } catch (cause) {failed.value = (cause as Error).message}
  }
  function exportInput() {
    const blob = new Blob([JSON.stringify({study_session_id: studyId, exercise_id: item.value?.exercise_id, answer_text: text.value, recovery: recovery.value, pending: pending.value}, null, 2)], {type: 'application/json'})
    const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'StudyFlow-英语未保存输入.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function hideHint() {hintMode.value = null}
  function resumeInput() {reference.value = null; hintMode.value = null; phase.value = 'input'}
  function suspend() {suspended = true; clearTimeout(timer); cache()}
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); cache()})
  return {data, item, tokens, position, navigationNotice, validationNotice, busy: actionBusy, actionRunning: actionInFlight, inputLocked: computed(() => actionInFlight.value && actionIntent.value !== 'reveal'), saving: busy, failed, superseded, reference, hintMode, phase, pending, recovery, dirty, load, edited, save, check: exclusive(check, 'check'), reveal: exclusive(reveal, 'reveal'), move: exclusive(move, 'move'), submit: exclusive(submit, 'submit'), requestReview: exclusive(requestReview, 'review'), retryPending, restore, discardRecovery, exportInput, resumeInput, hideHint, suspend}
}
