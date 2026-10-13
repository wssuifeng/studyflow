export interface NotebookBlock {
  source_block_id?: string | null
  source_section_id?: string | null
  id: string; text: string; course_id?: string | null; lesson_id?: string | null
  scope?: 'PLAN' | 'COURSE' | 'LESSON'; quote?: string; source_study_id?: string | null
  course_title?: string | null; lesson_title?: string | null; content_hash?: string | null
}
export interface LegacyNote {id:string; text:string; course_id:string; course_title:string; lesson_id:string; study_session_id:string}
export interface PlanNotebookData {plan_line_id:string; version:number; blocks:NotebookBlock[]; updated_at:string|null; legacy_notes?:LegacyNote[]}
export interface NotebookSaveParams {plan_line_id:string; blocks:NotebookBlock[]; expected_version:number; idempotency_key:string}

export interface NotebookRichNode {type:string; text?:string;attrs?:Record<string,unknown>;content?:NotebookRichNode[];marks?:{type:string;attrs?:Record<string,unknown>}[]}
export interface NotebookEntry {id:string;scope:'PLAN'|'COURSE'|'LESSON';course_id:string|null;lesson_id:string|null;content:NotebookRichNode[];course_title?:string|null;lesson_title?:string|null}
export interface NotebookSource {id:string;original:string;course_id:string;lesson_id:string;source_study_id:string;source_block_id?:string;source_section_id?:string;course_title?:string;lesson_title?:string;content_hash?:string;verification?:string}
export type NotebookOperation = {type:'insert_entry';entry:NotebookEntry;after_id?:string|null}|{type:'replace_entry';entry_id:string;content:NotebookRichNode[]}|{type:'remove_entry';entry_id:string}|{type:'move_entry';entry_id:string;scope:'PLAN'|'COURSE'|'LESSON';course_id:string|null;lesson_id:string|null;after_id?:string|null}
export interface NotebookApplyParams {plan_line_id:string;expected_version:number;idempotency_key:string;operations:NotebookOperation[];new_sources:NotebookSource[]}
export interface NotebookApplyResult {plan_line_id:string;version:number;format_version:2;changed_entry_ids:string[];updated_at:string|null;sources?:NotebookSource[]}
export interface NotebookReadResult {plan_line_id:string;version:number;format_version:number;entries:NotebookEntry[];sources:NotebookSource[];citations:{entry_id:string;occurrence_id:string;source_id:string;state:'ORIGINAL'|'PARTIAL'|'EDITED'}[];offset:number;total:number;next_cursor:number|null;updated_at:string|null}
