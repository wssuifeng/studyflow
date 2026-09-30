<script setup lang="ts">
import { computed, ref } from 'vue'
import type { QueueData } from '../types'
import { navigate } from '../ui'
const props = defineProps<{ data: QueueData | null }>()
const filter = ref('all')
const tabs = [{id:'all',label:'全部'}, {id:'WAITING_REVIEW',label:'等待批改'}, {id:'NEEDS_REVISION',label:'需要修正'}, {id:'RETEST_REQUIRED',label:'等待复测'}]
const groups = computed(() => {
  const map = new Map<string, { id: string; title: string; plan: string; items: NonNullable<QueueData>['items'] }>()
  for (const item of props.data?.items || []) {
    if (filter.value !== 'all' && item.status !== filter.value) continue
    if (!map.has(item.course_id)) map.set(item.course_id, { id: item.course_id, title: item.course_title, plan: item.plan_line || '学习计划', items: [] })
    map.get(item.course_id)!.items.push(item)
  }
  return [...map.values()]
})
</script>
<template>
  <div class="page-intro"><p class="eyebrow">LEARNING FEEDBACK</p><h2>让每一次反馈，落到下一步行动。</h2><p class="muted">在这里查看作答、理解错误，并继续修正或复测。</p></div>
  <nav class="filter-tabs" aria-label="作答状态"><button v-for="tab in tabs" :key="tab.id" :class="{selected:filter===tab.id}" @click="filter=tab.id">{{tab.label}}<span>{{data?.items.filter(item=>tab.id==='all'||item.status===tab.id).length || 0}}</span></button></nav>
  <div class="course-feedback-list"><article v-for="group in groups" :key="group.id" class="course-feedback-card"><header><div><p class="eyebrow">{{group.plan}}</p><h3>{{group.title}}</h3><p class="muted small">{{group.items.length}} 道题有待处理状态 · 原答案、批改和修正版在课程内集中查看</p></div><button class="primary-button" @click="navigate('/course/' + group.id + '?tab=answers')">打开课程反馈 →</button></header><div class="feedback-question-list"><div v-for="item in group.items" :key="item.id"><span :class="['status-chip',item.status.toLowerCase()]">{{item.label}}</span><span>{{item.exercise_title}}</span><small>{{item.next_action}}</small></div></div></article></div>
  <div v-if="!groups.length" class="empty-state"><span class="empty-symbol">✓</span><h3>{{filter==='all'?'目前没有待处理的作答':'这类作答暂时为空'}}</h3><p>完成课程练习后，批改和修正会出现在这里。</p><button class="secondary-button" @click="navigate('/today')">回到学习控制台 →</button></div>
</template>
