<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { EngineError, studyApi } from '../bridge'
import type { CourseAnswerState, CourseAnswerWriteParams, CourseDetailData } from '../types'
import { makeRequestKey, navigate, notify, reportError, statusLabel, storageKey } from '../ui'
const props = defineProps<{ course: CourseDetailData }>()
const emit = defineEmits<{ changed: [] }>()
type Row = CourseAnswerState & { title: string; prompt: string; requirements: string; lessonTitle: string; answer: string; savedAnswer: string }
const rows = ref<Row[]>([])
const loading = ref(true)
const failed = ref(false)
const busy = ref('')
const savedAt = ref('')
const cacheKey = storageKey('course-answers:' + props.course.course.id)
const requestKey = storageKey('course-request:' + props.course.course.id)
const recovery = ref<Record<string, string> | null>(null)
const pending = ref<{ operation: 'save' | 'submit'; params: CourseAnswerWriteParams } | null>(null)
const editable = computed(() => rows.value.filter(row => row.action !== 'LOCKED'))
const dirty = computed(() => editable.value.some(row => row.answer !== row.savedAnswer))
const filled = computed(() => editable.value.filter(row => row.answer.trim()).length)
const waiting = computed(() => rows.value.filter(row => row.submission?.status === 'WAITING_REVIEW').length)
const passed = computed(() => rows.value.filter(row => ['PASSED', 'RECHECKED', 'REVIEWED'].includes(row.submission?.status || '')).length)
function keepCache() {
  if (loading.value || busy.value) return
  const buffer = Object.fromEntries(editable.value.map(row => [row.exercise_id, row.answer]))
  if (dirty.value) localStorage.setItem(cacheKey, JSON.stringify(buffer))
}
watch(rows, keepCache, { deep: true, flush: 'sync' })
async function load() {
  loading.value = true; failed.value = false
  try {
    const sheet = await studyApi.courseAnswers(props.course.course.id)
    rows.value = props.course.lessons.flatMap(lesson => lesson.exercises.map(exercise => {
      const state = sheet.answers.find(item => item.exercise_id === exercise.id)
      if (!state) throw new Error('课程题目状态不完整，请重新同步课程。')
      const answer = state.draft?.answer_text || (state.action === 'LOCKED' ? state.submission?.answer_text || '' : '')
      return { ...state, title: exercise.title, prompt: exercise.prompt, requirements: exercise.requirements,
        lessonTitle: lesson.title, answer, savedAnswer: answer }
    }))
    recovery.value = null
    const cached = localStorage.getItem(cacheKey)
    if (cached) {
      try {
        const values = JSON.parse(cached)
        if (values && typeof values === 'object' && editable.value.some(row => typeof values[row.exercise_id] === 'string' && values[row.exercise_id] !== row.answer)) recovery.value = values
        else localStorage.removeItem(cacheKey)
      } catch { localStorage.removeItem(cacheKey) }
    }
    const request = localStorage.getItem(requestKey)
    if (request) {
      try { const value = JSON.parse(request); if (value.params?.course_id === props.course.course.id && ['save', 'submit'].includes(value.operation)) pending.value = value }
      catch { localStorage.removeItem(requestKey) }
    }
  } catch (cause) { failed.value = true; reportError(cause) }
  finally { loading.value = false }
}
function restoreCache() {
  if (!recovery.value) return
  for (const row of editable.value) if (typeof recovery.value[row.exercise_id] === 'string') row.answer = recovery.value[row.exercise_id]!
  recovery.value = null
  notify('已恢复本设备的未保存内容。整课保存后会写入工作区。', 'info')
}
function discardCache() { recovery.value = null; localStorage.removeItem(cacheKey) }
async function write(operation: 'save' | 'submit', retry = false) {
  if (busy.value || failed.value || (!retry && (!editable.value.length || recovery.value || pending.value))) return
  if (!retry && operation === 'submit' && filled.value !== editable.value.length) {
    notify('本课还有 ' + (editable.value.length - filled.value) + ' 道空白题。补齐后再统一提交。', 'info')
    document.querySelector<HTMLTextAreaElement>('.course-answer-sheet textarea:placeholder-shown')?.focus(); return
  }
  const params: CourseAnswerWriteParams = retry && pending.value ? pending.value.params : {
    course_id: props.course.course.id,
    answers: editable.value.map(row => ({ exercise_id: row.exercise_id, answer_text: row.answer,
      ...(row.draft ? { submission_id: row.draft.id, expected_version: row.draft.version } : {}),
      ...(row.submission && row.action !== 'FIRST' ? { parent_submission_id: row.submission.id } : {}) })),
    idempotency_key: makeRequestKey('course-' + operation),
  }
  keepCache(); busy.value = operation
  pending.value = { operation, params }; localStorage.setItem(requestKey, JSON.stringify(pending.value))
  try {
    const result = operation === 'save' ? await studyApi.saveCourseAnswers(params) : await studyApi.submitCourseAnswers(params)
    pending.value = null; localStorage.removeItem(requestKey); localStorage.removeItem(cacheKey)
    savedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    await load(); emit('changed')
    notify(operation === 'save' ? '整课草稿已保存，共 ' + result.submissions.length + ' 道题。' : '本课已统一提交，共 ' + result.submissions.length + ' 道题等待批改。')
  } catch (cause) {
    if (cause instanceof EngineError && !['INTERNAL_ERROR', 'DATABASE_ERROR', 'CONNECTION_FAILED', 'BRIDGE_UNAVAILABLE'].includes(cause.code)) {
      pending.value = null; localStorage.removeItem(requestKey)
    }
    reportError(cause)
  } finally { busy.value = '' }
}
function beforeUnload(event: BeforeUnloadEvent) { keepCache(); if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => { keepCache(); window.removeEventListener('beforeunload', beforeUnload) })
</script>

<template>
  <section class="course-answer-sheet" aria-label="整课作答与反馈">
    <div class="answer-sheet-heading"><div><p class="eyebrow accent">COURSE ANSWER SHEET</p><h3>把这一课的理解，连成完整答案。</h3><p class="muted">本课 {{ rows.length || course.course.exercise_total }} 道练习 · 统一保存与提交，原答案和每次反馈按题保留。</p></div><span v-if="passed" class="status-chip passed">已通过 {{ passed }} / {{ rows.length }}</span></div>
    <div v-if="loading" class="loading-state" role="status">正在恢复本课答案与反馈…</div>
    <div v-else-if="failed" class="error-state"><p>作答状态读取失败，未覆盖任何内容。</p><button class="secondary-button" @click="load">重新读取</button></div>
    <template v-else>
      <div v-if="recovery" class="recovery-note"><span>发现本设备的未保存内容。请先选择恢复或使用工作区草稿。</span><button class="secondary-button" @click="restoreCache">恢复未保存内容</button><button class="text-button" @click="discardCache">使用工作区版本</button></div>
      <div v-if="pending" class="recovery-note"><span>上次{{pending.operation === 'save' ? '保存' : '提交'}}尚未确认，内容已保留。使用原请求安全重试，不会重复提交。</span><button class="secondary-button" :disabled="!!busy" @click="write(pending.operation, true)">{{busy ? '确认中…' : '重试原请求'}}</button></div>
      <article v-for="(row, i) in rows" :key="row.exercise_id" class="answer-question">
        <header class="question-heading"><span class="question-index">{{ String(i + 1).padStart(2, '0') }}</span><div><p class="muted small">{{ row.lessonTitle }}</p><h4>{{ row.title }}</h4></div><span v-if="row.submission" :class="['status-chip', row.submission.status.toLowerCase()]">{{ statusLabel(row.submission.status) }}</span><span v-else-if="row.draft" class="status-chip">已存草稿</span></header>
        <p class="exercise-prompt">{{ row.prompt }}</p>
        <details v-if="row.requirements" class="question-requirements"><summary>作答约束</summary><p>{{ row.requirements }}</p></details>
        <div v-if="row.submission" class="inline-feedback">
          <details :open="row.action !== 'LOCKED' || !!row.submission.reviews.length"><summary>{{row.action === 'LOCKED' ? '我的已提交答案' : '上次提交的原答案'}}</summary><pre class="answer-text">{{row.submission.answer_text}}</pre></details>
          <section v-for="review in row.submission.reviews" :key="review.id" class="inline-review"><div class="review-title"><strong>{{review.summary}}</strong><span class="muted small">{{statusLabel(review.decision)}}</span></div><div v-if="review.rendered_html" class="markdown-body" v-html="review.rendered_html"/><p class="review-next-action">下一步：{{review.next_action || row.submission.next_action}}</p></section>
          <p v-if="!row.submission.reviews.length" class="waiting-note">答案已保留，等待外部 Agent 批改。可继续阅读本课或学习其他课程。</p>
          <button class="text-button history-link" @click="navigate('/submission/' + row.submission!.id)">查看这道题的版本历史 ↗</button>
        </div>
        <template v-if="row.action !== 'LOCKED'">
          <label :for="'course-answer-' + row.exercise_id" class="answer-label">{{row.action === 'REVISION' ? '本次修正版' : row.action === 'RETEST' ? '本次复测答案' : '我的答案'}}<span>{{row.answer.length}} 字</span></label>
          <textarea :id="'course-answer-' + row.exercise_id" v-model="row.answer" :disabled="!!busy || !!pending || !!recovery" rows="6" placeholder="写下你的理解、推导或代码。所有题目完成后，在页末统一提交。" spellcheck="false"/>
        </template>
      </article>
      <div v-if="!rows.length" class="empty-state"><h3>本课目前没有练习。</h3><p>课程材料不会自动产生题目。外部 Agent 可通过 CLI 导入带练习的知识点。</p></div>
      <div v-if="rows.length" class="course-write-bar">
        <div class="write-status" aria-live="polite"><strong>{{editable.length ? '已填写 ' + filled + ' / ' + editable.length + ' 道待作答题' : waiting ? '本课 ' + waiting + ' 道题等待批改' : '本课练习已完成'}}</strong><span>{{busy ? (busy === 'save' ? '整课保存中…' : '整课提交中…') : dirty ? '未保存内容已临时保存在此设备' : savedAt ? savedAt + ' 已保存到工作区' : '阅读记录与练习通过状态分别保存'}}</span></div>
        <div v-if="editable.length" class="write-buttons"><button class="secondary-button" :disabled="!!busy || !!pending || !!recovery" @click="write('save')">{{busy === 'save' ? '保存中…' : '保存整课草稿'}}</button><button class="primary-button" :disabled="!!busy || !!pending || !!recovery" @click="write('submit')">{{busy === 'submit' ? '提交中…' : '提交本课答案'}} <span>→</span></button></div>
        <button v-else class="secondary-button" @click="navigate('/plans')">继续我的计划 →</button>
      </div>
    </template>
  </section>
</template>
