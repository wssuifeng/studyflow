import type { CourseProgress } from './courses'

export type Plan = { id: string; name: string; priority: number; status: string; version:number; focus_course_id?:string|null }

export type PlanDetailData = {
  protocol_version: string
  plan: { id: string; name: string; priority: number; status: string; version:number; focus_course_id?:string|null; course_total: number; completed_courses: number; progress_percent: number; today_course_count: number }
  target_date: string
  current_course: CourseProgress | null
  courses: CourseProgress[]
  next_action: string
}
