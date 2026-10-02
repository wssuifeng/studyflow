<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, onMounted, ref, watch} from 'vue'
import {studyApi} from '../../../shared/api'
import type {CourseStudyDetailData} from '../../../shared/api/contracts'
import {makeRequestKey, navigate, notify, reportError, setNavigationGuard, statusLabel, storageKey} from '../../../shared/ui'
import KnowledgePointPager from './KnowledgePointPager.vue'
import KnowledgeExercises from '../../learning/components/KnowledgeExercises.vue'
import {useCourseAnswers} from '../../learning/composables/useCourseAnswers'

const props = defineProps<{id: string; lessonId?: string; initialView?: string}>()
const data = ref<CourseStudyDetailData | null>(null)
const answers = useCourseAnswers(data)
const loading = ref(true)
const index = ref(0)
const moving = ref(false)
const submitting = ref(false)
const progressSaving = ref(false)
const progressFailed = ref(false)
const ready = ref(false)
const body = ref<HTMLElement | null>(null)
const newVersionConfirm = ref(false)
const lesson = computed(() => data.value?.lessons[index.value])
const questions = computed(() => answers.rows.value.filter(row => row.lessonId === lesson.value?.id))
const blocked = computed(() => moving.value || submitting.value || !!answers.pending.value && !answers.busy.value || !!answers.recovery.value)
const feedbackNeeded = computed(() => answers.rows.value.filter(row => row.action === 'REVISION' || row.action === 'RETEST').length)
const readingPercent = computed(() => data.value?.lessons.length ? Math.round(data.value.lessons.reduce((sum,l)=>sum+l.progress.progress_percent,0)/data.value.lessons.length) : 0)
const saveLabel = computed(() => answers.busy.value || progressSaving.value ? '保存中…' : answers.saveFailed.value || progressFailed.value ? '保存失败，内容已保留' : answers.dirty.value ? '有修改，正在等待保存' : answers.savedAt.value ? answers.savedAt.value+' 已保存' : '草稿自动保存到本地工作区')
const renderedLesson = computed(() => {
  if (!lesson.value) return ''
  const html = new DOMParser().parseFromString(lesson.value.rendered_html, 'text/html')
  const heading = html.querySelector('h1')
  if (heading?.textContent?.replace(/\s+/g,'') === lesson.value.title.replace(/\s+/g,'')) heading.remove()
  return html.body.innerHTML
})
let timer: ReturnType<typeof setTimeout> | undefined
let progressFlight: Promise<boolean> | null = null

async function load(newVersion = false) {
  loading.value = true
  const keyName = storageKey((newVersion ? 'study-new:' : 'study-open:')+props.id)
  const key = localStorage.getItem(keyName) || makeRequestKey('study-open')
  localStorage.setItem(keyName,key)
  try {
    data.value = await studyApi.openCourseStudy(props.id,key,newVersion)
    localStorage.removeItem(keyName)
    const requested = newVersion ? undefined : props.lessonId || data.value.resume_lesson_id
    const found = data.value.lessons.findIndex(row=>row.id === requested)
    index.value = found < 0 ? 0 : found
    await answers.load()
    if (!props.lessonId && props.initialView === 'answers') {
      const target = answers.rows.value.find(row=>row.action === 'REVISION' || row.action === 'RETEST') || answers.missing.value[0]
      if (target) index.value = data.value.lessons.findIndex(l=>l.id === target.lessonId)
    }
    await nextTick(); await restorePosition()
  } catch (cause) {reportError(cause)}
  finally {loading.value = false; await nextTick(); await restorePosition()}
}
async function restorePosition() {
  ready.value = false; await nextTick()
  if (body.value) {
    try {body.value.scrollTop = JSON.parse(lesson.value?.progress.last_position || '{}').scrollTop || 0}
    catch {body.value.scrollTop = 0}
  }
  ready.value = true
}
async function savePosition(complete = false): Promise<boolean> {
  clearTimeout(timer)
  if (progressFlight && !await progressFlight) return false
  if (!data.value || !lesson.value) return true
  const current = lesson.value
  const scrollTop = body.value?.scrollTop || 0
  const max = Math.max(0,(body.value?.scrollHeight || 0)-(body.value?.clientHeight || 0))
  const traversed = max > 30 ? Math.min(95,Math.round(95*scrollTop/max)) : 0
  const percent = complete ? 100 : Math.max(current.progress.progress_percent,traversed)
  progressSaving.value = true
  progressFlight = (async()=>{
    try {
      const saved = await studyApi.saveStudyProgress({study_session_id:data.value!.study.id,lesson_id:current.id,
        progress_percent:percent,last_position:JSON.stringify({scrollTop}),expected_version:data.value!.study.progress_version})
      data.value!.study.progress_version = saved.version
      current.progress = saved; progressFailed.value = false
      return true
    } catch (cause) {progressFailed.value = true; reportError(cause); return false}
    finally {progressSaving.value = false}
  })()
  try {return await progressFlight} finally {progressFlight = null}
}
function onScroll() {if(ready.value){clearTimeout(timer); timer=setTimeout(()=>savePosition(),750)}}
async function flushCurrent() {
  if (loading.value || !data.value) return true
  if (!(answers.failed.value && !answers.dirty.value && !answers.pending.value) && !await answers.write('save')) return false
  return savePosition()
}
const removeGuard = setNavigationGuard(async()=>{
  if (moving.value || submitting.value) return false
  const ok = await flushCurrent()
  if (!ok) notify('尚未保存成功，当前输入已保留。请先处理保存提示。','info')
  return ok
})
async function selectLesson(next: number) {
  if (moving.value || submitting.value || next===index.value || next<0 || next>=(data.value?.lessons.length || 0)) return false
  moving.value = true; ready.value = false
  try {
    if (!await flushCurrent()) return false
    index.value = next
    const route = '/course/'+props.id+'?lesson='+lesson.value!.id
    window.history.replaceState(null,'','#'+route); localStorage.setItem(storageKey('last-route'),route)
    await restorePosition()
    return await savePosition()
  } finally {moving.value = false; ready.value = true}
}
async function continueLearning() {
  if (moving.value || submitting.value || !await answers.write('save') || !await savePosition(true)) return
  if (index.value<data.value!.lessons.length-1) await selectLesson(index.value+1)
}
async function submitCourse() {
  if (submitting.value || moving.value || !data.value) return
  if (answers.missing.value.length) {
    const first = answers.missing.value[0]!
    const target = data.value.lessons.findIndex(l=>l.id===first.lessonId)
    if (target!==index.value && !await selectLesson(target)) return
    await nextTick()
    const input = document.getElementById('answer-'+first.exercise_id)
    input?.scrollIntoView({block:'center',behavior:'auto'}); input?.focus()
    notify('还有 '+answers.missing.value.length+' 道题未作答，已定位到第一道。','info')
    return
  }
  if (!data.value.course.exercise_total) {
    const unread = data.value.lessons.findIndex((l,i)=>i!==index.value && l.progress.status!=='COMPLETED')
    if (unread>=0) {await selectLesson(unread); notify('请先确认读完这个知识点，再完成本次阅读。','info'); return}
  }
  submitting.value = true
  try {
    if (!await savePosition(true)) return
    if (!data.value.course.exercise_total) {
      data.value = await studyApi.completeCourseReading(data.value.study.id)
      notify('本次阅读学习已完成。')
    } else if (await answers.write('submit')) data.value = await studyApi.courseStudy(data.value.study.id)
  } catch (cause) {reportError(cause)}
  finally {submitting.value = false}
}
async function syncFeedback() {
  if (!await flushCurrent()) return
  try {data.value = await studyApi.courseStudy(data.value!.study.id); await answers.load(); notify('反馈已同步。')}
  catch (cause) {reportError(cause)}
}
async function retrySaving() {
  if (answers.saveFailed.value || answers.pending.value) await answers.retry()
  if (progressFailed.value && data.value) {
    try {
      const fresh = await studyApi.courseStudy(data.value.study.id)
      data.value.study.progress_version = fresh.study.progress_version
      await savePosition()
    } catch (cause) {reportError(cause)}
  }
}
async function startNewVersion() {
  if (!await flushCurrent()) return
  newVersionConfirm.value = false
  await load(true)
}
watch(()=>[props.lessonId,props.initialView],async()=>{
  if(!data.value || loading.value) return
  let target=props.lessonId ? data.value.lessons.findIndex(l=>l.id===props.lessonId) : -1
  if(target<0 && props.initialView==='answers') {
    await syncFeedback()
    const row=answers.rows.value.find(r=>r.action==='REVISION'||r.action==='RETEST') || answers.missing.value[0]
    if(row) target=data.value.lessons.findIndex(l=>l.id===row.lessonId)
  }
  if(target>=0 && target!==index.value) await selectLesson(target)
})
onMounted(()=>load())
onBeforeUnmount(()=>{clearTimeout(timer); removeGuard()})
</script>

<template>
  <div v-if="loading" class="loading-state" role="status">正在恢复课程、草稿与反馈…</div>
  <div v-else-if="!data" class="error-state"><p>课程暂时无法打开，没有覆盖学习记录。</p><button class="secondary-button" @click="load()">重新打开</button></div>
  <div v-else class="study-workspace">
    <button class="back-link" @click="navigate(data.course.plan_line_id ? '/plan/'+data.course.plan_line_id : '/plans')">← {{data.course.plan_line || '我的计划'}}</button>
    <header class="reader-heading"><div><p class="eyebrow accent">课程 {{data.course.sequence || 1}} / {{data.course.total || 1}}</p><h2>{{data.course.title}}</h2><p v-if="data.course.summary" class="muted">{{data.course.summary}}</p></div><div class="reader-progress"><span>{{statusLabel(data.course.study_status || 'IN_PROGRESS')}}</span><span>阅读 {{readingPercent}}% · 本轮通过 {{data.course.exercise_completed}}/{{data.course.exercise_total}}</span><button class="text-button" :disabled="blocked" @click="syncFeedback">同步反馈 ↻</button></div></header>
    <div v-if="data.study.source_changed" class="study-version-note"><span>{{data.study.source_available ? '材料已更新，本次学习仍使用开始时的版本。' : '源文件暂时不可读，仍可使用本次学习的固定材料。'}}</span><button v-if="data.study.source_available && ['PASSED','READ_COMPLETED'].includes(data.course.study_status || '')" class="text-button" @click="newVersionConfirm=true">开始新版学习</button><span v-if="newVersionConfirm">旧答案和反馈将保留。<button class="text-button" @click="startNewVersion">确认开始</button><button class="text-button" @click="newVersionConfirm=false">取消</button></span></div>
    <div v-if="answers.recovery.value" class="recovery-note"><span>发现本设备未保存的内容，请选择恢复；不会自动覆盖工作区版本。</span><button class="secondary-button" @click="answers.restoreCache">恢复可编辑内容</button><button class="text-button" @click="answers.exportRecovery">导出未保存内容</button><button class="text-button" @click="answers.discardCache">使用工作区版本</button></div>
    <div v-if="answers.pending.value || answers.saveFailed.value || progressFailed" class="recovery-note" role="alert"><span>{{answers.pending.value ? '上次写入尚未确认，使用原请求安全重试。' : '保存未完成，输入已保留；请先重试或重新读取。'}}</span><button class="secondary-button" :disabled="!!answers.busy.value" @click="retrySaving">重试保存</button></div>
    <div v-if="answers.failed.value" class="error-state"><p>作答状态读取失败，没有覆盖已有答案。</p><button class="secondary-button" @click="answers.load">重新读取作答</button></div>
    <template v-else-if="lesson">
      <KnowledgePointPager :lessons="data.lessons" :index="index" :busy="blocked" :answer-states="answers.rows.value" @select="selectLesson"/>
      <header class="study-unit-heading"><div><p class="eyebrow accent">知识点 {{String(index+1).padStart(2,'0')}}</p><h3>{{lesson.title}}</h3></div><span class="muted small">{{questions.length}} 道对应练习</span></header>
      <div class="study-unit-layout" :class="{'reading-only':!questions.length}">
        <article class="study-material"><div ref="body" class="markdown-body study-material-body" @scroll.passive="onScroll" v-html="renderedLesson"/><details class="source-details"><summary>查看本轮 Markdown 原文</summary><pre class="source-code">{{lesson.markdown}}</pre></details></article>
        <KnowledgeExercises v-if="!answers.loading.value" :rows="questions" :blocked="blocked"/>
        <div v-else class="loading-state" role="status">正在恢复练习…</div>
      </div>
      <footer class="study-action-bar"><div class="study-save-status" aria-live="polite"><span :class="['save-dot',{'is-error':answers.saveFailed.value || progressFailed,'is-saving':!!answers.busy.value || progressSaving}]"/><div><strong>{{saveLabel}}</strong><span>{{answers.editable.value.length ? '待作答 '+answers.editable.value.length+' 道 · 未答 '+answers.missing.value.length+' 道' : feedbackNeeded ? '按反馈完成修正或复测' : data.course.learning_submitted ? '本次学习已提交，阅读与通过分别记录' : '确认学习不代表长期掌握'}}</span></div></div><div class="study-actions"><button class="text-button" :disabled="blocked || progressSaving" @click="savePosition(true)">{{lesson.progress.status==='COMPLETED'?'✓ 已确认读完':'确认读完'}}</button><button v-if="index<data.lessons.length-1" class="primary-button" :disabled="blocked || progressSaving" @click="continueLearning">下一知识点 →</button><button v-else-if="answers.editable.value.length || !data.course.exercise_total && !data.course.learning_submitted" class="primary-button" :disabled="blocked || progressSaving || answers.loading.value" @click="submitCourse">{{submitting?'提交中…':feedbackNeeded?'提交本轮修正／复测':data.course.exercise_total?'提交并完成本次学习':'完成本次阅读'}} →</button><button v-else class="primary-button" @click="navigate('/today')">继续学习 →</button></div></footer>
    </template>
  </div>
</template>
