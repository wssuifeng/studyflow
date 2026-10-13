import type {NotebookEntry,NotebookSource,NotebookOperation,NotebookRichNode} from '../../../shared/api/contracts'
import {clone,type Entry,type Source,type RichNode,textOf} from './model'
export function richFromWire(nodes:NotebookRichNode[]):RichNode[]{return nodes.map(n=>({...clone(n),...(n.content?{content:richFromWire(n.content)}:{}),...(n.marks?{marks:n.marks.map(m=>({...clone(m),type:m.type==='citation'?'reference':m.type}))}:{})}))}
export function richToWire(nodes:RichNode[]):NotebookRichNode[]{return nodes.map(n=>({...clone(n),...(n.content?{content:richToWire(n.content)}:{}),...(n.marks?{marks:n.marks.map(m=>({...clone(m),type:m.type==='reference'?'citation':m.type}))}:{})}))}
export function fromWire(e:NotebookEntry):Entry{return {id:e.id,scope:e.scope,courseId:e.course_id,lessonId:e.lesson_id,courseTitle:e.course_title||undefined,lessonTitle:e.lesson_title||undefined,content:richFromWire(e.content)}}
export function toWire(e:Entry):NotebookEntry{return {id:e.id,scope:e.scope,course_id:e.courseId,lesson_id:e.lessonId,content:richToWire(e.content)}}
export function sourceFromWire(s:NotebookSource):Source{return {id:s.id,original:s.original,courseTitle:s.course_title||'历史课程',lessonTitle:s.lesson_title||'历史知识点',version:s.content_hash?.slice(0,8)||'待核验',contentHash:s.content_hash,verification:s.verification||'PENDING',courseId:s.course_id,lessonId:s.lesson_id,studyId:s.source_study_id,blockId:s.source_block_id,sectionId:s.source_section_id}}
export function sourceToWire(s:Source):NotebookSource{return {id:s.id,original:s.original,course_id:s.courseId!,lesson_id:s.lessonId!,source_study_id:s.studyId!,...(s.blockId?{source_block_id:s.blockId}:{}),...(s.sectionId?{source_section_id:s.sectionId}:{})}}
export function fingerprint(entries:Entry[]):string{return JSON.stringify(entries.map(toWire))}
const home=(e:Entry)=>JSON.stringify([e.scope,e.courseId,e.lessonId])
export function operationsBetween(before:Entry[],after:Entry[]):NotebookOperation[]{
 const result:NotebookOperation[]=[],old=new Map(before.map(e=>[e.id,e]));
 for(const e of before)if(!after.some(n=>n.id===e.id))result.push({type:'remove_entry',entry_id:e.id});
 const groups=new Map<string,string[]>();for(const e of before){const key=home(e);if(after.some(n=>n.id===e.id&&home(n)===key)){if(!groups.has(key))groups.set(key,[]);groups.get(key)!.push(e.id)}}
 const previous=new Map<string,string|null>();
 for(const e of after){const key=home(e),anchor=previous.get(key)||null,was=old.get(e.id);if(!was){result.push({type:'insert_entry',entry:toWire(e),after_id:anchor});const list=groups.get(key)||[];list.splice(anchor?list.indexOf(anchor)+1:0,0,e.id);groups.set(key,list)}else{
  if(JSON.stringify(was.content)!==JSON.stringify(e.content))result.push({type:'replace_entry',entry_id:e.id,content:richToWire(e.content)});
  const list=groups.get(key)||[];const at=list.indexOf(e.id),current=at>0?list[at-1]:null;
  if(home(was)!==key||at<0||current!==anchor){result.push({type:'move_entry',entry_id:e.id,scope:e.scope,course_id:e.courseId,lesson_id:e.lessonId,after_id:anchor});for(const l of groups.values()){const i=l.indexOf(e.id);if(i>=0)l.splice(i,1)}list.splice(anchor?list.indexOf(anchor)+1:0,0,e.id);groups.set(key,list)}
 }previous.set(key,e.id)}return result
}
export function blockProjection(entries:Entry[],sources:Record<string,Source>){return entries.map(e=>{const refs:Source[]=[];const walk=(nodes:RichNode[])=>{for(const n of nodes){for(const m of n.marks||[])if(m.type==='reference'&&sources[m.attrs?.sourceId])refs.push(sources[m.attrs?.sourceId]!);walk(n.content||[])}};walk(e.content);const source=refs[0];return {id:e.id,text:textOf(e.content),course_id:source?.courseId||e.courseId,lesson_id:source?.lessonId||e.lessonId,scope:e.scope,quote:source?.original||'',source_study_id:source?.studyId,source_block_id:source?.blockId,source_section_id:source?.sectionId,course_title:e.courseTitle,lesson_title:e.lessonTitle,content_hash:source?.version}})}

export function sourceToExport(s:Source){return {...sourceToWire(s),course_title:s.courseTitle,lesson_title:s.lessonTitle,content_hash:s.contentHash||null,verification:s.verification}}
