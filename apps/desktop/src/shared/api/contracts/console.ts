import type { CourseProgress } from './courses'

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
