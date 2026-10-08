import {emit} from '@tauri-apps/api/event'
import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { EngineError, studyApi, isTauri } from '../../../shared/api'
import type { CourseAnswerState, CourseAnswerWriteParams, CourseStudyDetailData } from '../../../shared/api/contracts'
import { makeRequestKey, notify, reportError, windowStorageKey } from '../../../shared/ui'

export type AnswerRow = CourseAnswerState & {
  lessonId: string; lessonTitle: string; title: string; prompt: string; requirements: string
  answer: string; savedAnswer: string
}
type PendingWrite = {operation: 'save' | 'submit'; params: CourseAnswerWriteParams}

export function useCourseAnswers(course: Ref<CourseStudyDetailData | null>, enabled:Ref<boolean> = ref(true)) {
  const rows = ref<AnswerRow[]>([])
  const loading = ref(true)
  const failed = ref(false)
  const saveFailed = ref(false)
  const busy = ref('')
  const savedAt = ref('')
  const cacheUnavailable=ref(false)
  function cacheRead(key:string){try{return localStorage.getItem(key)}catch{cacheUnavailable.value=true;return null}}
  function cacheRemove(key:string){try{localStorage.removeItem(key)}catch{cacheUnavailable.value=true}}
  function cacheWrite(key:string,text:string){try{localStorage.setItem(key,text)}catch{cacheUnavailable.value=true}}
  const recovery = ref<Record<string, string> | null>(null)
  const pending = ref<PendingWrite | null>(null)
  const editable = computed(() => rows.value.filter(row => !['LOCKED','WAITING_RETEST_TASK'].includes(row.action)))
  const dirty = computed(() => editable.value.some(row => row.answer !== row.savedAnswer))
  const missing = computed(() => editable.value.filter(row => !row.answer.trim()))
  const cacheKey = () => windowStorageKey('study-answers:' + course.value!.study.id)
  const requestKey = () => windowStorageKey('study-request:' + course.value!.study.id)
  let timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<boolean> | null = null
  let disposed = false
  let pendingFromStorage = false

  function keepCache() {
    if (!course.value || loading.value) return
    try {
      if (dirty.value) localStorage.setItem(cacheKey(), JSON.stringify({...recovery.value, ...Object.fromEntries(editable.value.map(row => [row.exercise_id, row.answer]))}))
      else if (!pending.value && !recovery.value) cacheRemove(cacheKey())
    } catch { cacheUnavailable.value = true }
  }
  function schedule() {
    clearTimeout(timer)
    if (enabled.value && !disposed && dirty.value && !loading.value && !saveFailed.value && !recovery.value && !pending.value) timer = setTimeout(() => write('save'), 900)
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
        return {...state, lessonId: lesson.id, lessonTitle: lesson.title, title: state.retest_task?.title || ex.title, prompt: state.retest_task?.prompt || ex.prompt,
          requirements: state.retest_task?.requirements || ex.requirements, answer, savedAnswer: answer}
      }))
      recovery.value = null; pending.value = null; pendingFromStorage = false
      const cached = cacheRead(cacheKey())
      if (cached) {
        const values = JSON.parse(cached)
        if (values && typeof values === 'object' && editable.value.some(row => typeof values[row.exercise_id] === 'string' && values[row.exercise_id] !== row.answer)) recovery.value = values
        else cacheRemove(cacheKey())
      }
      const request = cacheRead(requestKey())
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
  function discardCache() { recovery.value = null; cacheRemove(cacheKey()); schedule() }
  function entries(operation: 'save' | 'submit') {
    return editable.value.filter(row => operation === 'submit' || row.answer !== row.savedAnswer).map(row => ({
      exercise_id: row.exercise_id, answer_text: row.answer,
      ...(row.draft ? {submission_id:row.draft.id, expected_version:row.draft.version} : {}),
      ...(row.submission ? {parent_submission_id:row.submission.id} : {}),
      ...(row.retest_task ? {retest_task_id:row.retest_task.id} : {}),
    }))
  }
  async function perform(request: PendingWrite) {
    const {operation, params} = request
    keepCache(); busy.value = operation; saveFailed.value = false
    pending.value = request
    try {
      cacheWrite(requestKey(), JSON.stringify(request))
      const result = operation === 'save' ? await studyApi.saveCourseAnswers(params) : await studyApi.submitCourseAnswers(params)
      if (disposed) return true
      // Do not replace input typed while an autosave was in flight with its older payload.
      const state = await studyApi.courseAnswers(course.value!.course.id, course.value!.study.id)
      if (disposed) return true
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
          row.action = next.action; row.retest_task=next.retest_task; row.draft = next.draft; row.submission = next.submission
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
      pending.value = null; pendingFromStorage = false; cacheRemove(requestKey())
      savedAt.value = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})
      if (isTauri()) void emit('studyflow-tool-saved',{tool:'exercises',studyId:params.study_session_id}).catch(() => {})
      if (operation === 'submit') notify('本次课程学习已提交，等待批改。你可以继续下一门课程。')
      return !!result
    } catch (cause) {
      if (disposed) return false
      saveFailed.value = true
      if (cause instanceof EngineError && !['INTERNAL_ERROR','DATABASE_ERROR','DATABASE_LOCKED','DATABASE_DISK_FULL','WORKSPACE_DISK_FULL','DATABASE_READ_ONLY','WORKSPACE_READ_ONLY','DATABASE_CONSTRAINT_ERROR','CONNECTION_FAILED','BRIDGE_UNAVAILABLE','ENGINE_TIMEOUT','ENGINE_BUSY','ENGINE_UNCONFIRMED','INVALID_RESPONSE'].includes(cause.code)) {
        pending.value = null; cacheRemove(requestKey())
      }
      reportError(cause); return false
    } finally { busy.value = ''; keepCache(); schedule() }
  }
  async function write(operation: 'save' | 'submit'): Promise<boolean> {
    clearTimeout(timer)
    if (inFlight) { if (!await inFlight) return false; return write(operation) }
    if (disposed || failed.value || loading.value || recovery.value || pending.value || saveFailed.value) return false
    if (!enabled.value && operation === 'save') return !dirty.value
    if (operation === 'submit' && missing.value.length) return false
    if (operation === 'save' && !dirty.value) return true
    const answers = entries(operation)
    if (!answers.length) return operation === 'save'
    inFlight = perform({operation, params:{course_id:course.value!.course.id, study_session_id:course.value!.study.id,
      answers, idempotency_key:makeRequestKey('course-' + operation)}})
    try { return await inFlight } finally { inFlight = null }
  }
  async function retry() {
    if (disposed || !enabled.value) return false
    if (inFlight) return inFlight
    if (!pending.value) { keepCache(); return load() }
    inFlight = perform(pending.value)
    try { return await inFlight } finally { inFlight = null }
  }
  watch(enabled,owner => {clearTimeout(timer);if (owner && !dirty.value && !pending.value && !recovery.value) void load()})
  function suspendAutosave() {disposed = true; clearTimeout(timer); keepCache()}
  function beforeUnload(event: BeforeUnloadEvent) {
    if (disposed) return
    keepCache()
    if (dirty.value || pending.value) {event.preventDefault(); event.returnValue = ''}
  }
  window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); keepCache(); window.removeEventListener('beforeunload', beforeUnload)})
  return {cacheUnavailable,rows, loading, failed, saveFailed, busy, savedAt, recovery, pending, editable, dirty, missing,
    load, write, retry, suspendAutosave, restoreCache, discardCache, exportRecovery, keepCache}
}
