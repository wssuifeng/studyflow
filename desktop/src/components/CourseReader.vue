<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { studyApi } from '../bridge'
import type { CourseDetailData, DocumentReadData } from '../types'
import { navigate, notify, reportError, storageKey } from '../ui'
import KnowledgePointPager from './KnowledgePointPager.vue'
import CourseAnswerSheet from './CourseAnswerSheet.vue'
const props = defineProps<{ id: string; lessonId?: string; initialView?: string }>()
const data = ref<CourseDetailData | null>(null)
const loading = ref(true)
const switching = ref(false)
const progressSaving = ref(false)
const progressFailed = ref(false)
const index = ref(0)
const view = ref(props.initialView === 'answers' ? 'answers' : (localStorage.getItem(storageKey('course-view:' + props.id)) || 'reading'))
const body = ref<HTMLElement | null>(null)
const original = ref<DocumentReadData | null>(null)
const originalOpen = ref(false)
const originalBusy = ref(false)
const originalFailed = ref(false)
const lesson = computed(() => data.value?.lessons[index.value])
const readingPercent = computed(() => data.value?.lessons.length ? Math.round(data.value.lessons.reduce((sum,l)=>sum+l.progress.progress_percent,0)/data.value.lessons.length) : 0)
let timer: ReturnType<typeof setTimeout> | undefined
let ready = false

async function load() {
  loading.value = true
  try {
    data.value = await studyApi.courseDetail(props.id)
    const requested = props.lessonId || data.value.resume_lesson_id
    const found = data.value.lessons.findIndex(item => item.id === requested)
    index.value = found < 0 ? 0 : found
    await nextTick(); await restorePosition()
  } catch (cause) { reportError(cause) }
  finally { loading.value = false; await nextTick(); await restorePosition() }
}
async function restorePosition() {
  ready = false
  await nextTick()
  if (body.value) { try { body.value.scrollTop = JSON.parse(lesson.value?.progress.last_position || '{}').scrollTop || 0 } catch { body.value.scrollTop = 0 } }
  ready = true
}
async function savePosition(complete = false) {
  clearTimeout(timer)
  const current = lesson.value
  if (!current) return
  const scrollTop = body.value?.scrollTop || 0
  const max = Math.max(0, (body.value?.scrollHeight || 0) - (body.value?.clientHeight || 0))
  const traversed = max > 30 ? Math.min(95, Math.round(95 * scrollTop/max)) : 0
  const percent = complete ? 100 : Math.max(current.progress.progress_percent, traversed)
  progressSaving.value = true
  try {
    const saved = await studyApi.saveLearningProgress({course_id:props.id,lesson_id:current.id,progress_percent:percent,last_position:JSON.stringify({scrollTop})})
    current.progress = saved; progressFailed.value = false
    if (complete) notify('已记录这个知识点的阅读完成状态。')
  } catch (cause) { progressFailed.value = true; reportError(cause) }
  finally { progressSaving.value = false }
}
function onScroll() { if (ready) { clearTimeout(timer); timer = setTimeout(() => savePosition(), 750) } }
async function selectLesson(next: number) {
  if (switching.value || next === index.value || next < 0 || next >= (data.value?.lessons.length || 0)) return
  switching.value = true; ready = false
  await savePosition()
  index.value = next; originalOpen.value = false; original.value = null; originalFailed.value = false
  const route = '/course/' + props.id + '?lesson=' + lesson.value?.id
  window.history.replaceState(null, '', '#' + route); localStorage.setItem(storageKey('last-route'), route)
  await restorePosition(); await savePosition(); switching.value = false
}
async function markRead() { if (!progressSaving.value) await savePosition(true) }
async function toggleOriginal() {
  originalOpen.value = !originalOpen.value
  if (!originalOpen.value || original.value) return
  originalBusy.value = true; originalFailed.value = false
  try { original.value = await studyApi.readDocument(lesson.value!.markdown_path) }
  catch (cause) { originalFailed.value = true; reportError(cause) }
  finally { originalBusy.value = false }
}
async function changed() {
  if (!data.value) return
  try {
    const fresh = await studyApi.courseDetail(props.id)
    data.value.course = fresh.course
    for (const row of fresh.lessons) {
      const local = data.value.lessons.find(item=>item.id===row.id)
      if (local) local.exercises = row.exercises
    }
  } catch (cause) { reportError(cause) }
}
const renderedLesson = computed(() => {
  if (!lesson.value) return ''
  const html = new DOMParser().parseFromString(lesson.value.rendered_html, 'text/html')
  const heading = html.querySelector('h1')
  if (heading?.textContent?.replace(/\s+/g, '') === lesson.value.title.replace(/\s+/g, '')) heading.remove()
  return html.body.innerHTML
})
async function selectView(next: string) {
  if (next === view.value) return
  if (view.value === 'reading') await savePosition()
  view.value = next
  localStorage.setItem(storageKey('course-view:' + props.id), next)
  const route = '/course/' + props.id + (next === 'answers' ? '?tab=answers' : '?lesson=' + lesson.value?.id)
  window.history.replaceState(null, '', '#' + route); localStorage.setItem(storageKey('last-route'), route)
  await restorePosition()
}
async function continueReading() {
  await markRead()
  if (index.value < (data.value?.lessons.length || 0) - 1) await selectLesson(index.value + 1)
  else await selectView('answers')
}
onMounted(async()=>{ await load(); if(data.value) await savePosition() })
onBeforeUnmount(()=>{ clearTimeout(timer) })
</script>

<template>
  <div v-if="loading" class="loading-state" role="status">正在打开课程…</div>
  <div v-else-if="!data" class="error-state"><p>课程读取失败，记录未丢失。</p><button class="secondary-button" @click="load">重新读取</button></div>
  <template v-else>
    <button class="back-link" @click="navigate(data.course.plan_line_id ? '/plan/' + data.course.plan_line_id : '/plans')">← {{data.course.plan_line || '我的计划'}}</button>
    <div class="reader-heading"><div><p class="eyebrow accent">课程 {{data.course.sequence || 1}} / {{data.course.total || 1}}</p><h2>{{data.course.title}}</h2><p class="muted">{{data.course.summary}}</p></div><div class="reader-progress"><span>阅读 {{readingPercent}}%</span><span>练习通过 {{data.course.exercise_completed}} / {{data.course.exercise_total}}</span></div></div>
    <nav class="course-mode-tabs" aria-label="课程视图"><button :class="{selected:view==='reading'}" @click="selectView('reading')">知识学习 <span>{{data.lessons.length}}</span></button><button :class="{selected:view==='answers'}" @click="selectView('answers')">课程作答与反馈 <span>{{data.course.exercise_total}}</span></button></nav>
    <CourseAnswerSheet v-if="view==='answers'" :course="data" @changed="changed"/>
    <template v-else-if="lesson">
      <KnowledgePointPager :lessons="data.lessons" :index="index" :busy="switching" @select="selectLesson"/>
      <article class="reader-card seamless-reader">
        <header class="lesson-heading"><div><p class="eyebrow accent">知识点 {{String(index+1).padStart(2,'0')}}</p><h3>{{lesson.title}}</h3></div><span class="muted small">{{lesson.exercises.length ? lesson.exercises.length + ' 道练习将在课程作答页完成' : '阅读材料'}}</span></header>
        <div v-if="lesson.document_status!=='PRESENT'" class="error-state"><h3>学习材料暂时无法读取</h3><p>可以继续课程作答，或修复工作区材料后同步。</p><button class="secondary-button" @click="load">重新读取材料</button></div>
        <div v-else ref="body" class="markdown-body lesson-body" @scroll.passive="onScroll" v-html="renderedLesson"/>
        <div class="reading-actions"><span class="muted small" aria-live="polite">{{progressSaving?'阅读位置保存中…':progressFailed?'阅读位置未能保存':'已记录阅读 '+lesson.progress.progress_percent+'%'}}</span><div><button v-if="progressFailed" class="text-button" @click="savePosition()">重试保存</button><button class="text-button" :disabled="progressSaving || lesson.document_status!=='PRESENT'" @click="markRead">{{lesson.progress.progress_percent===100?'✓ 已读完':'标记读完'}}</button><button class="primary-button" :disabled="switching || progressSaving" @click="continueReading">{{index===data.lessons.length-1 ? '进入整课作答' : '读完，下一知识点'}} →</button></div></div>
        <details class="source-details" :open="originalOpen"><summary @click.prevent="toggleOriginal">查看 Markdown 原文 <span>{{lesson.markdown_path}}</span></summary><div v-if="originalBusy" class="loading-state">正在读取原文…</div><div v-else-if="originalFailed" class="error-state">原文无法读取。<button class="text-button" @click="originalOpen=false; toggleOriginal()">重试</button></div><pre v-else-if="original" class="source-code">{{original.markdown}}</pre></details>
      </article>
    </template>
    <div v-else class="empty-state"><h3>本课暂未导入知识点。</h3><p>外部 Agent 可通过 CLI 为此课程添加材料与练习。</p></div>
  </template>
</template>
