import {computed, onBeforeUnmount, ref, watch, type Ref} from 'vue'
import {EngineError, studyApi, isTauri} from '../../../shared/api'
import {makeRequestKey, reportError, windowStorageKey} from '../../../shared/ui'
import type {NotebookBlock, NotebookSaveParams, LegacyNote} from '../../../shared/api/contracts'
import {emit} from '@tauri-apps/api/event'

export function notebookFingerprint(blocks: NotebookBlock[]) {
  return JSON.stringify(blocks.map(b => ({id:b.id, text:b.text, course_id:b.course_id||null,
    lesson_id:b.lesson_id||null, quote:b.quote||'', source_study_id:b.source_study_id||null, source_block_id:b.source_block_id||null})))
}
function validBlocks(value:unknown):value is NotebookBlock[] {
  return Array.isArray(value) && value.every(b => b && typeof b==='object' && typeof b.id==='string' && typeof b.text==='string' &&
    ['course_id','lesson_id','source_study_id','source_block_id','quote'].every(k => b[k] == null || typeof b[k]==='string'))
}
const copy = <T>(value:T):T => JSON.parse(JSON.stringify(value))
export function usePlanNotebook(planId:Ref<string|undefined>, enabled:Ref<boolean> = ref(true)) {
  const blocks=ref<NotebookBlock[]>([]), legacy=ref<LegacyNote[]>([]), version=ref(0)
  const loading=ref(false), failed=ref(false), saveFailed=ref(false), busy=ref(false), savedAt=ref('')
  const pending=ref<NotebookSaveParams|null>(null), recovery=ref<NotebookBlock[]|null>(null),cacheUnreadable=ref(false)
  let rawRecovery:string|null=null, rawPending:string|null=null
  const deleted=ref<{block:NotebookBlock;index:number}[]>([])
  const canUndo=computed(()=>deleted.value.length>0)
  let baseline='[]', activePid='', generation=0, disposed=false, pendingFromStorage=false
  let timer:ReturnType<typeof setTimeout>|undefined, flight:Promise<boolean>|null=null
  const available=computed(()=>!!planId.value)
  const dirty=computed(() => notebookFingerprint(blocks.value)!==baseline)
  const key=(pid:string, kind:string) => windowStorageKey('notebook:'+pid+':'+kind)
  // Local cache failure never changes a successful database acknowledgement.
  function put(k:string, value:unknown) {try {localStorage.setItem(k,JSON.stringify(value))} catch { /* best effort */ }}
  function remove(k:string) {try {localStorage.removeItem(k)} catch { /* best effort */ }}
  function cache() {
    if (!activePid || loading.value || cacheUnreadable.value) return
    if (dirty.value || pending.value) put(key(activePid,'recovery'),blocks.value)
    else if (!recovery.value) remove(key(activePid,'recovery'))
  }
  function schedule() {
    clearTimeout(timer); cache()
    if (enabled.value && dirty.value && !disposed && !loading.value && !busy.value && !failed.value &&
        !saveFailed.value && !pending.value && !recovery.value && !cacheUnreadable.value) timer=setTimeout(() => save(),850)
  }
  watch(blocks,schedule,{deep:true,flush:'sync'})
  async function load(force=false) {
    if (!activePid || disposed || (!force && (dirty.value || pending.value || recovery.value))) return false
    const pid=activePid, token=++generation; loading.value=true; failed.value=false
    try {
      const data=await studyApi.planNotebook(pid)
      if (disposed || token!==generation || activePid!==pid) return false
      baseline=notebookFingerprint(data.blocks); blocks.value=data.blocks; legacy.value=data.legacy_notes||[]
      version.value=data.version; saveFailed.value=false; recovery.value=null; pending.value=null;pendingFromStorage=false;cacheUnreadable.value=false;rawRecovery=null;rawPending=null
      try {
        rawRecovery=localStorage.getItem(key(pid,'recovery')); rawPending=localStorage.getItem(key(pid,'pending'))
        if (rawPending) {
          try {
            const p=JSON.parse(rawPending)
            if (!p || p.plan_line_id!==pid || !validBlocks(p.blocks) || typeof p.idempotency_key!=='string' || !p.idempotency_key || !Number.isInteger(p.expected_version) || p.expected_version<0) throw Error('Invalid notebook request')
            pending.value=p;pendingFromStorage=true
          } catch {cacheUnreadable.value=true}
        }
        if (rawRecovery) {
          try {
            const saved=JSON.parse(rawRecovery)
            if (!validBlocks(saved)) throw Error('Invalid notebook recovery')
            if (notebookFingerprint(saved)!==baseline) recovery.value=saved
          } catch {cacheUnreadable.value=true}
        }
      } catch {cacheUnreadable.value=true /* Preserve both raw copies until explicit export/discard. */ }
      return true
    } catch (cause) {if (token===generation && !disposed) {failed.value=true; reportError(cause)}; return false}
    finally {if (token===generation) {loading.value=false; schedule()}}
  }
  async function perform(params:NotebookSaveParams) {
    const pid=params.plan_line_id, token=generation
    const current=() => !disposed && token===generation && activePid===pid
    busy.value=true; saveFailed.value=false; pending.value=params; put(key(pid,'pending'),params)
    try {
      const result=await studyApi.savePlanNotebook(params)
      remove(key(pid,'pending'))
      if (!current()) {
        try {const raw=localStorage.getItem(key(pid,'recovery'));if(raw&&notebookFingerprint(JSON.parse(raw))===notebookFingerprint(params.blocks))remove(key(pid,'recovery'))}catch {/* Preserve any unreadable recovery. */}
        return true
      }
      const restoreAcknowledged=pendingFromStorage && notebookFingerprint(blocks.value)===baseline
      version.value=result.version; baseline=notebookFingerprint(params.blocks)
      if (restoreAcknowledged || notebookFingerprint(blocks.value)===baseline) {baseline=notebookFingerprint(result.blocks); blocks.value=result.blocks}
      if (recovery.value && notebookFingerprint(recovery.value)===notebookFingerprint(params.blocks)) recovery.value=null
      pending.value=null; pendingFromStorage=false; savedAt.value=new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})
      if (isTauri()) void emit('studyflow-tool-saved',{tool:'notes',planId:pid}).catch(() => {})
      return true
    } catch (cause) {
      if (current()) {
        saveFailed.value=true
        if (cause instanceof EngineError && ['VERSION_CONFLICT','INVALID_ARGUMENT','IDEMPOTENCY_KEY_CONFLICT'].includes(cause.code)) {
          pending.value=null; pendingFromStorage=false; remove(key(pid,'pending'))
        }
        reportError(cause)
      }
      return false
    } finally {if (current()) {busy.value=false; schedule()}}
  }
  async function save():Promise<boolean> {
    clearTimeout(timer)
    if (disposed) return false
    if (!enabled.value) return !dirty.value && !pending.value && !recovery.value
    const token=generation
    if (flight) {if (!await flight) return false; return token===generation ? save() : true}
    if (loading.value || failed.value || recovery.value || saveFailed.value || pending.value || cacheUnreadable.value) return false
    if (!dirty.value) return true
    if (!activePid) return false
    const request=perform({plan_line_id:activePid,blocks:copy(blocks.value),expected_version:version.value,idempotency_key:makeRequestKey('plan-notebook')})
    flight=request
    let ok:boolean; try {ok=await request} finally {if (flight===request) flight=null}
    return ok && (token!==generation || !dirty.value || await save())
  }
  async function retry():Promise<boolean> {
    if (disposed || !enabled.value) return false
    if (flight) return flight
    if (!pending.value) return refreshConflict()
    const request=perform(copy(pending.value)); flight=request
    try {return await request} finally {if (flight===request) flight=null}
  }
  async function refreshConflict() {
    if (!activePid || disposed || busy.value) return false
    const pid=activePid, token=generation
    busy.value=true
    try {
      const latest=await studyApi.planNotebook(pid)
      if (disposed || token!==generation || pid!==activePid) return false
      // Capture after awaiting: the editor may have changed while the read was in flight.
      const local=copy(blocks.value), hadChanges=dirty.value
      version.value=latest.version; baseline=notebookFingerprint(latest.blocks); legacy.value=latest.legacy_notes||[]
      if (hadChanges && notebookFingerprint(local)!==baseline) recovery.value=local
      blocks.value=latest.blocks; saveFailed.value=false; schedule(); return true
    } catch (cause) {if (token===generation && !disposed) reportError(cause); return false}
    finally {if(token===generation && !disposed){busy.value=false;schedule()}}
  }
  function add(block:Partial<NotebookBlock>={}) {
    if (!activePid || !enabled.value || disposed || failed.value || loading.value || cacheUnreadable.value || recovery.value || pending.value&&!busy.value) return false
    blocks.value.push({id:makeRequestKey('note').slice(0,64),text:'',...block}); schedule(); return true
  }
  function removeBlock(id:string) {
    if (!enabled.value || disposed || loading.value || failed.value || recovery.value || cacheUnreadable.value || pending.value&&!busy.value) return
    const index=blocks.value.findIndex(b=>b.id===id);if(index<0)return
    deleted.value.push({block:copy(blocks.value[index]!),index})
    if(deleted.value.length>20)deleted.value.shift()
    blocks.value.splice(index,1)
  }
  function undoDelete() {
    if (!enabled.value || disposed || loading.value || failed.value || recovery.value || cacheUnreadable.value || pending.value&&!busy.value) return
    const entry=deleted.value.pop();if(!entry)return
    if(blocks.value.some(b=>b.id===entry.block.id))entry.block.id=makeRequestKey('restored-note').slice(0,64)
    blocks.value.splice(Math.min(entry.index,blocks.value.length),0,entry.block)
  }
  function restoreCache() {
    if (!recovery.value || !enabled.value) return
    for (const block of recovery.value) {
      const remote=blocks.value.find(b => b.id===block.id)
      if (!remote) blocks.value.push(copy(block))
      else if (notebookFingerprint([remote])!==notebookFingerprint([block])) blocks.value.push({...copy(block),id:makeRequestKey('merged-note').slice(0,64)})
    }
    recovery.value=null; saveFailed.value=false; schedule()
  }
  function discardCache() {
    // A valid uncertain request still needs its original idempotency key; only discard malformed requests here.
    if(cacheUnreadable.value && !pending.value)remove(key(activePid,'pending'))
    recovery.value=null;cacheUnreadable.value=false;rawRecovery=null;rawPending=null
    remove(key(activePid,'recovery')); schedule()
  }
  function exportRecovery() {
    const url=URL.createObjectURL(new Blob([JSON.stringify({plan_line_id:activePid,blocks:blocks.value,recovery:recovery.value,pending:pending.value,raw_recovery:rawRecovery,raw_pending:rawPending},null,2)],{type:'application/json;charset=utf-8'}))
    const a=document.createElement('a'); a.href=url; a.download='StudyFlow-学习笔记.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000)
  }
  function suspendAutosave() {cache(); disposed=true; clearTimeout(timer)}
  function beforeUnload(event:BeforeUnloadEvent) {cache(); if (!disposed && enabled.value && (dirty.value || pending.value || recovery.value)) {event.preventDefault(); event.returnValue=''}}
  window.addEventListener('beforeunload',beforeUnload)
  watch(planId,pid => {
    if (pid===activePid) return
    cache(); clearTimeout(timer); generation++; flight=null; activePid=pid||''
    loading.value=true;cacheUnreadable.value=false;rawRecovery=null;rawPending=null;deleted.value=[];baseline='[]'; pending.value=null;pendingFromStorage=false; recovery.value=null; blocks.value=[]; legacy.value=[]; version.value=0
    busy.value=false; saveFailed.value=false; savedAt.value=''
    if (activePid) void load();else loading.value=false
  },{immediate:true,flush:'sync'})
  watch(enabled,owner => {clearTimeout(timer); if (owner && activePid && !disposed) void load()})
  onBeforeUnmount(() => {cache(); disposed=true; clearTimeout(timer); generation++; window.removeEventListener('beforeunload',beforeUnload)})
  return {blocks,legacy,version,loading,failed,saveFailed,busy,savedAt,pending,recovery,dirty,load,save,retry,add,removeBlock,undoDelete,canUndo,restoreCache,discardCache,exportRecovery,suspendAutosave,refreshConflict,cacheUnreadable,available}
}
export type PlanNotebookController=ReturnType<typeof usePlanNotebook>
