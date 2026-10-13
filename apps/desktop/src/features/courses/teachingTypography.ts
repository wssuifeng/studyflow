/** Sanity-preserving display hierarchy inside a semantic teaching section.
 * Input is already sanitized Core HTML; stored course text is never rewritten.
 */
export function normalizeTeachingHeadings(html:string,base:5|6=5){
 const levels=Array.from(html.matchAll(/<h([1-6])(?:\s[^>]*)?>/gi),match=>Number(match[1]))
 if(!levels.length)return html
 const first=Math.min(...levels)
 return html.replace(/(<\/?h)([1-6])(?=[\s>])/gi,(_tag,prefix,level)=>prefix+Math.min(6,base+Number(level)-first))
}
