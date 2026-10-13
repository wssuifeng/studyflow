import type { TeachingBlock } from '../../shared/api/contracts/content'

export interface TeachingGroup {
  key: string
  paired: boolean
  blocks: readonly TeachingBlock[]
}
/** Read-only display grouping. It never edits, reorders or manufactures course blocks. */
export function teachingGroups(blocks: readonly TeachingBlock[]): TeachingGroup[] {
  return blocks.map(block => ({key:block.id,paired:false,blocks:[block]}))
}
