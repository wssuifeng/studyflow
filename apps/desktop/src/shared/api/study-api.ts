import { engineCall } from './engine'
import type { CourseAnswerSheetData, CourseAnswerWriteData, CourseAnswerWriteParams, CourseDetailData, CourseStudyDetailData, DocumentReadData, ExerciseSubmission, FollowupSubmission, LearningProgressData, PlanDetailData, SubmissionDetailData } from './contracts'

export const studyApi = {
  courseAnswers: (courseId: string, studyId?: string) => engineCall<CourseAnswerSheetData>('course.answers.get', { course_id: courseId, ...(studyId ? { study_session_id: studyId } : {}) }),
  openCourseStudy: (courseId: string, key: string, newVersion = false) => engineCall<CourseStudyDetailData>('course.study.open', { course_id: courseId, idempotency_key: key, new_version: newVersion }),
  courseStudy: (studyId: string) => engineCall<CourseStudyDetailData>('course.study.get', { study_session_id: studyId }),
  saveStudyProgress: (params: {study_session_id: string; lesson_id: string; progress_percent: number; last_position: string; expected_version: number}) => engineCall<LearningProgressData & {version: number}>('course.study.progress.save', params),
  completeCourseReading: (studyId: string) => engineCall<CourseStudyDetailData>('course.study.reading.complete', { study_session_id: studyId }),
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
