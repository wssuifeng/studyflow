import {invoke} from '@tauri-apps/api/core'
import {emitTo, listen} from '@tauri-apps/api/event'
import {isTauri} from '../../../shared/api'
import {makeRequestKey} from '../../../shared/ui'
import type {NotebookBlock} from '../../../shared/api/contracts'
import type {ToolTab} from './state'
export interface ToolContext {courseId:string;studyId:string;planId:string;planTitle:string;lessonId?:string}
export interface ToolWindowEntry {tool:ToolTab;context:ToolContext}
export interface ToolPrepare {requestId:string;mode:'flush'|'hold'|'shutdown'}
export interface ToolAck {requestId:string;tool:ToolTab;ok:boolean}
export const toolsEvent={context:'studyflow-tool-context',closed:'studyflow-tool-closed',docking:'studyflow-tool-docking',saved:'studyflow-tool-saved',prepare:'studyflow-tool-prepare',ack:'studyflow-tool-ack',release:'studyflow-tool-release',suspend:'studyflow-tool-suspend',noteAdd:'studyflow-note-add',noteAck:'studyflow-note-added',ready:'studyflow-tool-ready',probe:'studyflow-tool-probe'} as const
export const listToolWindows=():Promise<ToolWindowEntry[]> => isTauri()?invoke('tool_windows'):Promise.resolve([])
// Subscribe before broadcasting; a missing/failed child is a failure, never assumed saved.
export async function prepareTools(mode:ToolPrepare['mode']='flush'):Promise<{ok:boolean;requestId:string}> {
 const requestId=makeRequestKey('tools-flush')
 let windows:ToolWindowEntry[]
 try {windows=await listToolWindows()}catch{return {ok:false,requestId}}
 if (!windows.length) return {ok:true,requestId}
 const pending=new Set(windows.map(w=>w.tool));let finish:(ok:boolean)=>void=()=>{};let ok=true
 const result=new Promise<boolean>(resolve=>finish=resolve)
 let unlisten:()=>void=()=>{}
 let timer:ReturnType<typeof setTimeout>|undefined
 try {
  unlisten=await listen<ToolAck>(toolsEvent.ack,event=>{
   const ack=event.payload;if(ack.requestId!==requestId||!pending.has(ack.tool))return
   pending.delete(ack.tool);ok=ok&&ack.ok;if(!pending.size)finish(ok)
  })
  timer=setTimeout(()=>finish(false),6000)
  await Promise.all(windows.map(w=>emitTo('tool-'+w.tool,toolsEvent.prepare,{requestId,mode})))
  return {ok:await result,requestId}
 } catch {return {ok:false,requestId}}
 finally {if(timer)clearTimeout(timer);unlisten()}
}
export async function releaseTools(requestId:string) {
 if (!isTauri()) return
 try {const windows=await listToolWindows();await Promise.allSettled(windows.map(w=>emitTo('tool-'+w.tool,toolsEvent.release,{requestId})))}catch{/* The main editor must unlock even if a child has closed. */}
}
export async function suspendTools() {
 if (!isTauri()) return
 try {
  const windows=await listToolWindows()
  await Promise.allSettled(windows.map(w=>emitTo('tool-'+w.tool,toolsEvent.suspend,{})))
 } catch {/* A closed child must not block the main window from completing its exit. */}
}
export async function addDetachedNote(planId:string,block:NotebookBlock):Promise<boolean> {
 if (!isTauri()) return false
 const id=makeRequestKey('note-transfer');let finish:(ok:boolean)=>void=()=>{}
 const result=new Promise<boolean>(resolve=>finish=resolve)
 let unlisten:()=>void=()=>{}
 let timer:ReturnType<typeof setTimeout>|undefined
 try {
  unlisten=await listen<{id:string;ok:boolean}>(toolsEvent.noteAck,e=>{if(e.payload.id===id)finish(e.payload.ok)})
  timer=setTimeout(()=>finish(false),5000)
  await emitTo('tool-notes',toolsEvent.noteAdd,{id,planId,block});return await result
 } catch {return false} finally {if(timer)clearTimeout(timer);unlisten()}
}

// Native creation alone does not prove that the Vue tool page loaded.
export async function openToolWindow(tool:ToolTab,context:ToolContext):Promise<boolean> {
 if (!isTauri()) return false
 let finish:(ok:boolean)=>void=()=>{}
 const result=new Promise<boolean>(resolve=>finish=resolve)
 let unlisten:()=>void=()=>{}
 let timer:ReturnType<typeof setTimeout>|undefined
 try {
  unlisten=await listen<{tool:ToolTab;studyId:string;ok:boolean}>(toolsEvent.ready,e=>{
   if(e.payload.tool===tool&&e.payload.studyId===context.studyId)finish(e.payload.ok)
  })
  timer=setTimeout(()=>finish(false),12000)
  void invoke('open_tool_window',{tool,context}).then(()=>emitTo('tool-'+tool,toolsEvent.probe,{})).catch(()=>finish(false))
  return await result
 } catch {return false} finally {if(timer)clearTimeout(timer);unlisten()}
}
