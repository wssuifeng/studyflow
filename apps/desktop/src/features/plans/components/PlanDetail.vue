<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue'
import {listen} from '@tauri-apps/api/event'
import {isTauri,studyApi,engineCall} from '../../../shared/api'
import type {PlanDetailData} from '../../../shared/api/contracts'
import {navigate,reportError,statusLabel,makeRequestKey,notify} from '../../../shared/ui'
import {usePlanNotebook} from '../../notes/composables/usePlanNotebook'
import PlanNotebook from '../../notes/components/PlanNotebook.vue'
import LeaveStudyDialog from '../../courses/components/LeaveStudyDialog.vue'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import {listToolWindows,prepareTools,suspendTools,toolsEvent,type ToolWindowEntry} from '../../courses/dock/toolWindows'
const props=defineProps<{id:string}>()
const data=ref<PlanDetailData|null>(null),loading=ref(true),view=ref<'courses'|'notes'>('courses'),windows=ref<ToolWindowEntry[]>([])
const owner=computed(()=>!windows.value.some(w=>w.tool==='notes'&&w.context.planId===props.id))
const notebook=usePlanNotebook(computed(()=>props.id),owner)
const editing=ref(false),selectedCourse=ref(''),scheduledDate=ref(new Date().toLocaleDateString('en-CA')),newPriority=ref(1)
const schedules=ref<{id:string;course_id:string;date:string;status:string}[]>([])
async function mutate(operation:string,values:Record<string,unknown>){
 if(!data.value||editing.value)return
 editing.value=true
 try{
  if(!await notebook.save())return
  await engineCall('plan.edit',{plan_line_id:props.id,expected_version:data.value.plan.version,idempotency_key:makeRequestKey('plan-edit'),operation,values})
  await load();notify('计划已更新，学习证据保持不变。')
 }catch(cause){reportError(cause)}finally{editing.value=false}
}
async function reorder(id:string,direction:number){if(!data.value)return;const ids=data.value.courses.map(c=>c.id),i=ids.indexOf(id),j=i+direction;if(j<0||j>=ids.length)return;[ids[i],ids[j]]=[ids[j]!,ids[i]!];await mutate('REORDER',{course_ids:ids})}
async function load(){loading.value=true;try{data.value=await studyApi.planDetail(props.id);newPriority.value=data.value.plan.priority;schedules.value=(await engineCall<{items:typeof schedules.value}>('plan.schedule.list',{plan_line_id:props.id})).items;windows.value=await listToolWindows()}catch(cause){reportError(cause)}finally{loading.value=false}}
const exit=useSafeStudyExit({busy:()=>notebook.busy.value,hasProblem:()=>!!(notebook.pending.value||notebook.recovery.value||notebook.saveFailed.value),
 flush:async()=>{const peer=await prepareTools();return peer.ok&&await notebook.save()},retry:async()=>{await notebook.retry()},
 suspend:()=>{notebook.suspendAutosave();if(exit.dialog.value?.path==='close-window'){void suspendTools();window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}}})
let offSaved:(()=>void)|undefined,offClosed:(()=>void)|undefined,disposed=false
onMounted(async()=>{await load();if(isTauri()){
 const saved=await listen<{planId?:string}>(toolsEvent.saved,async e=>{if(e.payload.planId===props.id&&!notebook.dirty.value&&!notebook.pending.value)await notebook.load()});if(disposed)saved();else offSaved=saved
 const closed=await listen(toolsEvent.closed,async()=>{windows.value=await listToolWindows()});if(disposed)closed();else offClosed=closed
}})
onBeforeUnmount(()=>{disposed=true;offSaved?.();offClosed?.()})
</script>
<template>
 <LeaveStudyDialog v-if="exit.dialog.value" :closing="exit.dialog.value.path==='close-window'" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="notebook.exportRecovery"/>
 <button class="back-button" @click="navigate('/plans')">← 我的计划</button>
 <div v-if="loading" class="loading-state">正在读取学习计划…</div>
 <template v-else-if="data">
  <div class="detail-heading"><div><p class="eyebrow">LEARNING PATH</p><h2>{{data.plan.name}}</h2><p>{{data.plan.course_total}} 门课程 · {{data.plan.completed_courses}} 门练习已通过</p></div><button v-if="data.current_course" class="primary-button" @click="navigate('/course/'+data.current_course.id)">继续当前课程 →</button></div>
  <details class="plan-management"><summary>管理计划与安排</summary><div class="management-controls"><label>优先级 <input v-model.number="newPriority" type="number" min="1" max="100"/></label><button class="secondary-button" :disabled="editing" @click="mutate('UPDATE',{priority:newPriority})">保存优先级</button><button class="secondary-button" :disabled="editing" @click="mutate('UPDATE',{status:data.plan.status==='ACTIVE'?'PAUSED':'ACTIVE'})">{{data.plan.status==='ACTIVE'?'暂停计划':'恢复计划'}}</button><button v-if="data.plan.status!=='ARCHIVED'" class="text-button" :disabled="editing" @click="mutate('UPDATE',{status:'ARCHIVED'})">归档（保留全部记录）</button></div><div class="management-controls"><select v-model="selectedCourse" aria-label="选择安排课程"><option value="">选择课程</option><option v-for="c in data.courses" :key="c.id" :value="c.id">{{c.title}}</option></select><input v-model="scheduledDate" type="date" aria-label="安排日期"/><button class="secondary-button" :disabled="editing||!selectedCourse" @click="mutate('SCHEDULE',{course_id:selectedCourse,date:scheduledDate})">安排学习</button><button class="text-button" :disabled="editing||!selectedCourse" @click="mutate('UPDATE',{focus_course_id:selectedCourse})">设为当前重点</button></div><div v-for="item in schedules.filter(i=>i.status!=='CANCELLED')" :key="item.id" class="schedule-row"><span>{{item.date}} · {{data.courses.find(c=>c.id===item.course_id)?.title}}</span><button class="text-button" :disabled="editing" @click="mutate('RESCHEDULE',{schedule_id:item.id,date:scheduledDate})">顺延到所选日期</button><button class="text-button" :disabled="editing" @click="mutate('CANCEL_SCHEDULE',{schedule_id:item.id})">取消安排</button></div></details>
  <nav class="plan-view-tabs" aria-label="计划内容"><button :class="{selected:view==='courses'}" :aria-pressed="view==='courses'" @click="view='courses'">课程路径</button><button :class="{selected:view==='notes'}" :aria-pressed="view==='notes'" @click="view='notes'">计划学习笔记</button></nav>
  <div v-if="view==='notes'" class="plan-notebook-view"><p v-if="!owner" class="tools-caption">这份笔记正在独立窗口编辑，这里同步查看。</p><PlanNotebook :notebook="notebook" :plan-title="data.plan.name" :blocked="!owner"/></div>
  <template v-else><div class="progress-track"><i :style="{width:data.plan.progress_percent+'%'}"/></div><ol class="path-list"><li v-for="course in data.courses" :key="course.id" :class="{current:course.id===data.current_course?.id}"><span class="path-marker">{{course.progress_percent===100?'✓':course.sequence}}</span><div><span class="eyebrow" v-if="course.id===data.current_course?.id">当前推进课程</span><h3>{{course.title}}</h3><p v-if="course.summary" class="plan-course-summary">{{course.summary}}</p><p>{{course.knowledge_total}} 个知识点 · {{statusLabel(course.study_status||'NOT_STARTED')}} · 本轮通过 {{course.exercise_completed}}/{{course.exercise_total}}</p></div><div class="course-management"><button class="text-button" :disabled="editing" aria-label="课程上移" @click="reorder(course.id,-1)">↑</button><button class="text-button" :disabled="editing" aria-label="课程下移" @click="reorder(course.id,1)">↓</button><button class="secondary-button" @click="navigate('/course/'+course.id)">{{course.learning_submitted?'查看内容与反馈':'进入课程'}} →</button></div></li></ol><div v-if="!data.courses.length" class="empty-state"><p>计划已建立，课程内容等待导入。</p></div></template>
 </template>
 <div v-else class="empty-state"><p>计划未能读取。</p><button class="secondary-button" @click="load">重试</button></div>
</template>
