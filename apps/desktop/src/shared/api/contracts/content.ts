export type ContentStep = {title:string; body:string; body_html:string}
export type TeachingSection={id:string;title:string;role:'main'|'supplement';body:string;body_html:string;summary?:string;summary_html?:string;children?:TeachingSection[]}
type BaseBlock = {id:string; title:string}
export type TeachingBlock = BaseBlock & (
 | {type:'details'; summary:string;summary_html:string;body:string;body_html:string}
 | {type:'concept'; body?:string; body_html?:string; sections?:TeachingSection[]}
 | {type:'comparison'; columns:string[]; rows:string[][]}
 | {type:'steps'; items:ContentStep[]}
 | {type:'example'; given:string; given_html:string; steps:ContentStep[]; conclusion:string; conclusion_html:string}
 | {type:'callout'; tone?:'note'|'warning'|'tip'; body:string; body_html:string}
 | {type:'summary'; items:string[]}
 | {type:'practice'; exercise_ids:string[]}
)
