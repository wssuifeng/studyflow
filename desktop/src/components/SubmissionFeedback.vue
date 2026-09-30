<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { studyApi } from '../bridge'
import type { SubmissionDetailData } from '../types'
import { makeRequestKey, navigate, notify, reportError, statusLabel, storageKey } from '../ui'
const props = defineProps<{id:string}>()
const data = ref<SubmissionDetailData | null>(null)
const loading = ref(true)
const followupKind = ref<'REVISION' | 'RETEST' | ''>('')
const followupAnswer = ref('')
const followupBusy = ref(false)
const pending = ref<{kind: 'REVISION' | 'RETEST'; answer: string; key: string} | null>(null)
const pendingKey = storageKey('followup:' + props.id)
const canFollowup = computed(() => ['NEEDS_REVISION', 'RETEST_REQUIRED', 'PASSED', 'REVIEWED', 'RECHECKED'].includes(data.value?.status || ''))
const availableKinds = computed(() => {
  if (!data.value || !canFollowup.value) return [] as ('REVISION' | 'RETEST')[]
  return ['REVISION', 'RETEST'] as ('REVISION' | 'RETEST')[]
})
const kindLabel = (kind: 'REVISION' | 'RETEST') => kind === 'REVISION' ? '修正版' : '复测版'
async function load(){
  loading.value=true
  try {
    data.value=await studyApi.submission(props.id)
    const raw=localStorage.getItem(pendingKey)
    if(raw){ try { pending.value=JSON.parse(raw) } catch { localStorage.removeItem(pendingKey) } }
  } catch(cause){reportError(cause)} finally{loading.value=false}
}
function chooseKind(kind: 'REVISION' | 'RETEST'){
  followupKind.value=kind
  if(pending.value?.kind===kind) followupAnswer.value=pending.value.answer
}
async function createFollowup(retry=false){
  if(followupBusy.value || !data.value || !followupKind.value) return
  const kind=followupKind.value
  const answer=retry && pending.value?.kind===kind ? pending.value.answer : followupAnswer.value
  if(!answer.trim()){ notify(`请先写下${kindLabel(kind)}答案。`,'info'); return }
  const key=retry && pending.value?.kind===kind ? pending.value.key : makeRequestKey(kind.toLowerCase())
  followupBusy.value=true
  pending.value={kind,answer,key}; localStorage.setItem(pendingKey,JSON.stringify(pending.value))
  try {
    const result=kind==='REVISION' ? await studyApi.revise({parent_submission_id:data.value.id,answer_text:answer,idempotency_key:key}) : await studyApi.retest({parent_submission_id:data.value.id,answer_text:answer,idempotency_key:key})
    localStorage.removeItem(pendingKey); pending.value=null
    notify(`${kindLabel(kind)}已提交，进入等待批改。`)
    navigate('/submission/'+result.submission_id)
  } catch(cause){reportError(cause)} finally{followupBusy.value=false}
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
    <div class="feedback-layout"><section class="answer-record"><h3>我的原始作答 <span class="muted small">只读保留</span></h3><p v-if="data.exercise" class="muted small">{{data.exercise.prompt}}</p><pre>{{data.answer_text}}</pre></section><section class="review-record"><div class="section-heading"><h3>批改反馈</h3><button class="text-button" @click="load">刷新 ↻</button></div><div v-if="!data.reviews.length" class="waiting-feedback"><span>◷</span><h3>等待批改</h3><p>作答已进入待批改队列。外部 Agent 写回反馈后，在此同步即可查看。</p></div><article v-for="review in data.reviews" :key="review.id" class="review-item"><span :class="['status-chip',review.decision.toLowerCase()]">{{review.decision==='PASSED'?'通过':review.decision==='REVISION_REQUIRED'?'需要修正':'需要复测'}}</span><h3>{{review.summary}}</h3><div class="markdown-body" v-html="review.rendered_html"/><div class="next-action-note"><strong>下一步</strong><p>{{review.next_action}}</p></div></article></section></div>
    <section v-if="availableKinds.length" class="followup-panel"><div><p class="eyebrow accent">NEXT ATTEMPT</p><h3>继续把反馈变成一次新的作答</h3><p class="muted small">原始作答不会被覆盖；新的答案会作为当前作答的子版本进入批改队列。</p></div><div class="followup-kind"><button v-for="kind in availableKinds" :key="kind" :class="{selected:followupKind===kind}" class="secondary-button" @click="chooseKind(kind)">{{kindLabel(kind)}}</button></div><textarea v-if="followupKind" v-model="followupAnswer" rows="8" :disabled="followupBusy" :placeholder="`写下${kindLabel(followupKind)}答案…`"/><div v-if="pending && !followupBusy" class="recovery-note"><span>上一次操作尚未收到确认。</span><button class="text-button" @click="createFollowup(true)">重试上次操作</button></div><div v-if="followupKind" class="composer-actions"><button class="primary-button" :disabled="followupBusy || !followupAnswer.trim()" @click="createFollowup()">{{followupBusy ? '提交中…' : '提交'+kindLabel(followupKind)}} ↗</button></div></section>
    <div class="version-chain" v-if="data.parent || data.children.length"><strong>作答版本</strong><button v-if="data.parent" class="text-button" @click="navigate('/submission/'+data.parent.id)">← 第 {{data.parent.attempt_number}} 次作答</button><button v-for="child in data.children" :key="child.id" class="text-button" @click="navigate('/submission/'+child.id)">第 {{child.attempt_number}} 次 {{child.attempt_kind==='REVISION'?'修正':'复测'}} · {{statusLabel(child.status)}} →</button></div>
    <button v-if="data.course" class="secondary-button" @click="navigate('/course/'+data.course.id+'?lesson='+data.lesson?.id)">回到对应知识点 →</button>
  </template>
</template>
