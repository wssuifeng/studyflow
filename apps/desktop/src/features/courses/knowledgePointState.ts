import type { LessonDetail } from '../../shared/api/contracts'
import type { AnswerRow } from '../learning/composables/useCourseAnswers'

export type KnowledgeState = { kind: string; label: string; symbol: string }
export function knowledgePointState(lesson: LessonDetail, rows: AnswerRow[], current = false): KnowledgeState {
  const answers = rows.filter(row => row.lessonId === lesson.id)
  if (answers.some(row => row.action === 'REVISION')) return {kind: 'revision', label: '待修正', symbol: '!'}
  if (answers.some(row => row.action === 'RETEST')) return {kind: 'retest', label: '待复测', symbol: '↻'}
  if (answers.some(row => row.submission?.status === 'WAITING_REVIEW')) return {kind: 'review', label: '待批改', symbol: '◷'}
  if (answers.length && answers.every(row => row.submission?.status === 'PASSED')) return {kind: 'passed', label: '已通过', symbol: '✓'}
  if (answers.some(row => row.answer.trim() || row.draft)) return {kind: 'draft', label: '有草稿', symbol: '✎'}
  if (lesson.progress.status === 'COMPLETED') return {kind: 'read', label: '已读完', symbol: '✓'}
  if (current || lesson.progress.status === 'IN_PROGRESS') return {kind: 'learning', label: '学习中', symbol: '·'}
  return {kind: 'new', label: '未学习', symbol: '—'}
}
