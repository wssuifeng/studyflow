import type { TeachingBlock } from '../../shared/api/contracts/content'

export interface TeachingGroup {
  key: string
  paired: boolean
  blocks: readonly TeachingBlock[]
}
/** Read-only display grouping. It never edits, reorders or manufactures course blocks. */
export function teachingGroups(blocks: readonly TeachingBlock[]): TeachingGroup[] {
  const groups: TeachingGroup[] = []
  for (let index = 0; index < blocks.length; index++) {
    const first = blocks[index]
    const paired = first.type === 'concept' && blocks[index + 1]?.type === 'concept'
    groups.push({ key: first.id, paired, blocks: paired ? [first, blocks[++index]] : [first] })
  }
  return groups
}
