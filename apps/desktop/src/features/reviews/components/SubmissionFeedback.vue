<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { studyApi } from '../../../shared/api'
import type { SubmissionDetailData } from '../../../shared/api/contracts'
import { navigate, notify, reportError, statusLabel, storageKey } from '../../../shared/ui'
const props = defineProps<{id:string}>()
const data = ref<SubmissionDetailData | null>(null)
const loading = ref(true)
const recoveryBusy = ref(false)
const pending = ref<{kind:'REVISION'|'RETEST';answer:string;key:string}|null>(null)
const pendingKey = storageKey('followup:' + props.id)
const cacheError=ref(false)
async function load(){
 loading.value=true
 try {data.value=await studyApi.submission(props.id)} catch(cause){reportError(cause)} finally{loading.value=false}
 try {const raw=localStorage.getItem(pendingKey);if(raw){const value=JSON.parse(raw);if(['REVISION','RETEST'].includes(value.kind)&&typeof value.answer==='string'&&typeof value.key==='string')pending.value=value;else cacheError.value=true}}catch{cacheError.value=true}
}
function openEditor(){
 if(!data.value?.course)return
 if(data.value.is_current_study===false&&data.value.study_session_id){navigate('/source/'+data.value.study_session_id+'?lesson='+data.value.lesson?.id);return}
 const params=new URLSearchParams({lesson:data.value.lesson?.id||'',tab:'exercises'})
 if(data.value.study_session_id)params.set('study',data.value.study_session_id)
 params.set('exercise',data.value.exercise_id)
 navigate('/course/'+data.value.course.id+'?'+params)
}
function exportRecovery(){
 const blob=new Blob([JSON.stringify({submission_id:props.id,pending:pending.value},null,2)],{type:'application/json'})
 const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='StudyFlow-旧修正请求.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
async function retryRecovery(){
 if(recoveryBusy.value||!pending.value)return
 recoveryBusy.value=true
 const value=pending.value
 try {
  const params={parent_submission_id:props.id,answer_text:value.answer,idempotency_key:value.key}
  const result=value.kind==='REVISION'?await studyApi.revise(params):await studyApi.retest(params)
  try{localStorage.removeItem(pendingKey)}catch{cacheError.value=true}
  pending.value=null;notify('旧请求已确认，继续在课程内作答。');navigate('/submission/'+result.submission_id)
 }catch(cause){reportError(cause)}finally{recoveryBusy.value=false}
}
onMounted(load)
</script>

<template>
  <button class="back-button" @click="navigate('/queue')">← 作答与反馈</button>
  <div v-if="loading" class="loading-state" role="status">正在读取作答与历史反馈…</div>
  <div v-else-if="!data" class="error-state"><h2>作答暂时无法读取</h2><button class="secondary-button" @click="() => load()">重试</button></div>
  <template v-else>
    <div class="detail-heading"><div><p class="eyebrow">ANSWER & FEEDBACK</p><h2>{{data.exercise?.title || '作答详情'}}</h2><p class="muted">{{data.course?.title}} · {{data.lesson?.title}} · 第 {{data.attempt_number}} 次作答</p></div><span :class="['status-chip',data.status.toLowerCase()]">{{statusLabel(data.status)}}</span></div>
    <div class="next-action-note top-action"><strong>当前动作</strong><p>{{data.next_action}}</p></div>
    <div class="feedback-layout"><section class="answer-record"><h3>我的原始作答 <span class="muted small">只读保留</span></h3><p v-if="data.exercise" class="muted small">{{data.exercise.prompt}}</p><pre>{{data.answer_text}}</pre></section><section class="review-record"><div class="section-heading"><h3>批改反馈</h3><button class="text-button" @click="load">刷新 ↻</button></div><div v-if="!data.reviews.length" class="waiting-feedback"><span>◷</span><h3>等待批改</h3><p>作答已进入待批改队列。外部 Agent 写回反馈后，在此同步即可查看。</p></div><article v-for="review in data.reviews" :key="review.id" class="review-item"><span :class="['status-chip',review.decision.toLowerCase()]">{{review.decision==='PASSED'?'通过':review.decision==='REVISION_REQUIRED'?'需要修正':'需要复测'}}</span><h3>{{review.summary}}</h3><section v-for="(issue,i) in review.issues||[]" :key="i" class="review-issue"><blockquote>{{issue.quote}}</blockquote><small>{{issue.location}}</small><p><strong>原因</strong> {{issue.reason}}</p><p><strong>正确方向</strong> {{issue.guidance}}</p><p><strong>下一步</strong> {{issue.next_action}}</p></section><div class="markdown-body" v-html="review.rendered_html"/><div class="next-action-note"><strong>下一步</strong><p>{{review.next_action}}</p></div></article></section></div>
    <section class="followup-panel"><h3>在课程内继续学习</h3><p class="muted">这里保留原答案和反馈。修正与复测统一在同一轮课程的答题区完成，避免多处编辑。</p><button class="primary-button" @click="openEditor">{{data.status==='NEEDS_REVISION'?'定位到修正题':data.status==='RETEST_REQUIRED'?'查看复测任务':'回到本轮知识点'}} →</button></section>
    <section v-if="pending" class="recovery-note" role="status"><p>检测到旧版尚未确认的修正/复测请求。原输入和幂等键仍保留。</p><pre>{{pending.answer}}</pre><button class="secondary-button" :disabled="recoveryBusy" @click="retryRecovery">{{recoveryBusy?'正在确认…':'按原幂等键确认旧请求'}}</button><button class="text-button" @click="exportRecovery">导出原输入</button></section><p v-if="cacheError" role="status">本机缓存无法读取或清理；课程数据仍可读取，不会阻止退出。</p>
    <div class="version-chain" v-if="data.parent || data.children.length"><strong>作答版本</strong><button v-if="data.parent" class="text-button" @click="navigate('/submission/'+data.parent.id)">← 第 {{data.parent.attempt_number}} 次作答</button><button v-for="child in data.children" :key="child.id" class="text-button" @click="navigate('/submission/'+child.id)">第 {{child.attempt_number}} 次 {{child.attempt_kind==='REVISION'?'修正':'复测'}} · {{statusLabel(child.status)}} →</button></div>
    <button v-if="data.course" class="secondary-button" @click="navigate('/course/'+data.course.id+'?lesson='+data.lesson?.id)">回到对应知识点 →</button>
  </template>
</template>
