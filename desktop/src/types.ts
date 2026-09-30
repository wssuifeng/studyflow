export type Plan = { id: string; name: string; priority: number; status: string }
export type CourseProgress = {
  id: string
  title: string
  sequence: number | null
  total: number
  knowledge_total: number
  knowledge_completed: number
  exercise_total: number
  exercise_completed: number
  progress_percent: number
  plan_line?: string | null
  plan_line_id?: string | null
  status?: string
  summary?: string
  reading_percent?: number
  schedule?: { date: string; start_time: string | null; end_time: string | null; status: string } | null
}
export type TodayData = {
  protocol_version: string
  date: string
  primary_task: string | null
  current_course: CourseProgress | null
  courses: CourseProgress[]
  tasks: { id: string; title: string; status: string; kind: string }[]
  queue_counts: { waiting_review: number; needs_revision: number; waiting_retest: number }
  next_action: string
}
export type QueueItem = {
  id: string
  kind: string
  label: string
  status: string
  exercise_id: string
  exercise_title: string
  course_id: string
  course_title: string
  lesson_id: string
  lesson_title: string
  markdown_path: string
  plan_line_id: string | null
  plan_line: string | null
  parent_submission_id: string | null
  attempt_number: number
  attempt_kind: string
  source: string
  answer_text: string
  review_count: number
  context: { submission_id: string; course_id: string; lesson_id: string; markdown_path: string }
  next_action: string
}
export type QueueData = {
  waiting_review: QueueItem[]
  needs_revision: QueueItem[]
  waiting_retest: QueueItem[]
  items: QueueItem[]
}


export type PlanDetailData = {
  protocol_version: string
  plan: { id: string; name: string; priority: number; status: string; course_total: number; completed_courses: number; progress_percent: number; today_course_count: number }
  target_date: string
  current_course: CourseProgress | null
  courses: CourseProgress[]
  next_action: string
}
export type ExerciseSubmission = {
  id: string
  exercise_id: string
  task_id: string | null
  parent_submission_id: string | null
  status: string
  version: number
  attempt_number: number
  attempt_kind: string
  next_action: string
}
export type LessonDetail = {
  id: string
  title: string
  position: number
  markdown_path: string
  summary: string
  document_status: string
  rendered_html: string
  progress: { progress_percent: number; status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED'; last_position: string }
  exercises: {
    id: string
    title: string
    prompt: string
    requirements: string
    type: string
    position: number
    latest_submission: ExerciseSubmission | null
    draft: ExerciseSubmission | null
  }[]
}
export type CourseDetailData = {
  protocol_version: string
  course: CourseProgress & { summary: string; subject: string; content_type: string; difficulty: string; source_type: string; plan_line: string | null }
  lessons: LessonDetail[]
  resume_lesson_id: string | null
  next_action: string
}
export type DocumentReadData = {
  protocol_version: string
  path: string
  status: 'PRESENT'
  markdown: string
  html: string
  file_size: number
  modified_at: string | null
  content_hash: string
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

export type DoctorData = { healthy: boolean; workspace: { root: string; exists: boolean; writable: boolean }; database: { driver: string; status: string; managed_by_app: boolean; reachable: boolean }; next_action: string }

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
export type CourseAnswerWriteParams = { course_id: string; answers: CourseAnswerEntry[]; idempotency_key: string }
