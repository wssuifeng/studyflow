export type ContentStep = {title:string; body:string; body_html:string}
type BaseBlock = {id:string; title:string}
export type TeachingBlock = BaseBlock & (
 | {type:'concept'; body:string; body_html:string}
 | {type:'comparison'; columns:string[]; rows:string[][]}
 | {type:'steps'; items:ContentStep[]}
 | {type:'example'; given:string; given_html:string; steps:ContentStep[]; conclusion:string; conclusion_html:string}
 | {type:'callout'; tone?:'note'|'warning'|'tip'; body:string; body_html:string}
 | {type:'summary'; items:string[]}
 | {type:'practice'; exercise_ids:string[]}
)
