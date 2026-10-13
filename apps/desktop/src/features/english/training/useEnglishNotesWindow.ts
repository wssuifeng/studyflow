import {onBeforeUnmount,onMounted,ref,watch,type ComputedRef,type Ref} from 'vue'
import {invoke} from '@tauri-apps/api/core'
import {emitTo,listen} from '@tauri-apps/api/event'
import {isTauri} from '../../../shared/api'
import {notify,reportError} from '../../../shared/ui'
import {listToolWindows,openToolWindow,prepareTools,releaseTools,toolsEvent,addDetachedNote,type ToolContext} from '../../courses/dock/toolWindows'
import type {NotebookBlock} from '../../../shared/api/contracts'
export function useEnglishNotesWindow(context:ComputedRef<ToolContext|null>,detached:Ref<boolean>,notebook:{save:()=>Promise<boolean>;load:()=>Promise<boolean>}){
 const opening=ref(false),notice=ref('');const off:(()=>void)[]=[];let alive=true,generation=0
 async function refresh(follow=false){if(!isTauri()||!context.value)return;const token=++generation
  try{const windows=await listToolWindows();if(!alive||token!==generation)return;detached.value=windows.some(w=>w.tool==='notes');if(!detached.value)return
   if(follow){const captured={...context.value};const peer=await prepareTools('hold');try{if(!alive||token!==generation)return;if(!peer.ok){notice.value='独立笔记窗口尚未保存；请先在该窗口处理。';return}await invoke('set_tool_context',{context:captured,tool:'notes'});notice.value=''}finally{await releaseTools(peer.requestId)}}
  }catch(e){if(alive){detached.value=true;notice.value='独立笔记窗口连接未确认，请保留输入并重试。';reportError(e)}}
 }
 async function detach(){if(!isTauri()){notify('独立笔记窗口需要桌面版。','info');return}if(!context.value||opening.value)return
  opening.value=true
  try{if(!detached.value&&!await notebook.save())return;detached.value=true;const ready=await openToolWindow('notes',context.value);await refresh();if(!ready)notice.value='笔记窗口内容尚未就绪；请在该窗口重试或放回。';else notice.value=''}catch(e){reportError(e)}finally{opening.value=false}
 }
 async function putBack(){if(!isTauri())return;try{await emitTo('tool-notes','studyflow-tool-put-back',{})}catch(e){reportError(e)}}
 async function add(block:NotebookBlock){return context.value?addDetachedNote(context.value.planId,block):false}
 async function returned(){if(!alive)return;detached.value=false;await notebook.load();notice.value=''}
 onMounted(async()=>{if(!isTauri())return;try{
  for(const event of [toolsEvent.closed,toolsEvent.docking]){const stop=await listen<{tool:string}>(event,e=>{if(e.payload.tool==='notes')void returned().catch(reportError)});if(alive)off.push(stop);else stop()}
  const saved=await listen<{tool:string;planId?:string}>(toolsEvent.saved,e=>{if(alive&&detached.value&&e.payload.tool==='notes'&&e.payload.planId===context.value?.planId)void notebook.load().catch(reportError)});if(alive)off.push(saved);else saved()
  await refresh(true)
 }catch(e){if(alive){detached.value=true;notice.value='笔记窗口状态未确认，请重试连接后再编辑。';reportError(e)}}})
 watch(context,()=>void refresh(true))
 onBeforeUnmount(()=>{alive=false;generation++;off.forEach(stop=>stop())})
 return {opening,notice,detach,putBack,add,refresh}
}
