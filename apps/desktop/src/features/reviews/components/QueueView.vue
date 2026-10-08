<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {engineCall} from '../../../shared/api'
import {QUEUE_PAGE_SIZE, type QueueData, type QueueItem} from '../../../shared/api/contracts'
import {navigate,reportError} from '../../../shared/ui'
const props=defineProps<{data:QueueData|null}>()
const filter=ref('action'),history=ref<QueueItem[]>([]),more=ref<QueueItem[]>([]),cursor=ref<string|null>(null),busy=ref(false)
const tabs=[{id:'action',label:'我需要处理'},{id:'waiting',label:'等待Agent'},{id:'all',label:'全部待办'},{id:'history',label:'已通过历史'}]
async function fetchPage(reset=false){
 if(busy.value)return;busy.value=true
 try{
  const result=await engineCall<{items:QueueItem[];next_cursor:string|null}>('assignment.summary',{history:filter.value==='history',limit:QUEUE_PAGE_SIZE,...(!reset&&cursor.value?{cursor:cursor.value}:{})})
  if(filter.value==='history')history.value=reset?result.items:[...history.value,...result.items]
  else more.value=reset?result.items:[...more.value,...result.items]
  cursor.value=result.next_cursor
 }catch(cause){reportError(cause)}finally{busy.value=false}
}
watch(filter,()=>{history.value=[];more.value=[];cursor.value=props.data?.next_cursor||null;if(filter.value==='history')void fetchPage(true)})
watch(()=>props.data,()=>{more.value=[];cursor.value=props.data?.next_cursor||null},{immediate:true})
const items=computed(()=>filter.value==='history'?history.value:[...(props.data?.items||[]),...more.value].filter((v,i,a)=>a.findIndex(x=>x.id===v.id)===i).filter(i=>filter.value==='all'||filter.value==='action'&&['REVISE','RETEST'].includes(i.action||'')||filter.value==='waiting'&&['REVIEW','PUBLISH_RETEST'].includes(i.action||'')))
function open(item:QueueItem){
 if(['REVISE','RETEST'].includes(item.action||'')){
  const params=new URLSearchParams({lesson:item.lesson_id,exercise:item.exercise_id,tab:'exercises'});if(item.study_session_id)params.set('study',item.study_session_id)
  navigate('/course/'+item.course_id+'?'+params)
 }else navigate('/submission/'+item.id)
}
</script>
<template>
 <div class="page-intro"><h2>作答与反馈</h2><p class="muted">需要你处理的修正和复测优先；等待批改不影响继续学习。</p></div>
 <nav class="filter-tabs" aria-label="反馈筛选"><button v-for="tab in tabs" :key="tab.id" :class="{selected:filter===tab.id}" @click="filter=tab.id">{{tab.label}}</button></nav>
 <div class="feedback-rows"><button v-for="item in items" :key="item.id" class="feedback-row" @click="open(item)"><span :class="['status-chip',item.status.toLowerCase()]">{{item.label}}</span><div><strong>{{item.exercise_title}}</strong><small>{{item.course_title}} · {{item.lesson_title}}</small><p>{{item.next_action}}</p></div><span>→</span></button></div>
 <button v-if="cursor" class="secondary-button" :disabled="busy" @click="fetchPage()">{{busy?'读取中…':'加载更多'}}</button>
 <p v-if="!items.length&&!busy" class="empty-state">这里暂时没有记录。<button class="text-button" @click="navigate('/today')">继续学习 →</button></p>
</template>
