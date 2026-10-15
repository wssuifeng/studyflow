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
