

export type ExerciseSubmission = {
  id: string
  exercise_id: string
  study_session_id?: string | null
  batch_id?: string | null
  task_id: string | null
  parent_submission_id: string | null
  status: string
  version: number
  attempt_number: number
  attempt_kind: string
  next_action: string
}

export type SubmissionDetailData = ExerciseSubmission & {
  protocol_version: string
  answer_text: string
  source: string
  parent: { id: string; status: string; attempt_number: number } | null
  children: { id: string; status: string; attempt_number: number; attempt_kind: string }[]
  exercise: { id: string; title: string; prompt: string; requirements: string } | null
  lesson: { id: string; title: string; position: number; markdown_path: string } | null
  course: { id: string; title: string; plan_line_id: string | null } | null
  reviews: { id: string; summary: string; detail_markdown: string; rendered_html: string; issue_count: number; decision: string; next_action: string; created_at: string | null }[]
}

export type LearningProgressData = {
  protocol_version: string
  id: string
  course_id: string
  lesson_id: string
  progress_percent: number
  status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED'
  last_position: string
  source: string
  next_action: string
}

export type FollowupSubmission = {
  protocol_version: string
  submission_id: string
  parent_submission_id: string | null
  attempt_number: number
  attempt_kind: string
  status: string
  source: string
  next_action: string
}

export type CourseAnswerEntry = {
  exercise_id: string
  answer_text: string
  submission_id?: string
  expected_version?: number
  parent_submission_id?: string
  task_id?: string
}

export type CourseAnswerState = {
  exercise_id: string
  action: 'FIRST' | 'REVISION' | 'RETEST' | 'LOCKED'
  draft: SubmissionDetailData | null
  submission: SubmissionDetailData | null
}

export type CourseAnswerSheetData = { protocol_version: string; course_id: string; answers: CourseAnswerState[]; next_action: string }

export type CourseAnswerWriteData = { protocol_version: string; course_id: string; status: string; submissions: ExerciseSubmission[]; next_action: string }

export type CourseAnswerWriteParams = { course_id: string; study_session_id?: string; answers: CourseAnswerEntry[]; idempotency_key: string }
