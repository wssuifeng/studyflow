import { invoke, isTauri } from '@tauri-apps/api/core'
export { isTauri } from '@tauri-apps/api/core'
import type { CourseAnswerSheetData, CourseAnswerWriteData, CourseAnswerWriteParams, CourseDetailData, DocumentReadData, ExerciseSubmission, FollowupSubmission, LearningProgressData, PlanDetailData, SubmissionDetailData } from './types'

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
      const result = await fetch('/api/engine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-StudyFlow-Client': 'studyflow-ui' },
        body: JSON.stringify(request),
      })
      if (!result.ok) throw new EngineError('BRIDGE_UNAVAILABLE', '本地工作区暂时无法连接', '检查开发服务后点击重试。')
      response = await result.json()
    }
  } catch (cause) {
    if (cause instanceof EngineError) throw cause
    throw new EngineError('CONNECTION_FAILED', '无法连接本地工作区', '请重新打开软件，或恢复开发服务后重试。')
  }
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


export const studyApi = {
  courseAnswers: (courseId: string) => engineCall<CourseAnswerSheetData>('course.answers.get', { course_id: courseId }),
  saveCourseAnswers: (params: CourseAnswerWriteParams) => engineCall<CourseAnswerWriteData>('course.answers.draft.save', params),
  submitCourseAnswers: (params: CourseAnswerWriteParams) => engineCall<CourseAnswerWriteData>('course.answers.submit', params),
  planDetail: (planLineId: string, date?: string) =>
    engineCall<PlanDetailData>('plan.detail', { plan_line_id: planLineId, ...(date ? { date } : {}) }),
  courseDetail: (courseId: string) =>
    engineCall<CourseDetailData>('course.detail', { course_id: courseId }),
  readDocument: (path: string, render = true) =>
    engineCall<DocumentReadData>('document.read', { path, render }),
  submission: (submissionId: string) =>
    engineCall<SubmissionDetailData>('submission.get', { submission_id: submissionId }),
  saveDraft: (params: { exercise_id: string; answer_text: string; submission_id?: string; task_id?: string; idempotency_key?: string; expected_version?: number }) =>
    engineCall<ExerciseSubmission>('submission.draft.save', params),
  submit: (params: { exercise_id?: string; answer_text?: string; submission_id?: string; task_id?: string; idempotency_key?: string; expected_version?: number }) =>
    engineCall<ExerciseSubmission>('submission.submit', params),
  saveLearningProgress: (params: { course_id: string; lesson_id: string; progress_percent: number; last_position?: string }) =>
    engineCall<LearningProgressData>('learning.progress.save', params),
  revise: (params: { parent_submission_id: string; answer_text: string; idempotency_key?: string }) =>
    engineCall<FollowupSubmission>('submission.revise', params),
  retest: (params: { parent_submission_id: string; answer_text: string; idempotency_key?: string }) =>
    engineCall<FollowupSubmission>('submission.retest', params),
}
