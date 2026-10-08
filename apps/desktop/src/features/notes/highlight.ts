import type {NotebookBlock} from '../../shared/api/contracts'
// Decorate a temporary DOM only. Never rewrite frozen HTML or source Markdown.
export function highlightNotebookExcerpts(html:string,blocks:NotebookBlock[],studyId:string,lessonId:string):string {
 const quotes=blocks.filter(b=>b.quote&&b.source_study_id===studyId&&b.lesson_id===lessonId)
 if(!quotes.length)return html
 const doc=new DOMParser().parseFromString(html,'text/html'),walker=doc.createTreeWalker(doc.body,NodeFilter.SHOW_TEXT)
 const nodes:{node:Text;start:number;end:number}[]=[];let raw='',next:Node|null
 while((next=walker.nextNode())){const text=next as Text,start=raw.length;raw+=text.data;nodes.push({node:text,start,end:raw.length})}
 let normalized='';const offsets:number[]=[]
 for(let i=0;i<raw.length;i++){const char=raw[i]!;if(/\s/.test(char)){if(normalized&&!normalized.endsWith(' ')){normalized+=' ';offsets.push(i)}}else{normalized+=char;offsets.push(i)}}
 const matches:{start:number;end:number;id:string}[]=[]
 for(const b of quotes){const needle=b.quote!.replace(/\s+/g,' ').trim();if(!needle)continue;let start=0,index:number
  while((index=normalized.indexOf(needle,start))>=0){matches.push({start:offsets[index]!,end:offsets[index+needle.length-1]!+1,id:b.id});start=index+needle.length}
 }
 for(const {node,start,end} of nodes){
  const ranges=matches.filter(m=>m.start<end&&m.end>start).map(m=>({start:Math.max(0,m.start-start),end:Math.min(end-start,m.end-start),id:m.id})).sort((a,b)=>a.start-b.start)
  if(!ranges.length)continue
  const merged:typeof ranges=[];for(const r of ranges){const last=merged[merged.length-1];if(last&&r.start<=last.end)last.end=Math.max(last.end,r.end);else merged.push({...r})}
  const fragment=doc.createDocumentFragment();let position=0
  for(const r of merged){fragment.append(doc.createTextNode(node.data.slice(position,r.start)));const mark=doc.createElement('mark');mark.className='notebook-highlight';mark.dataset.noteId=r.id;mark.title='这段内容已记入计划笔记';mark.textContent=node.data.slice(r.start,r.end);fragment.append(mark);position=r.end}
  fragment.append(doc.createTextNode(node.data.slice(position)));node.replaceWith(fragment)
 }
 return doc.body.innerHTML
}
