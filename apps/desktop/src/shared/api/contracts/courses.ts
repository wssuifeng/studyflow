import type { ExerciseSubmission } from './learning'
import type { TeachingBlock } from './content'

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
  study_status?: string
  learning_submitted?: boolean
  study_session_id?: string | null
  waiting_count?: number
  feedback_count?: number
  reading_percent?: number
  schedule?: { date: string; start_time: string | null; end_time: string | null; status: string } | null
}

export type LessonDetail = {
  id: string
  title: string
  position: number
  markdown_path: string
  summary: string
  document_status: string
  rendered_html: string
  content_blocks?: TeachingBlock[]
  markdown?: string
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

export type CourseStudyDetailData = CourseDetailData & {
  study: { id: string; revision: number; content_hash: string; progress_version: number; source_changed: boolean; source_available: boolean; is_current: boolean }
}

export type StudyNote = { id: string; lesson_id: string; text: string; version: number; updated_at: string | null }
export type StudyNotesData = { protocol_version: string; study_session_id: string; notes: StudyNote[] }
export type StudyNoteWriteParams = { study_session_id: string; lesson_id: string; text: string; expected_version: number; idempotency_key: string }
export type StudyNoteWriteData = { protocol_version: string; study_session_id: string; note: StudyNote }
