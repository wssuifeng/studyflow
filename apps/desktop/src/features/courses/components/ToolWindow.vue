<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,ref} from 'vue'
import {emitTo,listen} from '@tauri-apps/api/event'
import {getCurrentWindow} from '@tauri-apps/api/window'
import {confirmNavigation,reportError} from '../../../shared/ui'
import type {NotebookBlock} from '../../../shared/api/contracts'
import {toolsEvent,listToolWindows,type ToolContext,type ToolPrepare} from '../dock/toolWindows'
import {toolTabs,type ToolTab} from '../dock/state'
import ToolSession from './ToolSession.vue'
const props=defineProps<{tool:ToolTab}>()
const context=ref<ToolContext|null>(null),nextContext=ref<ToolContext|null>(null),paused=ref(false),revision=ref(0)
const session=ref<InstanceType<typeof ToolSession>|null>(null),loading=ref(true),failed=ref(false)
const remove:(()=>void)[]=[],ready=ref(false);let disposed=false,heldRequest='',followGeneration=0
async function follow(next:ToolContext){
 const token=++followGeneration
 if(context.value&&session.value&&!await session.value.flush()){nextContext.value=next;return false}
 if(disposed||token!==followGeneration)return false
 context.value=next;nextContext.value=null;ready.value=false;revision.value++;return true
}
async function reportReady(ok:boolean){ready.value=ok;await emitTo('main',toolsEvent.ready,{tool:props.tool,studyId:context.value?.studyId,ok})}
async function putBack(){
 if(!await confirmNavigation('close-window'))return
 if(session.value&&ready.value&&!await session.value.flush()){
  reportError(new Error('独立工具窗口仍有未保存内容，未放回侧栏。请重试保存或选择导出。'))
  return
 }
 try {
  await emitTo('main',toolsEvent.docking,{tool:props.tool})
  await getCurrentWindow().destroy()
 }catch(cause){reportError(cause)}
}
async function subscribe<T>(event:string,handler:(payload:T)=>void|Promise<void>){
 let off:()=>void=()=>{}
 try {
  off=await listen<T>(event,e=>{void Promise.resolve(handler(e.payload)).catch(cause=>{if(!disposed)reportError(cause)})})
  if(disposed)off();else remove.push(off)
 } catch(cause){reportError(cause);throw cause}
}
onMounted(async()=>{try{
 await subscribe('studyflow-tool-put-back',putBack)
 await subscribe(toolsEvent.probe,async()=>{if(ready.value)await reportReady(true)})
 await subscribe<{lessonId:string}>('studyflow-tool-focus-lesson',p=>session.value?.focusLesson(p.lessonId))
 await subscribe<{exerciseId:string;lessonId?:string}>('studyflow-focus-exercise',async p=>{
  if(p.lessonId)session.value?.focusLesson(p.lessonId)
  await nextTick()
  const row=document.querySelector<HTMLElement>(`[data-exercise="${p.exerciseId}"]`)
  row?.scrollIntoView({block:'start'})
  row?.querySelector<HTMLTextAreaElement>('textarea')?.focus({preventScroll:true})
 })
 await subscribe('studyflow-tool-export',()=>session.value?.exportUnsaved())
 await subscribe<{tool:ToolTab;context:ToolContext}>(toolsEvent.context,async payload=>{if(payload.tool===props.tool)await follow(payload.context)})
 await subscribe<ToolPrepare>(toolsEvent.prepare,async p=>{
  if(heldRequest&&heldRequest!==p.requestId){await emitTo('main',toolsEvent.ack,{requestId:p.requestId,tool:props.tool,ok:false});return}
  heldRequest=p.requestId;paused.value=true;let ok=false
  try{ok=!!(ready.value&&await session.value?.flush())}catch(cause){reportError(cause)}
  try{await emitTo('main',toolsEvent.ack,{requestId:p.requestId,tool:props.tool,ok})}
  catch(cause){ok=false;reportError(cause)}
  finally{if(heldRequest===p.requestId&&(p.mode==='flush'||!ok)){heldRequest='';paused.value=false}}
 })
 await subscribe<{requestId:string}>(toolsEvent.release,p=>{if(p.requestId===heldRequest){heldRequest='';paused.value=false}})
 await subscribe(toolsEvent.suspend,()=>{paused.value=true;session.value?.suspend()})
 await subscribe<{id:string;planId:string;block:NotebookBlock}>(toolsEvent.noteAdd,async p=>{
  const ok=!!(ready.value&&context.value?.planId===p.planId&&session.value?.addNote(p.block))
  await emitTo('main',toolsEvent.noteAck,{id:p.id,ok})
 })
 await subscribe<{tool:ToolTab;studyId?:string;planId?:string}>(toolsEvent.saved,async p=>{
  if(p.tool!==props.tool&&(props.tool==='notes'?p.planId===context.value?.planId:p.studyId===context.value?.studyId))await session.value?.reload()
 })
 const rows=await listToolWindows();context.value=rows.find(w=>w.tool===props.tool)?.context||null
 if(!context.value)failed.value=true
 }catch(cause){failed.value=true;reportError(cause)}finally{loading.value=false}})
onBeforeUnmount(()=>{disposed=true;remove.forEach(off=>off())})
</script>
<template>
 <section class="native-tool-window">
  <div class="native-tool-strip"><strong>{{toolTabs.find(t=>t.id===tool)?.label}}</strong><span>跟随主窗课程 · 同一轮学习</span><button class="text-button" @click="putBack">放回侧栏 ↙</button></div>
  <div v-if="loading" class="loading-state">正在连接主窗口…</div>
  <div v-else-if="failed||!context" class="error-state"><p>未找到工具上下文。请从主窗口的标签重新打开。</p><button class="text-button" @click="putBack">关闭此窗口</button></div>
  <div v-if="nextContext" class="notebook-alert"><p>主窗口已切换课程。请先处理此窗口未保存的内容，旧内容没有丢弃。</p><button class="text-button" @click="follow(nextContext)">保存后跟随新课程</button><button class="text-button" @click="session?.exportUnsaved()">导出未保存内容</button></div>
  <div v-if="context" class="native-tool-session"><ToolSession :key="context.studyId+':'+revision" ref="session" :tool="tool" :context="context" :paused="paused" @ready="reportReady(true)" @failed="reportReady(false)"/></div>
 </section>
</template>
