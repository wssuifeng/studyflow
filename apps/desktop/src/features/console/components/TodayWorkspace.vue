<script setup lang="ts">
import { computed,ref } from 'vue'
import type { CourseProgress, TodayData } from '../../../shared/api/contracts'
import { navigate, statusLabel } from '../../../shared/ui'
import {courseAction} from '../../../shared/ui/nextAction'
const search=ref('')
const props = defineProps<{ data: TodayData }>()
const groups = computed(() => {
  const map = new Map<string, { id: string | null; name: string; courses: CourseProgress[]; scheduled: CourseProgress[]; active: boolean }>()
  for (const course of props.data.courses) {
    const key = course.plan_line_id || course.plan_line || 'unassigned'
    if (!map.has(key)) map.set(key, { id: course.plan_line_id || null, name: course.plan_line || '未归类课程', courses: [], scheduled: [], active: false })
    const group = map.get(key)!
    group.courses.push(course)
    if (course.schedule?.date === props.data.date) group.scheduled.push(course)
    if (course.id === props.data.current_course?.id) group.active = true
  }
  return [...map.values()].filter(g=>!search.value||g.name.includes(search.value)).sort((a, b) => Number(b.active) - Number(a.active)).map(group => ({ ...group,
    visible: group.scheduled.length ? group.scheduled : group.courses.filter(c => !c.learning_submitted).slice(0, 3),
  }))
})
</script>
<template>
  <div class="console-intro"><div><p class="eyebrow accent">YOUR LEARNING SPACE</p><h2>今日学习</h2><p class="muted">继续计划里的课程，或处理已经返回的反馈。</p></div><button class="text-button" @click="navigate('/plans')">所有学习计划 ↗</button></div>
  <input v-if="data.courses.length>6" v-model="search" class="inline-search" aria-label="查找学习计划" placeholder="查找计划…"/>
  <section v-if="groups.length" class="today-plan-list" aria-label="今日学习计划">
    <article v-for="group in groups" :key="group.id || group.name" :class="['today-plan-card', { 'current-plan': group.active }]">
      <header class="today-plan-header"><div><p class="eyebrow">{{group.scheduled.length ? '今日安排' : '当前可继续 · 未安排今日时间'}}</p><h3>{{group.name}}</h3></div><button v-if="group.id" class="text-button" @click="navigate('/plan/' + group.id)">计划详情 →</button></header>
      <div class="plan-courses"><button v-for="course in group.visible" :key="course.id" :class="['plan-course-item', { current: course.id === data.current_course?.id }]" @click="navigate('/course/' + course.id)">
        <span class="course-sequence">{{String(course.sequence || 1).padStart(2,'0')}}<small>/ {{course.total}}</small></span>
        <div class="plan-course-copy"><div class="course-title-line"><h4>{{course.title}}</h4><span v-if="course.id === data.current_course?.id" class="current-course-label">当前推进</span></div><p>{{course.knowledge_total}} 个知识点 · {{course.exercise_total}} 道练习<span v-if="course.schedule?.start_time"> · {{course.schedule.start_time.slice(0,5)}}{{course.schedule.end_time ? '—' + course.schedule.end_time.slice(0,5) : ''}}</span></p></div>
        <div class="course-row-progress"><span>{{statusLabel(course.study_status || 'NOT_STARTED')}}</span><span class="course-enter">{{courseAction(course)}} <b>→</b></span></div>
      </button></div>
      <p v-if="!group.visible.length" class="plan-empty-note">这个计划暂时没有未提交课程，可以进入详情回看或处理反馈。</p>
      <footer v-if="!group.scheduled.length && group.courses.length > group.visible.length" class="today-plan-footer"><span>{{group.courses.length}} 门顺序课程</span><button v-if="group.id" class="text-button" @click="navigate('/plan/' + group.id)">查看完整学习路径 →</button></footer>
    </article>
  </section>
  <section v-else class="empty-state"><span class="empty-symbol">✦</span><h2>留一个位置给新的知识。</h2><p>外部 Agent 可以通过 CLI 创建计划、顺序课程和练习。</p><button class="primary-button" @click="navigate('/plans')">打开我的计划 →</button></section>
  <button v-if="data.queue_counts.waiting_review || data.queue_counts.needs_revision || data.queue_counts.waiting_retest" class="console-feedback-summary" @click="navigate('/queue')"><span>◎</span><div><strong>作答与反馈</strong><p>等待批改 {{data.queue_counts.waiting_review}} · 需要修正 {{data.queue_counts.needs_revision}} · 需要复测 {{data.queue_counts.waiting_retest}}</p></div><span>→</span></button>
</template>
