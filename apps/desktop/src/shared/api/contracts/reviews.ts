

export const QUEUE_PAGE_SIZE = 50

export type QueueItem = {
  id: string
  kind: string
  label: string
  status: string
  study_session_id?: string | null
  batch_id?: string | null
  snapshot_status?: string
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
  action?: string
  answer_text?: string
  review_count: number
  context: { submission_id: string; course_id: string; lesson_id: string; markdown_path: string }
  next_action: string
}

export type QueueData = {
  waiting_review: QueueItem[]
  needs_revision: QueueItem[]
  waiting_retest: QueueItem[]
  counts?: Record<string,number>
  next_cursor?: string|null
  items: QueueItem[]
}
