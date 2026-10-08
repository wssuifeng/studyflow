export interface NotebookBlock {
  source_block_id?: string | null
  id: string; text: string; course_id?: string | null; lesson_id?: string | null
  scope?: 'PLAN' | 'COURSE' | 'LESSON'; quote?: string; source_study_id?: string | null
  course_title?: string | null; lesson_title?: string | null; content_hash?: string | null
}
export interface LegacyNote {id:string; text:string; course_id:string; course_title:string; lesson_id:string; study_session_id:string}
export interface PlanNotebookData {plan_line_id:string; version:number; blocks:NotebookBlock[]; updated_at:string|null; legacy_notes?:LegacyNote[]}
export interface NotebookSaveParams {plan_line_id:string; blocks:NotebookBlock[]; expected_version:number; idempotency_key:string}
