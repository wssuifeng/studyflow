export type ScopeMode='PLAN'|'COURSE'|'LESSON';
export interface Scope {mode:ScopeMode;courseId?:string;lessonId?:string}
export interface RichNode {type:string;attrs?:Record<string,any>;content?:RichNode[];text?:string;marks?:{type:string;attrs?:Record<string,any>}[]}
export interface Entry {id:string;scope:ScopeMode;courseId:string|null;lessonId:string|null;content:RichNode[];courseTitle?:string;lessonTitle?:string}
export interface Course {id:string;title:string;lessons:{id:string;title:string}[]}
export interface Source {id:string;courseTitle:string;lessonTitle:string;original:string;version:string;contentHash?:string;verification:string;courseId?:string;lessonId?:string;studyId?:string;blockId?:string;sectionId?:string}
export interface LessonGroup {id:string;title:string;entries:Entry[]}
export interface CourseGroup {id:string;title:string;lessons:LessonGroup[]}
export const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value));
export const uid=()=>globalThis.crypto.randomUUID();
export const normalizeText=(text:string)=>text.normalize('NFC').replace(/\r\n?/g,'\n');
export function classifyText(current:string,original:string):'ORIGINAL'|'PARTIAL'|'EDITED'{const c=normalizeText(current),o=normalizeText(original);return c===o?'ORIGINAL':c&&o.includes(c)?'PARTIAL':'EDITED'}
export function visibleEntries(entries:Entry[],scope:Scope){return entries.filter(e=>scope.mode==='PLAN'||e.courseId===scope.courseId&&(scope.mode==='COURSE'||e.lessonId===scope.lessonId&&e.scope==='LESSON'))}
export function applyProjection(all:Entry[],beforeIds:string[],next:Entry[]):Entry[]{
 const seen=new Set<string>();const before=new Set(beforeIds);const hidden=new Set(all.filter(e=>!before.has(e.id)).map(e=>e.id));
 for(const e of next){if(seen.has(e.id))throw Error('duplicate entry ID');if(hidden.has(e.id))throw Error('projection cannot overwrite hidden entry');seen.add(e.id)}
 const output:Entry[]=[];let inserted=false;
 for(const e of all){if(before.has(e.id)){if(!inserted){output.push(...clone(next));inserted=true}}else output.push(clone(e))}
 if(!inserted)output.push(...clone(next));return output;
}
export function groupEntries(entries:Entry[],courses:Course[]):CourseGroup[]{
 const groups:CourseGroup[]=[];const used=new Set<string>();
 const plan=entries.filter(e=>e.scope==='PLAN');if(plan.length){groups.push({id:'__plan',title:'计划随记',lessons:[{id:'__plan',title:'',entries:plan}]});plan.forEach(e=>used.add(e.id))}
 for(const course of courses){const lessons:LessonGroup[]=[];const own=entries.filter(e=>e.courseId===course.id&&e.scope==='COURSE');if(own.length)lessons.push({id:'__course',title:'课程随记',entries:own});
  for(const lesson of course.lessons){const own=entries.filter(e=>e.courseId===course.id&&e.lessonId===lesson.id&&e.scope==='LESSON');if(own.length)lessons.push({id:lesson.id,title:lesson.title,entries:own})}
  const old=entries.filter(e=>e.courseId===course.id&&!lessons.some(l=>l.entries.some(x=>x.id===e.id))&&e.scope!=='PLAN');if(old.length)lessons.push({id:'__history',title:'历史知识点笔记',entries:old});
  if(lessons.length){groups.push({id:course.id,title:course.title,lessons});lessons.forEach(l=>l.entries.forEach(e=>used.add(e.id)))}
 }
 const historical=entries.filter(e=>!used.has(e.id));if(historical.length)groups.push({id:'__history',title:'历史课程笔记',lessons:[{id:'__history',title:'',entries:historical}]});return groups;
}
export function entryFromScope(scope:Scope,content:RichNode[]=[{type:'paragraph'}]):Entry{return {id:uid(),scope:scope.mode,courseId:scope.mode==='PLAN'?null:scope.courseId||null,lessonId:scope.mode==='LESSON'?scope.lessonId||null:null,content}}
export function textOf(nodes:RichNode[]):string{return nodes.map(n=>n.text??(n.content?textOf(n.content):n.type==='hardBreak'?'\n':'')).join('')}
export const isBlank=(entry:Entry)=>!textOf(entry.content).trim();
export class MemoryHistory{
 private snapshots:Entry[][];private cursor=0;private lastGroup:string|undefined;private lastTime=0;
 constructor(initial:Entry[]){this.snapshots=[clone(initial)]}
 push(next:Entry[],typingGroup?:string){if(JSON.stringify(this.snapshots[this.cursor])===JSON.stringify(next))return;const now=Date.now();const merge=typingGroup&&typingGroup===this.lastGroup&&now-this.lastTime<850&&this.cursor===this.snapshots.length-1&&this.cursor>0;this.snapshots=this.snapshots.slice(0,this.cursor+1);if(merge)this.snapshots[this.cursor]=clone(next);else{this.snapshots.push(clone(next));if(this.snapshots.length>120)this.snapshots.shift();this.cursor=this.snapshots.length-1}this.lastGroup=typingGroup;this.lastTime=now}
 breakGroup(){this.lastGroup=undefined;this.lastTime=0}
 undo(){this.breakGroup();if(this.cursor>0)this.cursor--;return clone(this.snapshots[this.cursor])}
 redo(){this.breakGroup();if(this.cursor<this.snapshots.length-1)this.cursor++;return clone(this.snapshots[this.cursor])}
 get canUndo(){return this.cursor>0}get canRedo(){return this.cursor<this.snapshots.length-1}
}
