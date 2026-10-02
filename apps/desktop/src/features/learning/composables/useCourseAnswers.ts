import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { EngineError, studyApi } from '../../../shared/api'
import type { CourseAnswerState, CourseAnswerWriteParams, CourseStudyDetailData } from '../../../shared/api/contracts'
import { makeRequestKey, notify, reportError, storageKey } from '../../../shared/ui'

export type AnswerRow = CourseAnswerState & {
  lessonId: string; lessonTitle: string; title: string; prompt: string; requirements: string
  answer: string; savedAnswer: string
}
type PendingWrite = {operation: 'save' | 'submit'; params: CourseAnswerWriteParams}

export function useCourseAnswers(course: Ref<CourseStudyDetailData | null>) {
  const rows = ref<AnswerRow[]>([])
  const loading = ref(true)
  const failed = ref(false)
  const saveFailed = ref(false)
  const busy = ref('')
  const savedAt = ref('')
  const recovery = ref<Record<string, string> | null>(null)
  const pending = ref<PendingWrite | null>(null)
  const editable = computed(() => rows.value.filter(row => row.action !== 'LOCKED'))
  const dirty = computed(() => editable.value.some(row => row.answer !== row.savedAnswer))
  const missing = computed(() => editable.value.filter(row => !row.answer.trim()))
  const cacheKey = () => storageKey('study-answers:' + course.value!.study.id)
  const requestKey = () => storageKey('study-request:' + course.value!.study.id)
  let timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<boolean> | null = null
  let disposed = false
  let pendingFromStorage = false

  function keepCache() {
    if (!course.value || loading.value) return
    try {
      if (dirty.value) localStorage.setItem(cacheKey(), JSON.stringify({...recovery.value, ...Object.fromEntries(editable.value.map(row => [row.exercise_id, row.answer]))}))
      else if (!pending.value && !recovery.value) localStorage.removeItem(cacheKey())
    } catch { saveFailed.value = true }
  }
  function schedule() {
    clearTimeout(timer)
    if (!disposed && dirty.value && !loading.value && !saveFailed.value && !recovery.value && !pending.value) timer = setTimeout(() => write('save'), 900)
  }
  watch(rows, () => { keepCache(); schedule() }, {deep: true, flush: 'sync'})

  async function load() {
    if (!course.value) return false
    loading.value = true; failed.value = false
    try {
      const sheet = await studyApi.courseAnswers(course.value.course.id, course.value.study.id)
      rows.value = course.value.lessons.flatMap(lesson => lesson.exercises.map(ex => {
        const state = sheet.answers.find(row => row.exercise_id === ex.id)
        if (!state) throw new Error('本轮题目状态不完整，请重新读取课程。')
        const answer = state.draft?.answer_text || (state.action === 'LOCKED' ? state.submission?.answer_text || '' : '')
        return {...state, lessonId: lesson.id, lessonTitle: lesson.title, title: ex.title, prompt: ex.prompt,
          requirements: ex.requirements, answer, savedAnswer: answer}
      }))
      recovery.value = null; pending.value = null; pendingFromStorage = false
      const cached = localStorage.getItem(cacheKey())
      if (cached) {
        const values = JSON.parse(cached)
        if (values && typeof values === 'object' && editable.value.some(row => typeof values[row.exercise_id] === 'string' && values[row.exercise_id] !== row.answer)) recovery.value = values
        else localStorage.removeItem(cacheKey())
      }
      const request = localStorage.getItem(requestKey())
      if (request) {
        const value = JSON.parse(request)
        if (value.params?.study_session_id === course.value.study.id && ['save','submit'].includes(value.operation)) {pending.value = value; pendingFromStorage = true}
      }
      saveFailed.value = false
      return true
    } catch (cause) { failed.value = true; reportError(cause); return false }
    finally { loading.value = false }
  }
  function restoreCache() {
    if (!recovery.value) return
    for (const row of editable.value) if (typeof recovery.value[row.exercise_id] === 'string') row.answer = recovery.value[row.exercise_id]!
    const locked = Object.fromEntries(Object.entries(recovery.value).filter(([id])=>!editable.value.some(row=>row.exercise_id===id)))
    recovery.value = Object.keys(locked).length ? locked : null
    if (recovery.value) notify('部分本机内容对应已提交题，不能覆盖原答案。可导出后使用工作区版本。','info')
    keepCache(); schedule()
  }
  function exportRecovery() {
    const blob = new Blob([JSON.stringify({study_session_id:course.value!.study.id, answers:recovery.value},null,2)], {type:'application/json;charset=utf-8'})
    const url = URL.createObjectURL(blob); const link = document.createElement('a')
    link.href=url; link.download='StudyFlow-未保存内容.json'; link.click(); URL.revokeObjectURL(url)
  }
  function discardCache() { recovery.value = null; localStorage.removeItem(cacheKey()); schedule() }
  function entries(operation: 'save' | 'submit') {
    return editable.value.filter(row => operation === 'submit' || row.answer !== row.savedAnswer).map(row => ({
      exercise_id: row.exercise_id, answer_text: row.answer,
      ...(row.draft ? {submission_id:row.draft.id, expected_version:row.draft.version} : {}),
      ...(row.submission ? {parent_submission_id:row.submission.id} : {}),
    }))
  }
  async function perform(request: PendingWrite) {
    const {operation, params} = request
    keepCache(); busy.value = operation; saveFailed.value = false
    pending.value = request
    try {
      localStorage.setItem(requestKey(), JSON.stringify(request))
      const result = operation === 'save' ? await studyApi.saveCourseAnswers(params) : await studyApi.submitCourseAnswers(params)
      // Do not replace input typed while an autosave was in flight with its older payload.
      const state = await studyApi.courseAnswers(course.value!.course.id, course.value!.study.id)
      for (const row of rows.value) {
        const ack = params.answers.find(item => item.exercise_id === row.exercise_id)
        const next = state.answers.find(item => item.exercise_id === row.exercise_id)
        if (ack) {
          if (pendingFromStorage && row.answer === row.savedAnswer) row.answer = ack.answer_text
          row.savedAnswer = ack.answer_text
          if (recovery.value?.[row.exercise_id] === ack.answer_text) {
            const remaining = {...recovery.value}; delete remaining[row.exercise_id]
            recovery.value = Object.keys(remaining).length ? remaining : null
          }
        }
        if (next) {
          const changedParent = next.submission?.id !== row.submission?.id
          row.action = next.action; row.draft = next.draft; row.submission = next.submission
          if (operation === 'submit' && ack) row.answer = next.submission?.answer_text || ack.answer_text
          else if (changedParent && next.action === 'LOCKED' && row.answer !== (next.submission?.answer_text || '')) {
            recovery.value = {...recovery.value, [row.exercise_id]:row.answer}
          }
        }
      }
      if (recovery.value) {
        const remaining = Object.fromEntries(Object.entries(recovery.value).filter(([id,value])=>{
          const row=rows.value.find(item=>item.exercise_id===id)
          return !row || value !== row.savedAnswer
        }))
        recovery.value=Object.keys(remaining).length ? remaining : null
      }
      pending.value = null; pendingFromStorage = false; localStorage.removeItem(requestKey())
      savedAt.value = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})
      if (operation === 'submit') notify('本次课程学习已提交，等待批改。你可以继续下一门课程。')
      return !!result
    } catch (cause) {
      saveFailed.value = true
      if (cause instanceof EngineError && !['INTERNAL_ERROR','DATABASE_ERROR','CONNECTION_FAILED','BRIDGE_UNAVAILABLE'].includes(cause.code)) {
        pending.value = null; localStorage.removeItem(requestKey())
      }
      reportError(cause); return false
    } finally { busy.value = ''; keepCache(); schedule() }
  }
  async function write(operation: 'save' | 'submit'): Promise<boolean> {
    clearTimeout(timer)
    if (inFlight) { if (!await inFlight) return false; return write(operation) }
    if (failed.value || loading.value || recovery.value || pending.value || saveFailed.value) return false
    if (operation === 'submit' && missing.value.length) return false
    if (operation === 'save' && !dirty.value) return true
    const answers = entries(operation)
    if (!answers.length) return operation === 'save'
    inFlight = perform({operation, params:{course_id:course.value!.course.id, study_session_id:course.value!.study.id,
      answers, idempotency_key:makeRequestKey('course-' + operation)}})
    try { return await inFlight } finally { inFlight = null }
  }
  async function retry() {
    if (inFlight) return inFlight
    if (!pending.value) { keepCache(); return load() }
    inFlight = perform(pending.value)
    try { return await inFlight } finally { inFlight = null }
  }
  function beforeUnload(event: BeforeUnloadEvent) {
    keepCache()
    if (dirty.value || pending.value) {event.preventDefault(); event.returnValue = ''}
  }
  window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); keepCache(); window.removeEventListener('beforeunload', beforeUnload)})
  return {rows, loading, failed, saveFailed, busy, savedAt, recovery, pending, editable, dirty, missing,
    load, write, retry, restoreCache, discardCache, exportRecovery, keepCache}
}
