export type EnglishShortcut = 'sentence-audio'|'word-audio'|'explanation'|'skip'|'previous'|null
export function englishShortcut(event: Pick<KeyboardEvent, 'key'|'code'|'ctrlKey'|'metaKey'|'altKey'|'shiftKey'|'isComposing'|'repeat'>): EnglishShortcut {
  if (event.isComposing || event.repeat || event.altKey || !(event.ctrlKey || event.metaKey)) return null
  if (event.code === 'Quote' || event.key === "'") return event.shiftKey ? 'word-audio' : 'sentence-audio'
  if (event.shiftKey) return null
  if (event.code === 'Semicolon' || event.key === ';') return 'explanation'
  if (event.code === 'Period' || event.key === '.') return 'skip'
  if (event.code === 'Comma' || event.key === ',') return 'previous'
  return null
}
export function inputAdvance(key:string,index:number,values:string[],minimum=values.length):'check'|number|null {
 if(!values[index]?.trim())return null
 const filled=values.filter(value=>value.trim()).length
 if(key==='Enter'&&filled>=minimum)return 'check'
 if(key===' '||key==='Enter')return index<values.length-1?index+1:'check'
 return null
}
export type TokenMove={index:number;caret:'start'|'end'}
/**
 * 词框间自由键盘导航（纯函数，便于单测）：
 *  - ArrowLeft：光标在词首 → 上一词（光标落词尾）；
 *  - ArrowRight：光标在词尾 → 下一词（光标落词首）；
 *  - Backspace：空框或光标在词首 → 上一词（不删除内容）；
 *  - Delete：光标在词尾 → 下一词（不删除内容）。
 * 仅在折叠光标处于边界时触发；框内光标移动、删除与选区操作保留浏览器原生行为。
 * 返回 null 表示交给默认处理；IME 组合态由调用方先行拦截，不在此处理。
 */
export function tokenNavigate(key:string,index:number,value:string,caretStart:number,caretEnd:number,count:number):TokenMove|null {
 const collapsed=caretStart===caretEnd
 const atStart=collapsed&&caretStart===0
 const atEnd=collapsed&&caretEnd===value.length
 if(key==='ArrowLeft'&&atStart&&index>0)return {index:index-1,caret:'end'}
 if(key==='ArrowRight'&&atEnd&&index<count-1)return {index:index+1,caret:'start'}
 if(key==='Backspace'&&index>0&&(value.length===0||atStart))return {index:index-1,caret:'end'}
 if(key==='Delete'&&atEnd&&index<count-1)return {index:index+1,caret:'start'}
 return null
}
/**
 * Ctrl/Meta 修饰的跨词框快速跳转（纯函数，便于单测）：
 *  - Ctrl+ArrowLeft：无视光标位置 → 上一词（光标落词尾）；
 *  - Ctrl+ArrowRight：无视光标位置 → 下一词（光标落词首）；
 *  - Ctrl+Home：首词（光标落词首）；Ctrl+End：末词（光标落词尾）。
 * 裸 Home/End 保留词框内原生行为；首/末词不越界。IME 组合态由调用方先行拦截。
 */
export function tokenJump(key:string,index:number,count:number):TokenMove|null {
 if(count<=0)return null
 if(key==='ArrowLeft'&&index>0)return {index:index-1,caret:'end'}
 if(key==='ArrowRight'&&index<count-1)return {index:index+1,caret:'start'}
 if(key==='Home')return {index:0,caret:'start'}
 if(key==='End')return {index:count-1,caret:'end'}
 return null
}
