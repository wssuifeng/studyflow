import {computed, onBeforeUnmount, shallowRef, watch} from 'vue'
import {engineCall, EngineError} from '../../shared/api'
import {makeRequestKey, windowStorageKey} from '../../shared/ui'

export interface PracticeOption { id: string; text: string }
export type PracticeAnswer = string | Record<string, string>
export interface PracticeQuestion {
  id: string; prompt: string; options?: PracticeOption[]
  parts?: ({text: string} | {blank_id: string})[]
}
interface ResultItem {
  id: string; correct: boolean; explanation: string; evidence?: string[]
  correct_option_id?: string; blanks?: {id: string; correct: boolean; accepted: string}[]
}
interface PracticeState {
  version: number; answers: Record<string, PracticeAnswer>; position: number
  result: {correct: number; total: number; items: ResultItem[]} | null
}
interface PracticeView extends PracticeState {
  title: string; questions: PracticeQuestion[]; read_only: boolean
  paragraphs?: {id: string; text: string}[]
  audio?: {sha256: string; format: string}
  transcript?: string
}
export interface AuthorPreviewContext {package: Record<string, unknown>; lesson_id: string; exercise_id: string}
interface PracticeReceipt extends PracticeState {course_submitted: boolean}
interface Draft extends Pick<PracticeState, 'answers' | 'position'> {version: number}
interface Pending extends Draft {key: string; confirm: boolean}

export function usePractice(studyId: string, exerciseId: string, kind: 'reading' | 'listening', finished: (submitted: boolean) => void, preview?: AuthorPreviewContext) {
  const params = {study_session_id: studyId, exercise_id: exerciseId}
  const method = `practice.${kind}`
  const storageKey = windowStorageKey(`practice:${studyId}:${exerciseId}`)
  const view = shallowRef<PracticeView>()
  const draft = shallowRef<Draft>({answers: {}, position: 0, version: 0})
  const pending = shallowRef<Pending>()
  const busy = shallowRef(false)
  const error = shallowRef('')
  const conflict = shallowRef(false)
  const dirty = computed(() => !!view.value && (!view.value.read_only || conflict.value) && (draft.value.position !== view.value.position ||
    JSON.stringify(draft.value.answers) !== JSON.stringify(view.value.answers)))
  let inFlight: Promise<boolean> | undefined
  let disposed = false
  let timer: ReturnType<typeof setTimeout> | undefined

  function cache() {
    if (preview) return
    try {
      if (dirty.value || pending.value) localStorage.setItem(storageKey, JSON.stringify({draft: draft.value, pending: pending.value}))
      else localStorage.removeItem(storageKey)
    } catch { /* The exit guard still retains the in-memory draft. */ }
  }

  async function load(useCache = true) {
    busy.value = true
    error.value = ''
    try {
      const state = preview ? await engineCall<PracticeView>('practice.author.preview', {...preview}) : await engineCall<PracticeView>(`${method}.get`, params)
      if (disposed) return
      view.value = state
      draft.value = {answers: state.answers, position: state.position, version: state.version}
      pending.value = undefined
      conflict.value = false
      if (useCache && !preview) {
        const cached = localStorage.getItem(storageKey)
        if (cached) {
          const saved = JSON.parse(cached) as {draft: Draft; pending?: Pending}
          draft.value = saved.draft
          pending.value = saved.pending
          conflict.value = !saved.pending && (saved.draft.version !== state.version || state.read_only)
          if (conflict.value) error.value = '工作区已有更新。可以复制本机输入，或载入工作区版本。'
        }
      } else cache()
    } catch (cause) { error.value = cause instanceof Error ? cause.message : '无法读取题组。' }
    finally { busy.value = false }
  }

  async function send(request: Pending) {
    busy.value = true
    error.value = ''
    pending.value = request
    cache()
    try {
      const state = await engineCall<PracticeReceipt>(`${method}.${request.confirm ? 'confirm' : 'save'}`, {
        ...params, answers: request.answers, position: request.position,
        expected_version: request.version, idempotency_key: request.key,
      })
      if (disposed || !view.value) return true
      view.value = {...view.value, ...state, read_only: !!state.result}
      draft.value = {answers: state.answers, position: state.position, version: state.version}
      pending.value = undefined
      if (request.confirm) finished(state.course_submitted)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : '保存未确认。'
      if (cause instanceof EngineError) {
        conflict.value = ['VERSION_CONFLICT', 'STUDY_ROUND_SUPERSEDED', 'INVALID_STATE_TRANSITION'].includes(cause.code)
        if (conflict.value || ['INVALID_ARGUMENT', 'INCOMPLETE_READING_GROUP', 'INCOMPLETE_LISTENING_GROUP'].includes(cause.code)) pending.value = undefined
      }
      return false
    } finally { busy.value = false; cache() }
  }

  async function save(confirm = false): Promise<boolean> {
    clearTimeout(timer)
    if (inFlight) return await inFlight && (!confirm || save(true))
    if (conflict.value) return false
    if (preview) {
      if (!confirm) return true
      busy.value = true
      error.value = ''
      try {
        view.value = await engineCall<PracticeView>('practice.author.preview', {...preview, answers: draft.value.answers})
        return true
      } catch (cause) {error.value = cause instanceof Error ? cause.message : '无法预览解析。'; return false}
      finally {busy.value = false}
    }
    if (pending.value) {
      const result = await (inFlight = send(pending.value)).finally(() => {inFlight = undefined})
      return result && (!confirm || !!view.value?.result || save(true))
    }
    if (!view.value || view.value.read_only || (!confirm && !dirty.value)) return true
    inFlight = send({...draft.value, key: makeRequestKey('practice'), confirm})
    try { return await inFlight } finally { inFlight = undefined }
  }

  function select(questionId: string, answer: PracticeAnswer) {
    draft.value = {...draft.value, answers: {...draft.value.answers, [questionId]: answer}}
  }
  function move(position: number) {draft.value = {...draft.value, position}}
  watch(draft, () => {
    if (busy.value) return
    cache()
    clearTimeout(timer)
    if (!preview && dirty.value && !pending.value && !conflict.value && !view.value?.read_only) timer = setTimeout(() => void save(), 900)
  }, {flush: 'sync'})
  function beforeUnload(event: BeforeUnloadEvent) {
    if (!preview && (dirty.value || pending.value)) {event.preventDefault(); event.returnValue = ''}
  }
  window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {
    clearTimeout(timer)
    cache()
    disposed = true
    window.removeEventListener('beforeunload', beforeUnload)
  })
  return {view, draft, pending, busy, error, conflict, dirty, load, save, select, move, params}
}
