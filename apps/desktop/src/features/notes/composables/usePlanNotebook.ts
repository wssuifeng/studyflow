import {computed,onBeforeUnmount,ref,shallowRef,watch,type Ref} from 'vue'
import {EngineError,studyApi,isTauri} from '../../../shared/api'
import {makeRequestKey,reportError,windowStorageKey} from '../../../shared/ui'
import type {NotebookApplyParams,NotebookBlock} from '../../../shared/api/contracts'
import {emit} from '@tauri-apps/api/event'
import {clone,MemoryHistory,uid,type Entry,type Source,type Course} from '../editor/model'
import {fromWire,toWire,sourceFromWire,sourceToWire,sourceToExport,fingerprint,operationsBetween,blockProjection} from '../editor/wire'
interface Snapshot {entries:Entry[];sources:Record<string,Source>;baseline:Entry[]}
interface Pending {params:NotebookApplyParams;snapshot:Snapshot}
export interface NoteConflict {id:string;local?:Entry;remote?:Entry}
export {fingerprint as notebookFingerprint} from '../editor/wire'
export function usePlanNotebook(planId:Ref<string|undefined>,enabled:Ref<boolean>=ref(true)){
 const entries=shallowRef<Entry[]>([]),sources=ref<Record<string,Source>>({}),courses=ref<Course[]>([]),version=ref(0)
 const loading=ref(false),failed=ref(false),saveFailed=ref(false),busy=ref(false),savedAt=ref(''),cacheUnreadable=ref(false),cacheFailed=ref(false),composing=ref(false)
 const rejected=ref<Pending|null>(null);const pending=ref<Pending|null>(null),recovery=ref<Snapshot|null>(null),conflicts=ref<NoteConflict[]>([])
 const baseline=shallowRef<Entry[]>([]);let activePid='',generation=0,disposed=false,flight:Promise<boolean>|null=null,history=new MemoryHistory([]),rawRecovery:string|null=null,rawPending:string|null=null,ackSources=new Set<string>()
 let timer:ReturnType<typeof setTimeout>|undefined,cacheTimer:ReturnType<typeof setTimeout>|undefined
 const available=computed(()=>!!planId.value),editable=computed(()=>available.value&&enabled.value),dirty=computed(()=>fingerprint(entries.value)!==fingerprint(baseline.value))
 const blocks=computed(()=>blockProjection(entries.value,sources.value)),canUndo=ref(false),canRedo=ref(false)
 const key=(pid:string,kind:string)=>windowStorageKey('notebook:'+pid+':v2:'+kind)
 const snapshot=():Snapshot=>({entries:clone(entries.value),sources:clone(sources.value),baseline:clone(baseline.value)})
 function put(k:string,v:unknown){try{localStorage.setItem(k,JSON.stringify(v));cacheFailed.value=false;return true}catch{cacheFailed.value=true;return false}}
 function remove(k:string){try{localStorage.removeItem(k)}catch{cacheFailed.value=true}}
 function cache(){if(!activePid||loading.value||composing.value||cacheUnreadable.value)return;if(dirty.value||pending.value)put(key(activePid,'recovery'),snapshot());else if(!recovery.value)remove(key(activePid,'recovery'))}
 function schedule(){clearTimeout(timer);if(composing.value)return;if(!cacheTimer)cacheTimer=setTimeout(()=>{cacheTimer=undefined;cache()},5000)
  if(enabled.value&&dirty.value&&!disposed&&!loading.value&&!busy.value&&!failed.value&&!saveFailed.value&&!pending.value&&!recovery.value&&!cacheUnreadable.value)timer=setTimeout(()=>{cache();void save()},850)}
 watch(entries,schedule,{deep:true,flush:'sync'})
 function validSnapshot(s:unknown):s is Snapshot{const v=s as Snapshot;return !!v&&Array.isArray(v.entries)&&v.entries.every(e=>e&&typeof e.id==='string'&&Array.isArray(e.content))&&Array.isArray(v.baseline)&&!!v.sources&&typeof v.sources==='object'}
 async function readAll(pid:string){const first=await studyApi.readPlanNotebook(pid,{limit:100});const result={...first,entries:[...first.entries],sources:[...first.sources]};let cursor=first.next_cursor
  while(cursor!==null){const next=await studyApi.readPlanNotebook(pid,{offset:cursor,limit:100,expected_version:first.version});result.entries.push(...next.entries);result.sources.push(...next.sources);cursor=next.next_cursor}
  return result}
 function adopt(data:Awaited<ReturnType<typeof readAll>>){baseline.value=data.entries.map(fromWire);entries.value=clone(baseline.value);sources.value=Object.fromEntries(data.sources.map(s=>[s.id,sourceFromWire(s)]));ackSources=new Set(data.sources.map(s=>s.id));version.value=data.version;history=new MemoryHistory(entries.value);canUndo.value=false;canRedo.value=false}
 async function load(force=false){if(!activePid||disposed||(!force&&(dirty.value||pending.value||recovery.value)))return false;const pid=activePid,token=++generation;loading.value=true;failed.value=false
  try{const data=await readAll(pid);if(disposed||token!==generation||activePid!==pid)return false;adopt(data);pending.value=null;recovery.value=null;saveFailed.value=false;cacheUnreadable.value=false;conflicts.value=[]
   try{rawPending=localStorage.getItem(key(pid,'pending'));rawRecovery=localStorage.getItem(key(pid,'recovery'))
    if(rawPending){const p=JSON.parse(rawPending);if(!p?.params||p.params.plan_line_id!==pid||!Array.isArray(p.params.operations)||typeof p.params.idempotency_key!=='string'||!validSnapshot(p.snapshot))throw Error('Invalid pending notebook');pending.value=p}
    if(rawRecovery){const r=JSON.parse(rawRecovery);if(!validSnapshot(r))throw Error('Invalid notebook recovery');if(fingerprint(r.entries)!==fingerprint(baseline.value))recovery.value=r}
    const oldPending=localStorage.getItem(windowStorageKey('notebook:'+pid+':pending')),oldRecovery=localStorage.getItem(windowStorageKey('notebook:'+pid+':recovery'))
    if(oldPending||oldRecovery){rawRecovery=JSON.stringify({v2:rawRecovery,legacy_recovery:oldRecovery,legacy_pending:oldPending});cacheUnreadable.value=true}
   }catch{cacheUnreadable.value=true}
   return true
  }catch(cause){if(token===generation&&!disposed){failed.value=true;reportError(cause)}return false}finally{if(token===generation){loading.value=false;schedule()}}}
 async function perform(request:Pending){const pid=request.params.plan_line_id,token=generation,current=()=>!disposed&&token===generation&&activePid===pid;busy.value=true;saveFailed.value=false;rejected.value=null;pending.value=clone(request);put(key(pid,'pending'),request)
  try{const result=await studyApi.applyPlanNotebook(request.params);remove(key(pid,'pending'));if(!current())return true
   const acknowledgeSources=()=>{for(const s of request.params.new_sources)ackSources.add(s.id);for(const s of result.sources||[])sources.value[s.id]=sourceFromWire(s)}
   if(result.version<=version.value){pending.value=null;if(recovery.value&&fingerprint(recovery.value.entries)===fingerprint(request.snapshot.entries))recovery.value=null;acknowledgeSources();cache();if(isTauri())try{await emit('studyflow-tool-saved',{tool:'notes',planId:pid})}catch{}return true}
   const restoring=fingerprint(entries.value)===fingerprint(baseline.value)&&!!recovery.value
   version.value=result.version;baseline.value=clone(request.snapshot.entries)
   if(restoring){entries.value=clone(request.snapshot.entries);sources.value={...clone(request.snapshot.sources),...sources.value};history=new MemoryHistory(entries.value)}
   acknowledgeSources();pending.value=null;if(recovery.value&&fingerprint(recovery.value.entries)===fingerprint(baseline.value))recovery.value=null
   savedAt.value=new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});cache();if(isTauri())try{await emit('studyflow-tool-saved',{tool:'notes',planId:pid})}catch{}return true
  }catch(cause){if(current()){saveFailed.value=true;cache();if(cause instanceof EngineError&&cause.code==='VERSION_CONFLICT'){pending.value=null;remove(key(pid,'pending'))}else if(cause instanceof EngineError&&['INVALID_ARGUMENT','NOTEBOOK_SOURCE_IMMUTABLE','NOTEBOOK_FORMAT_UNSUPPORTED','NOTEBOOK_FORMAT_UPGRADE_REQUIRED','OBJECT_NOT_FOUND'].includes(cause.code)){rejected.value=clone(request);pending.value=null;remove(key(pid,'pending'))}reportError(cause)}return false
  }finally{if(current()){busy.value=false;schedule()}}}
 async function save():Promise<boolean>{clearTimeout(timer);cache();if(disposed||composing.value)return false;if(!enabled.value)return !dirty.value&&!pending.value&&!recovery.value
  const token=generation;if(flight){if(!await flight)return false;return token===generation?save():true}
  if(loading.value||failed.value||recovery.value||saveFailed.value&&!rejected.value||pending.value||cacheUnreadable.value)return false;if(!dirty.value){if(rejected.value){rejected.value=null;saveFailed.value=false;cache()}return true}if(!activePid)return false
  const shot=snapshot(),usedSources=new Set<string>();const refs=(nodes:Entry['content'])=>{for(const node of nodes){for(const mark of node.marks||[])if(mark.type==='reference')usedSources.add(mark.attrs?.sourceId);refs(node.content||[])}};for(const entry of shot.entries)refs(entry.content);const params:NotebookApplyParams={plan_line_id:activePid,expected_version:version.value,idempotency_key:makeRequestKey('plan-notebook-v2'),operations:operationsBetween(baseline.value,shot.entries),new_sources:Object.values(shot.sources).filter(s=>!ackSources.has(s.id)&&usedSources.has(s.id)).map(sourceToWire)}
  const request=perform({params,snapshot:shot});flight=request;let ok:boolean;try{ok=await request}finally{if(flight===request)flight=null}return ok&&(token!==generation||!dirty.value||await save())}
 async function retry():Promise<boolean>{if(disposed||!enabled.value||composing.value)return false;if(flight)return flight;if(!pending.value)return rejected.value?save():refreshConflict();const request=perform(clone(pending.value));flight=request;try{return await request}finally{if(flight===request)flight=null}}
 async function refreshConflict(){if(!activePid||disposed||busy.value)return false;const pid=activePid,token=generation;busy.value=true
  try{const latest=await readAll(pid);if(disposed||token!==generation||pid!==activePid)return false;const local=snapshot(),changed=dirty.value;adopt(latest);if(changed&&fingerprint(local.entries)!==fingerprint(baseline.value))recovery.value=local;saveFailed.value=false;return true}catch(cause){if(token===generation&&!disposed)reportError(cause);return false}finally{if(token===generation){busy.value=false;schedule()}}}
 function commit(next:Entry[],typingGroup?:string){if(!enabled.value||disposed||loading.value||failed.value||recovery.value||cacheUnreadable.value||pending.value&&!busy.value)return false;entries.value=clone(next);history.push(next,typingGroup);canUndo.value=history.canUndo;canRedo.value=history.canRedo;schedule();return true}
 function add(block:Partial<NotebookBlock>={}){if(!available.value||!enabled.value||disposed||loading.value||failed.value||recovery.value||cacheUnreadable.value||pending.value&&!busy.value)return false;const id=block.id||uid(),content:Entry['content']=[];if(block.quote){if(!block.course_id||!block.lesson_id||!block.source_study_id)return false;const sid=uid();sources.value[sid]={id:sid,original:block.quote,courseTitle:block.course_title||'',lessonTitle:block.lesson_title||'',version:'待核验',verification:'PENDING',courseId:block.course_id,lessonId:block.lesson_id,studyId:block.source_study_id,blockId:block.source_block_id||undefined,sectionId:block.source_section_id||undefined};content.push({type:'paragraph',content:[{type:'text',text:block.quote,marks:[{type:'reference',attrs:{sourceId:sid,occurrenceId:uid()}}]}]})}if(block.text)content.push({type:'paragraph',content:[{type:'text',text:block.text}]});return commit([...entries.value,{id,scope:block.lesson_id?'LESSON':block.course_id?'COURSE':'PLAN',courseId:block.course_id||null,lessonId:block.lesson_id||null,content:content.length?content:[{type:'paragraph'}]}])}
 function removeBlock(id:string){commit(entries.value.filter(e=>e.id!==id))}
 function undo(){if(!enabled.value||recovery.value||cacheUnreadable.value||pending.value&&!busy.value)return;entries.value=history.undo();canUndo.value=history.canUndo;canRedo.value=history.canRedo}
 function redo(){if(!enabled.value||recovery.value||cacheUnreadable.value||pending.value&&!busy.value)return;entries.value=history.redo();canUndo.value=history.canUndo;canRedo.value=history.canRedo}
 let merging:Entry[]=[]
 function restoreCache(){const r=recovery.value;if(!r||!enabled.value||pending.value)return;const base=new Map(r.baseline.map(e=>[e.id,e])),local=new Map(r.entries.map(e=>[e.id,e])),remote=new Map(entries.value.map(e=>[e.id,e]));merging=clone(entries.value);conflicts.value=[]
  const signature=(list:Entry[],id:string)=>{const e=list.find(x=>x.id===id);if(!e)return 'null';const same=list.filter(x=>x.scope===e.scope&&x.courseId===e.courseId&&x.lessonId===e.lessonId),at=same.findIndex(x=>x.id===id);return JSON.stringify({...fromComparable(e),after:at>0?same[at-1]!.id:null})}
  for(const id of new Set([...base.keys(),...local.keys()])){const b=base.get(id),l=local.get(id),w=remote.get(id);const bs=signature(r.baseline,id),ls=signature(r.entries,id),ws=signature(entries.value,id);if(bs===ls||ls===ws)continue;if(bs!==ws){conflicts.value.push({id,local:clone(l||null)||undefined,remote:clone(w||null)||undefined});continue}replaceMerged(id,l)}
  sources.value={...r.sources,...sources.value};if(!conflicts.value.length)finishMerge()}
 function fromComparable(e:Entry){return {id:e.id,scope:e.scope,courseId:e.courseId,lessonId:e.lessonId,content:e.content}}
 function replaceMerged(id:string,value?:Entry,order=recovery.value?.entries||[]){const at=merging.findIndex(e=>e.id===id);if(at>=0)merging.splice(at,1);if(!value)return;const group=order.filter(e=>e.scope===value.scope&&e.courseId===value.courseId&&e.lessonId===value.lessonId),i=group.findIndex(e=>e.id===id),anchor=i>0?group[i-1]!.id:null;let target=anchor?merging.findIndex(e=>e.id===anchor)+1:merging.findIndex(e=>e.scope===value.scope&&e.courseId===value.courseId&&e.lessonId===value.lessonId);if(target<0||anchor&&target===0)target=merging.length;merging.splice(target,0,clone(value))}
 function resolveConflict(id:string,choice:'local'|'remote'){const conflict=conflicts.value.find(c=>c.id===id);if(!conflict)return;replaceMerged(id,choice==='local'?conflict.local:conflict.remote,choice==='local'?recovery.value?.entries:entries.value);conflicts.value=conflicts.value.filter(c=>c.id!==id);if(!conflicts.value.length)finishMerge()}
 function finishMerge(){recovery.value=null;saveFailed.value=false;entries.value=clone(merging);history=new MemoryHistory(entries.value);cache();schedule()}
 function discardCache(){if(pending.value)return;recovery.value=null;conflicts.value=[];cacheUnreadable.value=false;rawRecovery=null;rawPending=null;remove(key(activePid,'pending'));remove(key(activePid,'recovery'));remove(windowStorageKey('notebook:'+activePid+':recovery'));remove(windowStorageKey('notebook:'+activePid+':pending'));schedule()}
 function exportRecovery(){const blob=new Blob([JSON.stringify({schema:'studyflow.notebook-recovery/2',format_version:2,plan_line_id:activePid,document:{entries:entries.value.map(e=>({...toWire(e),course_title:e.courseTitle||null,lesson_title:e.lessonTitle||null})),sources:Object.values(sources.value).map(sourceToExport)},...snapshot(),recovery:recovery.value,pending:pending.value,rejected:rejected.value,raw_recovery:rawRecovery,raw_pending:rawPending},null,2)],{type:'application/json;charset=utf-8'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='StudyFlow-学习笔记.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 function composition(active:boolean){composing.value=active;if(!active)schedule()}
 function suspendAutosave(){cache();disposed=true;clearTimeout(timer);clearTimeout(cacheTimer)}
 function beforeUnload(event:BeforeUnloadEvent){cache();if(!disposed&&enabled.value&&(dirty.value||pending.value||recovery.value)){event.preventDefault();event.returnValue=''}}
 window.addEventListener('beforeunload',beforeUnload)
 watch(planId,pid=>{if(pid===activePid)return;cache();clearTimeout(timer);clearTimeout(cacheTimer);cacheTimer=undefined;generation++;flight=null;activePid=pid||'';baseline.value=[];entries.value=[];sources.value={};courses.value=[];version.value=0;loading.value=true;busy.value=false;saveFailed.value=false;pending.value=null;rejected.value=null;recovery.value=null;cacheUnreadable.value=false;cacheFailed.value=false;history=new MemoryHistory([]);conflicts.value=[];if(activePid)void load();else loading.value=false},{immediate:true,flush:'sync'})
 watch(enabled,owner=>{clearTimeout(timer);if(owner&&activePid&&!disposed)void load()})
 onBeforeUnmount(()=>{cache();disposed=true;clearTimeout(timer);clearTimeout(cacheTimer);generation++;window.removeEventListener('beforeunload',beforeUnload)})
 return {planId,entries,sources,courses,blocks,version,loading,failed,saveFailed,busy,savedAt,pending,rejected,recovery,conflicts,dirty,load,save,retry,commit,add,removeBlock,undo,redo,undoDelete:undo,canUndo,canRedo,restoreCache,resolveConflict,discardCache,exportRecovery,suspendAutosave,refreshConflict,cacheUnreadable,cacheFailed,available,editable,composition,composing}
}
export type PlanNotebookController=ReturnType<typeof usePlanNotebook>
