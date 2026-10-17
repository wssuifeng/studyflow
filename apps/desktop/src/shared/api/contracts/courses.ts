import type { ExerciseSubmission } from './learning'
import type { TeachingBlock } from './content'

export type CourseProgress = {
  learning_group?:'PENDING'|'COMPLETED'|'OTHER'
  management_position?:'NORMAL'|'OTHER'
  management_reason?:string
  plan_course_item_id?:string|null
  content_revision?:number
  study_content_revision?:number|null
  source_changed?:boolean
  can_start_new_round?:boolean
  new_round_blocker?:string
  learning_mode?: 'general'|'english'
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
  workspace_key?:string
  protocol_version: string
  course: CourseProgress & { summary: string; subject: string; content_type: string; difficulty: string; source_type: string; plan_line: string | null }
  lessons: LessonDetail[]
  resume_lesson_id: string | null
  next_action: string
}

export type CourseStudyDetailData = CourseDetailData & {
  study: { workspace_key?:string; abandoned_at?:string|null; id: string; revision: number; content_hash: string; progress_version: number; source_changed: boolean; source_available: boolean; is_current: boolean }
}

export type StudyNote = { id: string; lesson_id: string; text: string; version: number; updated_at: string | null }
export type StudyNotesData = { protocol_version: string; study_session_id: string; notes: StudyNote[] }
export type StudyNoteWriteParams = { study_session_id: string; lesson_id: string; text: string; expected_version: number; idempotency_key: string }
export type StudyNoteWriteData = { protocol_version: string; study_session_id: string; note: StudyNote }

export type StudyRestartPreview = {expected_state_hash?:string;reset_current_state?:boolean;expected_training_version?:number;study_session_id:string;course_id:string;revision:number;expected_version:number;expected_content_hash:string|null;can_restart:boolean;blocked_reasons:{code:string;message:string}[];history_retained:boolean;notes_retained:boolean;reading_position_transferred:boolean}
