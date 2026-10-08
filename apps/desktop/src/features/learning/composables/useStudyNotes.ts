import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { EngineError, studyApi } from '../../../shared/api'
import type { CourseStudyDetailData, StudyNoteWriteParams } from '../../../shared/api/contracts'
import { makeRequestKey, reportError, windowStorageKey } from '../../../shared/ui'

type NoteRow = {lessonId: string; text: string; savedText: string; version: number}
export function useStudyNotes(course: Ref<CourseStudyDetailData | null>) {
  const rows = ref<NoteRow[]>([])
  const loading = ref(true)
  const failed = ref(false)
  const saveFailed = ref(false)
  const busy = ref(false)
  const savedAt = ref('')
  const pending = ref<StudyNoteWriteParams | null>(null)
  const recovery = ref<Record<string, string> | null>(null)
  const dirty = computed(() => rows.value.some(row => row.text !== row.savedText))
  const cacheKey = () => windowStorageKey('study-notes:' + course.value!.study.id)
  const requestKey = () => windowStorageKey('study-note-request:' + course.value!.study.id)
  let timer: ReturnType<typeof setTimeout> | undefined
  let inFlight: Promise<boolean> | null = null
  let disposed = false
  let pendingFromStorage = false

  function keepCache() {
    if (!course.value || loading.value) return
    try {
      if (dirty.value || recovery.value) localStorage.setItem(cacheKey(), JSON.stringify({...recovery.value, ...Object.fromEntries(rows.value.filter(row => row.text !== row.savedText).map(row => [row.lessonId, row.text]))}))
      else if (!pending.value) localStorage.removeItem(cacheKey())
    } catch { saveFailed.value = true }
  }
  function schedule() {
    clearTimeout(timer)
    if (!disposed && dirty.value && !loading.value && !failed.value && !busy.value && !saveFailed.value && !pending.value && !recovery.value) timer = setTimeout(() => save(), 900)
  }
  watch(rows, () => {keepCache(); schedule()}, {deep: true, flush: 'sync'})
  async function load() {
    if (!course.value) return false
    keepCache(); loading.value = true; failed.value = false
    try {
      const result = await studyApi.studyNotes(course.value.study.id)
      rows.value = course.value.lessons.map(lesson => {
        const note = result.notes.find(row => row.lesson_id === lesson.id)
        return {lessonId: lesson.id, text: note?.text || '', savedText: note?.text || '', version: note?.version || 0}
      })
      pending.value = null; recovery.value = null; pendingFromStorage = false
      const cached = JSON.parse(localStorage.getItem(cacheKey()) || 'null')
      if (cached && typeof cached === 'object') {
        const differences = Object.fromEntries(Object.entries(cached).filter(([id, text]) => typeof text === 'string' && rows.value.some(row => row.lessonId === id && row.text !== text))) as Record<string, string>
        if (Object.keys(differences).length) recovery.value = differences
        else localStorage.removeItem(cacheKey())
      }
      const request = JSON.parse(localStorage.getItem(requestKey()) || 'null')
      if (request?.study_session_id === course.value.study.id && typeof request.text === 'string') {pending.value = request; pendingFromStorage = true}
      saveFailed.value = false
      return true
    } catch (cause) {failed.value = true; reportError(cause); return false}
    finally {loading.value = false}
  }
  async function perform(params: StudyNoteWriteParams): Promise<boolean> {
    busy.value = true; pending.value = params; saveFailed.value = false; keepCache()
    try {
      localStorage.setItem(requestKey(), JSON.stringify(params))
      const result = await studyApi.saveStudyNote(params)
      if (disposed) return true
      const row = rows.value.find(row => row.lessonId === params.lesson_id)
      if (row) {
        if (pendingFromStorage && row.text === row.savedText) row.text = params.text
        row.savedText = params.text; row.version = result.note.version
      }
      if (recovery.value?.[params.lesson_id] === params.text) {
        const remaining = {...recovery.value}; delete remaining[params.lesson_id]
        recovery.value = Object.keys(remaining).length ? remaining : null
      }
      pending.value = null; pendingFromStorage = false; localStorage.removeItem(requestKey())
      savedAt.value = new Date().toLocaleTimeString('zh-CN', {hour: '2-digit', minute: '2-digit'})
      return true
    } catch (cause) {
      if (disposed) return false
      saveFailed.value = true
      if (cause instanceof EngineError && !['INTERNAL_ERROR','DATABASE_ERROR','DATABASE_LOCKED','DATABASE_DISK_FULL','WORKSPACE_DISK_FULL','DATABASE_READ_ONLY','WORKSPACE_READ_ONLY','DATABASE_CONSTRAINT_ERROR','CONNECTION_FAILED','BRIDGE_UNAVAILABLE'].includes(cause.code)) {
        pending.value = null; localStorage.removeItem(requestKey())
      }
      reportError(cause); return false
    } finally {busy.value = false; keepCache(); schedule()}
  }
  async function save(): Promise<boolean> {
    clearTimeout(timer)
    if (inFlight) {if (!await inFlight) return false; return save()}
    if (disposed || failed.value || loading.value || recovery.value || pending.value || saveFailed.value) return false
    const row = rows.value.find(row => row.text !== row.savedText)
    if (!row) return true
    inFlight = perform({study_session_id: course.value!.study.id, lesson_id: row.lessonId, text: row.text,
      expected_version: row.version, idempotency_key: makeRequestKey('study-note')})
    let ok: boolean
    try {ok = await inFlight} finally {inFlight = null}
    return ok && (!dirty.value || await save())
  }
  async function retry() {
    if (disposed) return false
    if (inFlight) return inFlight
    if (!pending.value) return load()
    inFlight = perform(pending.value)
    try {return await inFlight} finally {inFlight = null}
  }
  function restoreCache() {
    if (!recovery.value) return
    for (const row of rows.value) if (typeof recovery.value[row.lessonId] === 'string') row.text = recovery.value[row.lessonId]!
    recovery.value = null; keepCache(); schedule()
  }
  function discardCache() {recovery.value = null; localStorage.removeItem(cacheKey()); schedule()}
  function exportRecovery() {
    const blob = new Blob([JSON.stringify({study_session_id: course.value!.study.id, notes: recovery.value}, null, 2)], {type: 'application/json;charset=utf-8'})
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = 'StudyFlow-未保存笔记.json'; link.click(); URL.revokeObjectURL(url)
  }
  function suspendAutosave() {disposed = true; clearTimeout(timer); keepCache()}
  function beforeUnload(event: BeforeUnloadEvent) {
    if (disposed) return
    keepCache()
    if (dirty.value || pending.value || recovery.value) {event.preventDefault(); event.returnValue = ''}
  }
  window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {disposed = true; clearTimeout(timer); keepCache(); window.removeEventListener('beforeunload', beforeUnload)})
  return {rows, loading, failed, saveFailed, busy, savedAt, pending, recovery, dirty, load, save, retry, suspendAutosave, restoreCache, discardCache, exportRecovery}
}
export type StudyNotesController = ReturnType<typeof useStudyNotes>
