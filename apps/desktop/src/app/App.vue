<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {isTauri,invoke} from '@tauri-apps/api/core'
import {getCurrentWindow} from '@tauri-apps/api/window'
import {emitTo,listen} from '@tauri-apps/api/event'
import { engineCall } from '../shared/api'
import {QUEUE_PAGE_SIZE, type DoctorData, type Plan, type QueueData, type QueueItem, type TodayData} from '../shared/api/contracts'
import { confirmNavigation, navigate, notify, reportError, windowStorageKey, workspaceScope } from '../shared/ui'
import AppShell from './layout/AppShell.vue'
import TodayWorkspace from '../features/console/components/TodayWorkspace.vue'
import FrozenSource from '../features/notes/components/FrozenSource.vue'
import PlanList from '../features/plans/components/PlanList.vue'
import PlanDetail from '../features/plans/components/PlanDetail.vue'
import CourseReader from '../features/courses/components/CourseReader.vue'
import QueueView from '../features/reviews/components/QueueView.vue'
import SubmissionFeedback from '../features/reviews/components/SubmissionFeedback.vue'
import ToolWindow from '../features/courses/components/ToolWindow.vue'
import LeaveStudyDialog from '../features/courses/components/LeaveStudyDialog.vue'
import {isTool} from '../features/courses/dock/state'
import {listToolWindows,prepareTools,releaseTools,suspendTools} from '../features/courses/dock/toolWindows'
import WorkspaceSettings from '../features/workspace/components/WorkspaceSettings.vue'
const today = ref<TodayData | null>(null)
const plans = ref<Plan[]>([])
const queue = ref<QueueData | null>(null)
const doctor = ref<DoctorData | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const failed = ref(false)
const route = ref(window.location.hash.slice(1) || '/today')
const revision = ref(0)
const parsed = computed(()=>{
  const [path, query] = route.value.split('?')
  const pieces = path!.split('/').filter(Boolean)
  return {name:pieces[0] || 'today', id:pieces[1] || '', lesson:new URLSearchParams(query).get('lesson') || undefined, tab:new URLSearchParams(query).get('tab') || undefined, study:new URLSearchParams(query).get('study') || undefined, exercise:new URLSearchParams(query).get('exercise') || undefined,block:new URLSearchParams(query).get('block') || undefined}
})
// Deep-link content identity changes require a guarded remount; focus-only layout changes do not.
const routeKey = computed(()=>[parsed.value.name, parsed.value.id, parsed.value.study || '',
  parsed.value.lesson || '', parsed.value.exercise || '', parsed.value.block || '', parsed.value.tab || '', revision.value].join(':'))
const active = computed(()=> parsed.value.name==='plan' || parsed.value.name==='course' ? 'plans' : parsed.value.name==='submission' ? 'queue' : parsed.value.name)
const titles: Record<string,string> = {today:'学习控制台',plans:'我的计划',plan:'学习计划',course:'课程工作区',queue:'作答与反馈',submission:'作答与反馈',settings:'工作区',tool:'学习工具'}
const title = computed(()=>titles[parsed.value.name] || 'StudyFlow')
const detached = isTauri() && getCurrentWindow().label.startsWith('tool-')
const focusMode = computed(() => detached || parsed.value.name==='course' && new URLSearchParams(route.value.split('?')[1]).get('focus')==='1')
const dateLabel = computed(()=>new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'}))
const feedbackCount = computed(()=> (today.value?.queue_counts.needs_revision || 0)+(today.value?.queue_counts.waiting_retest || 0)+(today.value?.queue_counts.waiting_review || 0))
function resetMainScrollForRoute(next:string){
 const name=next.split('?')[0]?.split('/').filter(Boolean)[0]||'today'
 if(name==='course'||name==='tool')return
 document.querySelector<HTMLElement>('.workspace-shell:not(.focus-shell) > .main-content')?.scrollTo({top:0,left:0,behavior:'auto'})
}
async function readRoute() {
  const next=window.location.hash.slice(1) || '/today'
  if(!await confirmNavigation(next)) {window.history.replaceState(null,'','#'+route.value); return}
  route.value=next
  const nextName=next.split('?')[0]?.split('/').filter(Boolean)[0]||'today'
  if(nextName!=='course'&&nextName!=='tool')newFeedback.value=false
  resetMainScrollForRoute(next)
  try{localStorage.setItem(windowStorageKey('last-route'),next)}catch{/* Optional navigation cache */}
  if(!loading.value && !refreshing.value) load()
}
async function compactQueue():Promise<QueueData>{
 const data=await engineCall<{items:QueueItem[];counts:Record<string,number>;next_cursor:string|null}>('assignment.summary',{limit:QUEUE_PAGE_SIZE})
 return {...data,waiting_review:data.items.filter(i=>i.status==='WAITING_REVIEW'),needs_revision:data.items.filter(i=>i.status==='NEEDS_REVISION'),waiting_retest:data.items.filter(i=>i.status==='RETEST_REQUIRED')}
}
const newFeedback=ref(false)
let changeRevision='',changeTimer:ReturnType<typeof setInterval>|undefined
async function checkChanges(){
 if(document.hidden||loading.value||refreshing.value||detached)return
 try{const current=await engineCall<{revision:string}>('system.changes');if(changeRevision&&changeRevision!==current.revision){
  if(parsed.value.name==='course'||parsed.value.name==='tool')newFeedback.value=true
  else {queue.value=await compactQueue();today.value=await engineCall<TodayData>('study.today')}
 }changeRevision=current.revision}catch{/* Keep editor state intact on transient faults. */}
}
async function load(refresh=false) {
  if(refresh && !await confirmNavigation(route.value)) return
  refreshing.value=true
  try {
    const nextDoctor=await engineCall<DoctorData>('system.doctor')
    doctor.value=nextDoctor; workspaceScope.value=nextDoctor.workspace.root
    if (loading.value && !window.location.hash) {
      let saved:string|null=null;try{saved=localStorage.getItem(windowStorageKey('last-route'))}catch{/* Optional navigation cache */}
      if (saved) { route.value=saved; window.history.replaceState(null,'','#'+saved) }
    }
    if(detached){failed.value=false;return}
    const results = await Promise.all([engineCall<TodayData>('study.today'),engineCall<{plans:Plan[]}>('plan.list',{include_inactive:true}),compactQueue()])
    today.value=results[0]; plans.value=results[1].plans; queue.value=results[2]; failed.value=false
    if(refresh) {revision.value++; notify('课程与反馈已同步到最新状态。')}
  } catch(cause) {failed.value=true;reportError(cause)}
  finally {loading.value=false;refreshing.value=false}
}
let closingWindow=false,discardWindowSave=false,shutdownRequest=''
let removeCloseListener:(()=>void)|undefined,removeFeedbackListener:(()=>void)|undefined
const toolCloseDialog=ref<{reason:string;retrying:boolean}|null>(null)
let closeDecision:((allow:boolean)=>void)|null=null
function discardNotice(){discardWindowSave=true}
async function askToolClose(){
 toolCloseDialog.value={reason:'有独立工具窗口的保存尚未确认。可返回处理，也可明确不保存退出；已保存的学习记录不会删除。',retrying:false}
 return new Promise<boolean>(resolve=>closeDecision=resolve)
}
function finishToolClose(allowed:boolean,discard=false){
 if(discard){discardWindowSave=true;void suspendTools()}
 toolCloseDialog.value=null;const resolve=closeDecision;closeDecision=null;resolve?.(allowed)
}
async function retryToolClose(){
 if(!toolCloseDialog.value||toolCloseDialog.value.retrying)return
 const dialog=toolCloseDialog.value;dialog.retrying=true
 const result=await prepareTools('shutdown')
 if(toolCloseDialog.value!==dialog){await releaseTools(result.requestId);return}
 if(result.ok){shutdownRequest=result.requestId;finishToolClose(true)}else{await releaseTools(result.requestId);dialog.retrying=false}
}
async function exportToolInputs(){const windows=await listToolWindows();await Promise.all(windows.map(w=>emitTo('tool-'+w.tool,'studyflow-tool-export',{})))}
onMounted(async()=>{
 changeTimer=setInterval(checkChanges,30000);window.addEventListener('focus',checkChanges);void checkChanges();
 window.addEventListener('hashchange',readRoute);window.addEventListener('studyflow-discard-close',discardNotice);load()
 if(isTauri()&&!detached)removeFeedbackListener=await listen<{id:string}>('studyflow-open-feedback',e=>{if(/^[a-zA-Z0-9-]{1,64}$/.test(e.payload.id))void navigate('/submission/'+e.payload.id)})
 if(isTauri()) removeCloseListener=await getCurrentWindow().onCloseRequested(async event=>{
  event.preventDefault();if(closingWindow)return;closingWindow=true;let destroyed=false
  try {
   if(!await confirmNavigation('close-window'))return
   if(!detached){
    if(!discardWindowSave){const held=await prepareTools('shutdown');if(held.ok)shutdownRequest=held.requestId;else{await releaseTools(held.requestId);if(!await askToolClose())return}}
    if(discardWindowSave)await suspendTools()
    await invoke('close_tool_windows')
   }
   await getCurrentWindow().destroy();destroyed=true
  }catch(cause){reportError(cause)}finally{if(!detached&&!destroyed&&shutdownRequest)await releaseTools(shutdownRequest);shutdownRequest='';closingWindow=false;discardWindowSave=false}
 })
})
onBeforeUnmount(()=>{
 clearInterval(changeTimer);window.removeEventListener('focus',checkChanges);window.removeEventListener('hashchange',readRoute);window.removeEventListener('studyflow-discard-close',discardNotice);removeCloseListener?.();removeFeedbackListener?.();closeDecision?.(false)})
</script>

<template>
  <LeaveStudyDialog v-if="toolCloseDialog" :closing="true" :reason="toolCloseDialog.reason" :retrying="toolCloseDialog.retrying" @retry="retryToolClose" @discard="finishToolClose(true,true)" @cancel="finishToolClose(false)" @export="exportToolInputs"/>
  <AppShell :focus="focusMode" :window-chrome="detached" :active="active" :count="feedbackCount" :connected="!!doctor?.healthy && !failed" :title="title" :date="dateLabel" :refreshing="refreshing" @navigate="navigate" @refresh="load(true)">
    <div v-if="loading" class="loading-state initial-loading" role="status"><span class="loading-orbit"/><h2>正在打开本地学习空间</h2><p>恢复计划、课程与反馈…</p></div>
    <div v-else-if="failed" class="error-state initial-loading"><h2>工作区暂时无法连接</h2><p>你的记录仍保存在本地。连接恢复后可以继续。</p><button class="primary-button" @click="() => load()">重新连接 ↻</button></div>
    <p v-if="newFeedback&&!loading" class="recovery-note" role="status">工作区有新反馈或状态更新；当前输入未被覆盖。请在课程内保存后同步反馈。<button class="text-button" @click="newFeedback=false">知道了</button></p>
    <Transition v-if="!loading&&!failed" name="page" mode="out-in">
      <div :key="routeKey" class="page-content">
        <ToolWindow v-if="parsed.name==='tool' && isTool(parsed.id)" :tool="parsed.id"/>
        <TodayWorkspace v-else-if="parsed.name==='today' && today" :data="today" />
        <PlanList v-else-if="parsed.name==='plans'" :plans="plans" />
        <PlanDetail v-else-if="parsed.name==='plan' && parsed.id" :id="parsed.id" />
        <FrozenSource v-else-if="parsed.name==='source' && parsed.id && parsed.lesson" :study-id="parsed.id" :lesson-id="parsed.lesson" :block-id="parsed.block"/>
        <CourseReader v-else-if="parsed.name==='course' && parsed.id" :id="parsed.id" :lesson-id="parsed.lesson" :initial-view="parsed.tab" :study-id="parsed.study" :exercise-id="parsed.exercise" />
        <QueueView v-else-if="parsed.name==='queue'" :data="queue" />
        <SubmissionFeedback v-else-if="parsed.name==='submission' && parsed.id" :id="parsed.id" />
        <WorkspaceSettings v-else-if="parsed.name==='settings'" :doctor="doctor" />
        <div v-else class="empty-state"><h2>页面暂不存在</h2><button class="primary-button" @click="navigate('/today')">回到学习控制台</button></div>
      </div>
    </Transition>
    <footer v-if="!focusMode && parsed.name !== 'course'" class="app-footer"><span>每天向前一点，知识就有了自己的形状。</span><span>StudyFlow · LOCAL FIRST</span></footer>
  </AppShell>
</template>
