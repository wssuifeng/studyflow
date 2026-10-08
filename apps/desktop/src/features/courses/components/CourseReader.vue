<script setup lang="ts">
import {computed, inject, nextTick, onBeforeUnmount, onMounted, onUpdated, ref, watch} from 'vue'
import {isTauri, studyApi} from '../../../shared/api'
import type {CourseStudyDetailData} from '../../../shared/api/contracts'
import {makeRequestKey, navigate, notify, reportError, statusLabel, windowStorageKey} from '../../../shared/ui'
import KnowledgePointPager from './KnowledgePointPager.vue'
import CourseOutline from './CourseOutline.vue'
import {activeTheme} from '../../../shared/themes'
import {soundEnabled,setSoundEnabled} from '../../../shared/ui/interaction'
import TeachingContent from './TeachingContent.vue'
import ThemeReadingArtwork from '../../../shared/components/ThemeReadingArtwork.vue'
import DisplaySlot from '../../../shared/components/DisplaySlot.vue'
import { activeDisplay } from '../../../shared/themes/display-loader'
import LeaveStudyDialog from './LeaveStudyDialog.vue'
import CourseToolsSidebar from './CourseToolsSidebar.vue'
import StudyActions from './StudyActions.vue'
import StudyRecovery from './StudyRecovery.vue'
import {learningContent} from '../learningContent'
import {workspacePanelKey} from '../../../shared/layout/workspacePanel'
import {restoreDockLayout} from '../dock/restore'
import {interactionFeedback} from '../../../shared/ui/interaction'
import {invoke} from '@tauri-apps/api/core'
import {highlightNotebookExcerpts} from '../../notes/highlight'
import {usePlanNotebook} from '../../notes/composables/usePlanNotebook'
import {activateTool,closeTool,normalizeDock,reorderTools,splitTools,type ToolTab} from '../dock/state'
import {addDetachedNote,openToolWindow,listToolWindows,prepareTools,releaseTools,suspendTools,toolsEvent,type ToolContext} from '../dock/toolWindows'
import {emitTo,listen} from '@tauri-apps/api/event'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import {useCourseAnswers} from '../../learning/composables/useCourseAnswers'

const props = defineProps<{id: string; lessonId?: string; initialView?: string; studyId?: string; exerciseId?: string}>()
const data = ref<CourseStudyDetailData | null>(null)
const detached=ref<ToolTab[]>([])
const answersOwner=computed(()=>!detached.value.includes('exercises'))
const notesOwner=computed(()=>!detached.value.includes('notes'))
const answers = useCourseAnswers(data,answersOwner)
const notes = usePlanNotebook(computed(()=>data.value?.course.plan_line_id||undefined),notesOwner)
const shellPanel=inject(workspacePanelKey)
const panelOwner=Symbol('course-panel')
const sequenceTheme=computed(()=>activeTheme.value.id==='sequence-light')
let storedDockLayout:string|null=null
try {storedDockLayout=localStorage.getItem(windowStorageKey('course-dock'))}catch {/* Layout preference is optional. */}
const dock=ref(storedDockLayout?restoreDockLayout(storedDockLayout):normalizeDock({width:activeDisplay.value.tools_width}))
const tab=computed<ToolTab>({get:()=>dock.value.panes[0]||'exercises',set:t=>{dock.value=activateTool(dock.value,t)}})
const sidebarOpen=computed({get:()=>!dock.value.collapsed,set:open=>{dock.value={...dock.value,collapsed:!open}}})
const dockMaxWidth=computed(()=>shellPanel?.geometry.value.maxWidth||820)
const layoutClass=computed(()=>['study-unit-layout',sidebarOpen.value?'tools-visible':'tools-hidden',shellPanel?.geometry.value.compact?'tools-compact':''])
const readingShellProps=computed(()=>({class:layoutClass.value,'data-reading-shell':activeDisplay.value.reading_shell,style:{'--study-height':layoutHeight.value+'px'}}))
const selection=ref<{text:string;x:number;y:number;blockId?:string}|null>(null)
const toolsToggle=ref<HTMLButtonElement|null>(null)
async function openPractice(exerciseId:string) {
 if(blocked.value)return
 dock.value=activateTool(dock.value,'exercises')
 if(detached.value.includes('exercises')) {
   if(!await openToolWindow('exercises',context.value!)){notify('练习窗口尚未就绪，请重试。','info');return}
   await emitTo('tool-exercises','studyflow-focus-exercise',{exerciseId,lessonId:lesson.value?.id})
   return
 }
 await nextTick()
 requestAnimationFrame(()=>{
   const row=document.querySelector<HTMLElement>(`[data-exercise="${exerciseId}"]`)
   row?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'})
   row?.querySelector<HTMLTextAreaElement>('textarea')?.focus({preventScroll:true})
 })
}
async function jumpToBlock(lessonIndex:number,blockId:string) {
 if(index.value!==lessonIndex)await selectLesson(lessonIndex)
 if(index.value!==lessonIndex)return
 if(shellPanel?.geometry.value.compact||dock.value.full)sidebarOpen.value=false
 await nextTick()
 body.value?.querySelector<HTMLElement>(`[data-content-block="${blockId}"]`)?.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'})
}
async function toggleTools() {
 if(sidebarOpen.value)sidebarOpen.value=false
 else dock.value=activateTool(dock.value,dock.value.panes[0]||'exercises')
 interactionFeedback('open')
}
watch(sidebarOpen,async(open,previous)=>{
 await nextTick()
 if(open)document.getElementById('dock-tab-'+tab.value)?.focus({preventScroll:true})
 else if(previous)toolsToggle.value?.focus({preventScroll:true})
})
let readingRestoreTimer: ReturnType<typeof setTimeout> | undefined
function applyPendingReadingScroll(target:number): boolean {
 const current=body.value?.isConnected ? body.value : document.querySelector<HTMLElement>('[data-reading-scroll-container]')
 if(!current?.getClientRects().length)return false
 if(body.value!==current)body.value=current
 current.scrollTop=target
 return true
}
async function restoreReadingScrollAfterLayout(saved:number) {
 const target=Math.max(0,Math.round(saved))
 restoringReadingScroll.value=true
 pendingReadingScroll.value=target
 readingScrollTop.value=target
 const apply=()=>applyPendingReadingScroll(target)
 try {
  // Theme shells can replace the reading container after the Vue update. Apply to
  // the current connected container, not only the pre-switch template ref.
  await nextTick()
  apply()
  for (let i=0;i<4;i++) {
   await new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()))
   apply()
   await nextTick()
  }
  if(readingRestoreTimer)clearTimeout(readingRestoreTimer)
  readingRestoreTimer=setTimeout(()=>{
   apply()
   pendingReadingScroll.value=null
   readingRestoreTimer=undefined
  },180)
 } finally {
  restoringReadingScroll.value=false
 }
}
watch(()=>activeTheme.value.id,async()=>{
 // Capture before the theme-controlled template/layout update; post-flush capture would already see 0.
 const saved=body.value?.scrollTop ?? readingScrollTop.value
 await restoreReadingScrollAfterLayout(saved)
},{flush:'sync'})
const context=computed<ToolContext|null>(()=>data.value?.course.plan_line_id?{
 courseId:data.value.course.id,studyId:data.value.study.id,planId:data.value.course.plan_line_id,
 planTitle:data.value.course.plan_line||'学习计划',lessonId:lesson.value?.id}:null)
watch(dock,value=>{try{localStorage.setItem(windowStorageKey('course-dock'),JSON.stringify(value))}catch {/* Layout is optional. */}},{deep:true})
const openingWindow = ref(false)

const loading = ref(true)
const index = ref(0)
const moving = ref(false)
const submitting = ref(false)
const progressSaving = ref(false)
const progressFailed = ref(false)
const ready = ref(false)
const body = ref<HTMLElement | null>(null)
const restoringReadingScroll=ref(false)
const pendingReadingScroll=ref<number|null>(null)
const readingScrollTop=ref(0)
const studyLayout = ref<HTMLElement | null>(null)
const layoutHeight = ref(520)
const actionBar = ref<HTMLElement | null>(null)
const layoutOverflow = ref(false)
const newVersionConfirm = ref(false)
const openingRequest=ref<{key:string;newVersion:boolean;reviewRound:boolean}|null>(null)
const lesson = computed(() => data.value?.lessons[index.value])
watch(()=>[dock.value.collapsed,dock.value.width,dock.value.full,loading.value,!!lesson.value,answers.failed.value],()=>shellPanel?.publish(panelOwner,{visible:!dock.value.collapsed&&!loading.value&&!!lesson.value&&!answers.failed.value,width:dock.value.width,full:dock.value.full}),{immediate:true})
const blocked = computed(() => openingWindow.value || moving.value || submitting.value || !!answers.pending.value && !answers.busy.value || !!answers.recovery.value || !!notes.pending.value && !notes.busy.value || !!notes.recovery.value)
const feedbackNeeded = computed(() => answers.rows.value.filter(row => row.action === 'REVISION' || row.action === 'RETEST').length)
const readingPercent = computed(() => data.value?.lessons.length ? Math.round(data.value.lessons.reduce((sum,l)=>sum+l.progress.progress_percent,0)/data.value.lessons.length) : 0)
const planPosition = computed(() => ({current: Math.max(1, data.value?.course.sequence || 1), total: Math.max(1, data.value?.course.total || 1)}))
const courseProgressPercent = computed(() => Math.max(0, Math.min(100, Math.round(data.value?.course.progress_percent || 0))))
const courseStatus = computed(() => statusLabel(data.value?.course.study_status || 'IN_PROGRESS'))
const saveLabel = computed(() => answers.busy.value || notes.busy.value || progressSaving.value ? '保存中…' : answers.saveFailed.value || notes.saveFailed.value || progressFailed.value ? '保存失败，内容已保留' : answers.dirty.value || notes.dirty.value ? '有修改，正在等待保存' : answers.savedAt.value || notes.savedAt.value ? (answers.savedAt.value || notes.savedAt.value)+' 已保存' : '答案与笔记自动保存到本地工作区')
const renderedLesson = computed(() => lesson.value && data.value ? highlightNotebookExcerpts(learningContent(lesson.value.rendered_html,lesson.value.title),notes.blocks.value,data.value.study.id,lesson.value.id) : '')
const documentHeadings=ref<{id:string;title:string;level:number}[]>([])
const activeHeading=ref('')
function collectDocumentHeadings() {
 const nodes=body.value?.querySelectorAll<HTMLElement>('.legacy-teaching-content h1,.legacy-teaching-content h2,.legacy-teaching-content h3,.legacy-teaching-content h4,.teaching-block-heading h4,.teaching-steps h5')||[]
 documentHeadings.value=Array.from(nodes).map((node,i)=>{
  const id=node.id||'section-'+lesson.value?.id+'-'+i;node.id=id
  const level=node.closest('.teaching-block-heading')?2:node.tagName==='H5'?3:Math.max(2,Number(node.tagName.slice(1)))
  return {id,title:node.textContent?.trim()||'',level}
 }).filter(item=>item.title)
 updateActiveHeading()
}
function updateActiveHeading() {
 if(!body.value)return
 const top=body.value.getBoundingClientRect().top+96
 const current=documentHeadings.value.filter(item=>{const node=document.getElementById(item.id);return node&&node.getBoundingClientRect().top<=top}).at(-1)
 activeHeading.value=current?.id||documentHeadings.value[0]?.id||''
}
async function jumpToHeading(id:string) {
 if(shellPanel?.geometry.value.compact||dock.value.full)sidebarOpen.value=false
 await nextTick()
 const node=document.getElementById(id)
 if(node&&body.value?.contains(node)){node.scrollIntoView({block:'start',behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});activeHeading.value=id}
}
function toggleSound(){setSoundEnabled(!soundEnabled.value);if(soundEnabled.value)interactionFeedback('preview')}
watch(()=>[renderedLesson.value,lesson.value?.id,lesson.value?.content_blocks],async()=>{await nextTick();collectDocumentHeadings()},{flush:'post'})
let timer: ReturnType<typeof setTimeout> | undefined
let progressFlight: Promise<boolean> | null = null

async function load(newVersion = false,reviewRound=false) {
  loading.value = true
  const keyName = windowStorageKey((newVersion ? 'study-new:' : 'study-open:')+props.id)
  let key=openingRequest.value?.key||makeRequestKey('study-open')
  try{key=localStorage.getItem(keyName)||key;localStorage.setItem(keyName,key)}catch{/* opening is independent of optional local storage */}
  if(openingRequest.value){newVersion=openingRequest.value.newVersion;reviewRound=openingRequest.value.reviewRound}
  openingRequest.value={key,newVersion,reviewRound}
  try {
    data.value = props.studyId && !newVersion && !reviewRound ? await studyApi.courseStudy(props.studyId) : await studyApi.openCourseStudy(props.id,key,newVersion,reviewRound)
    openingRequest.value=null
    if(data.value.course.id!==props.id){data.value=null;throw new Error('学习轮次与课程不匹配。')}
    if(!data.value.study.is_current){const source='/source/'+data.value.study.id+'?lesson='+(props.lessonId||data.value.lessons[0]?.id);data.value=null;await navigate(source);return}
    try{localStorage.removeItem(keyName)}catch{/* content is frozen in the workspace */}
    const requested = newVersion ? undefined : props.lessonId || data.value.resume_lesson_id
    const found = data.value.lessons.findIndex(row=>row.id === requested)
    index.value = found < 0 ? 0 : found
    detached.value=(await listToolWindows()).map(w=>w.tool)
    await Promise.all([answers.load(), notes.load()])
    await syncToolContext()
    if(['answers','exercises'].includes(props.initialView||'')) dock.value=activateTool(dock.value,'exercises')
    if (!props.lessonId && props.initialView === 'answers') {
      const target = answers.rows.value.find(row=>row.action === 'REVISION' || row.action === 'RETEST') || answers.missing.value[0]
      if (target) index.value = data.value.lessons.findIndex(l=>l.id === target.lessonId)
    }
    await nextTick(); await restorePosition()
    if(props.exerciseId)await openPractice(props.exerciseId)
  } catch (cause) {reportError(cause)}
  finally {loading.value = false; await nextTick(); await restorePosition()}
}
function fitStudyLayout() {
  if (!studyLayout.value?.getClientRects().length) return
  // Geometry belongs to the application shell, not the shrinking reading column.
  if(dockMaxWidth.value<560&&!dock.value.full&&dock.value.panes.length>1)dock.value={...dock.value,panes:dock.value.panes.slice(0,1)}
  const footerHeight = actionBar.value?.getBoundingClientRect().height || 73
  const available = Math.round(window.innerHeight - studyLayout.value.getBoundingClientRect().top - footerHeight - 34)
  layoutOverflow.value = available < 160
  layoutHeight.value = Math.max(160, available)
}
async function restorePosition() {
  ready.value = false; await nextTick()
  if (body.value) {
    try {readingScrollTop.value=JSON.parse(lesson.value?.progress.last_position || '{}').scrollTop || 0}
    catch {readingScrollTop.value=0}
    body.value.scrollTop=readingScrollTop.value
  }
  fitStudyLayout(); collectDocumentHeadings(); ready.value = true
}
async function savePosition(complete = false): Promise<boolean> {
  if (safeExit.leaving.value) return true
  clearTimeout(timer)
  if (progressFlight && !await progressFlight) return false
  if (!data.value || !lesson.value) return true
  const current = lesson.value
  const scrollTop = body.value?.getClientRects().length ? body.value.scrollTop : readingScrollTop.value
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
    } catch (cause) {if (safeExit.leaving.value) return false; progressFailed.value = true; reportError(cause); return false}
    finally {progressSaving.value = false}
  })()
  try {return await progressFlight} finally {progressFlight = null}
}
function onScroll() {updateActiveHeading();if(restoringReadingScroll.value)return;if(ready.value&&body.value?.getClientRects().length){readingScrollTop.value=body.value.scrollTop;clearTimeout(timer); timer=setTimeout(()=>savePosition(),750)}}
async function flushCurrent() {
  if (loading.value || !data.value) return true
  const peers=await prepareTools()
  if(!peers.ok) {notify('独立工具窗口尚未保存，请先处理那里的输入。','info');return false}
  if(!answersOwner.value&&!answers.dirty.value&&!answers.pending.value&&!answers.recovery.value)await answers.load()
  if (!(answers.failed.value && !answers.dirty.value && !answers.pending.value) && !await answers.write('save')) return false
  if (!(notes.failed.value && !notes.dirty.value && !notes.pending.value) && !await notes.save()) return false
  return savePosition()
}
const safeExit = useSafeStudyExit({
  busy: () => moving.value || submitting.value || !!answers.busy.value || notes.busy.value,
  hasProblem: () => !!(answers.saveFailed.value || notes.saveFailed.value || progressFailed.value || answers.pending.value || notes.pending.value || answers.recovery.value || notes.recovery.value),
  flush: flushCurrent, retry: retrySaving,
  suspend: () => {clearTimeout(timer); answers.suspendAutosave(); notes.suspendAutosave(); if(safeExit.dialog.value?.path==='close-window'){void suspendTools();window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}},
})
function exportUnsaved() {
  try {
    const content = {study_session_id: data.value?.study.id, exported_at: new Date().toISOString(),
      answers: answers.rows.value.map(row => ({exercise_id: row.exercise_id, answer_text: row.answer})),
      recovered_answers: answers.recovery.value, pending_answers: answers.pending.value,
      notes: notes.blocks.value,
      recovered_notes: notes.recovery.value, pending_note: notes.pending.value}
    const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], {type: 'application/json;charset=utf-8'}))
    const link = document.createElement('a'); link.href = url; link.download = 'StudyFlow-未保存学习内容.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {reportError(cause)}
}
async function moveTo(next:number) {
 index.value=next;selection.value=null;interactionFeedback('move')
 const route='/course/'+props.id+'?lesson='+lesson.value!.id
 window.history.replaceState(null,'','#'+route);localStorage.setItem(windowStorageKey('last-route'),route)
 await restorePosition();return savePosition()
}
async function selectLesson(next:number) {
 if(moving.value||submitting.value||next===index.value||next<0||next>=(data.value?.lessons.length||0))return false
 moving.value=true;ready.value=false
 try {if(!await flushCurrent())return false;return await moveTo(next)}
 finally {moving.value=false;ready.value=true}
}
async function confirmRead() {if(await savePosition(true))interactionFeedback('complete')}
async function continueLearning() {
 if(moving.value||submitting.value||!data.value)return
 moving.value=true;ready.value=false
 try {
  if(!await flushCurrent()||!await savePosition(true))return
  if(index.value<data.value.lessons.length-1)await moveTo(index.value+1)
 }finally{moving.value=false;ready.value=true}
}
async function submitCourse() {
  if (submitting.value || moving.value || !data.value || !await flushCurrent()) return
  if (answers.missing.value.length) {
    const first = answers.missing.value[0]!
    const target = data.value.lessons.findIndex(l=>l.id===first.lessonId)
    if (target!==index.value && !await selectLesson(target)) return
    sidebarOpen.value = true; tab.value = 'exercises'
    if(detached.value.includes('exercises')){await detachTool('exercises');await emitTo('tool-exercises','studyflow-tool-focus-lesson',{lessonId:first.lessonId})}
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
  const peers=await prepareTools('hold')
  try {
    if(!peers.ok){notify('独立工具窗口保存未确认，本轮没有提交。','info');return}
    if(!answersOwner.value)await answers.load()
    if(answers.missing.value.length){notify('独立窗口还有未作答题，请补充后提交。','info');return}
    if (!await notes.save() || !await savePosition(true)) return
    if (!data.value.course.exercise_total) {
      data.value = await studyApi.completeCourseReading(data.value.study.id)
      notify('本次阅读学习已完成。');interactionFeedback('complete')
    } else if (await answers.write('submit')) {data.value = await studyApi.courseStudy(data.value.study.id);interactionFeedback('complete')}
  } catch (cause) {reportError(cause)}
  finally {await syncToolContext(false);await releaseTools(peers.requestId);submitting.value = false}
}
async function syncFeedback() {
  if (!await flushCurrent()) return
  try {data.value = await studyApi.courseStudy(data.value!.study.id); await Promise.all([answers.load(), notes.load()]); await syncToolContext(); notify('反馈已同步。')}
  catch (cause) {reportError(cause)}
}
async function retrySaving() {
  if (answers.saveFailed.value || answers.pending.value) await answers.retry()
  if (notes.saveFailed.value || notes.pending.value) await notes.retry()
  if (progressFailed.value && data.value) {
    try {
      const fresh = await studyApi.courseStudy(data.value.study.id)
      data.value.study.progress_version = fresh.study.progress_version
      await savePosition()
    } catch (cause) {reportError(cause)}
  }
  if (!(answers.failed.value || notes.failed.value || answers.saveFailed.value || notes.saveFailed.value || progressFailed.value ||
        answers.pending.value || notes.pending.value || answers.recovery.value || notes.recovery.value || answers.dirty.value || notes.dirty.value)) {
    notify('保存已恢复，答案与笔记已同步到工作区。')
  }
}
async function syncToolContext(prepare=true) {
 if(!isTauri()||!context.value)return
 const windows=await listToolWindows();detached.value=windows.map(w=>w.tool)
 if(!windows.length)return
 const held=prepare?await prepareTools('hold'):null
 try {
  if(held&&!held.ok){notify('独立窗口仍保留上一课程，请先保存或恢复该窗口内容。','info');return}
  await invoke('set_tool_context',{context:context.value})
 }catch(cause){reportError(cause)}finally{if(held)await releaseTools(held.requestId)}
}
async function detachTool(tool:ToolTab) {
 if(!isTauri()){notify('独立工具窗口需要桌面版。','info');return}
 if(!context.value){notify('本课程尚未归属计划，请先通过 Agent 归入计划。','info');return}
 if(openingWindow.value)return
 if(detached.value.includes(tool)){await invoke('open_tool_window',{tool,context:context.value});return}
 if(!await flushCurrent())return
 openingWindow.value=true
 try {const loaded=await openToolWindow(tool,context.value);detached.value=(await listToolWindows()).map(w=>w.tool);if(!loaded)notify('工具内容尚未就绪，请在独立窗口重试加载，或放回侧栏。未创建新的学习轮次。','info')}
 catch(cause){reportError(cause)}finally{openingWindow.value=false}
}
async function putBackTool(tool:ToolTab) {
 await emitTo('tool-'+tool,'studyflow-tool-put-back',{})
}
function setDockWidth(width:number){dock.value={...dock.value,width,panes:width<560?dock.value.panes.slice(0,1):dock.value.panes}}
function splitTool(tool:ToolTab) {
 const available=dockMaxWidth.value
 if(available<560){notify('当前宽度不足以容纳两个工具窗格，可先展开工具区域。','info');return}
 if(dock.value.panes.includes(tool)){
  const other=dock.value.open.find(t=>t!==tool)||(tool==='notes'?'exercises':'notes')
  const base=activateTool({...dock.value,width:Math.max(560,dock.value.width)},other)
  dock.value=splitTools(base,tool,available)
 }else dock.value=splitTools({...dock.value,width:Math.max(560,dock.value.width)},tool,available)
}
function captureSelection() {
 const selected=window.getSelection()
 if(!selected||selected.isCollapsed||!body.value?.contains(selected.anchorNode)||!body.value.contains(selected.focusNode)){selection.value=null;return}
 const text=selected.toString().trim();if(!text||text.length>20000){selection.value=null;return}
 const anchor=selected.anchorNode instanceof Element?selected.anchorNode:selected.anchorNode?.parentElement
 const end=selected.focusNode instanceof Element?selected.focusNode:selected.focusNode?.parentElement
 const anchorId=anchor?.closest<HTMLElement>('[data-content-block]')?.dataset.contentBlock
 const endId=end?.closest<HTMLElement>('[data-content-block]')?.dataset.contentBlock
 const blockId=anchorId===endId?anchorId:undefined
 const r=selected.getRangeAt(0).getBoundingClientRect()
 selection.value={text,blockId,x:Math.max(10,Math.min(window.innerWidth-190,r.left)),y:Math.max(8,Math.min(window.innerHeight-48,r.bottom+8))}
}
async function markNote() {
 if(!selection.value||!data.value||!lesson.value||!context.value)return
 const block={id:makeRequestKey('excerpt').slice(0,64),text:'',quote:selection.value.text,source_block_id:selection.value.blockId||null,course_id:data.value.course.id,
  lesson_id:lesson.value.id,source_study_id:data.value.study.id,course_title:data.value.course.title,lesson_title:lesson.value.title}
 if(!notesOwner.value){if(!await addDetachedNote(context.value.planId,block)){notify('笔记窗口暂时不能接收摘录，选文仍保留，请处理该窗口后重试。','info');return}}
 else {if(notes.failed.value||notes.loading.value||notes.recovery.value||notes.pending.value||notes.cacheUnreadable.value){notify('请先恢复笔记的保存状态，再添加摘录。','info');return}notes.add(block);sidebarOpen.value=true;tab.value='notes'}
 selection.value=null;window.getSelection()?.removeAllRanges();notify('摘录已记入计划笔记，可以补充自己的理解。')
}
const toolListeners:(()=>void)[]=[]
const dockingTools=new Set<ToolTab>()
let disposed=false
async function listenTools(){
 if(!isTauri())return
 const register=async<T>(name:string,fn:(p:T)=>void|Promise<void>)=>{const off=await listen<T>(name,e=>{void fn(e.payload)});if(disposed)off();else toolListeners.push(off)}
 await register<{lessonId:string;blockId:string;studyId:string}>('studyflow-focus-section',async p=>{
  if(p.studyId!==data.value?.study.id)return
  const target=data.value.lessons.findIndex(l=>l.id===p.lessonId)
  if(target>=0&&data.value.lessons[target].content_blocks?.some(b=>b.id===p.blockId))await jumpToBlock(target,p.blockId)
 })
 await register<{tool:ToolTab}>(toolsEvent.docking,p=>{dockingTools.add(p.tool)})
 await register<{tool:ToolTab}>(toolsEvent.closed,async p=>{
  detached.value=detached.value.filter(t=>t!==p.tool)
  if(dockingTools.delete(p.tool))dock.value=activateTool(dock.value,p.tool)
 })
 await register<{tool:ToolTab;studyId?:string;planId?:string}>(toolsEvent.saved,async p=>{
  if(p.tool==='exercises'&&p.studyId===data.value?.study.id&&!answersOwner.value&&!answers.dirty.value&&!answers.pending.value&&!answers.recovery.value)await answers.load()
  if(p.tool==='notes'&&p.planId===data.value?.course.plan_line_id&&!notesOwner.value)await notes.load()
 })
}
async function startNewVersion() {
  if (!await flushCurrent()) return
  newVersionConfirm.value = false
  await load(true)
}
watch(()=>[props.lessonId,props.initialView],async()=>{
  if(!data.value || loading.value) return
  if(['answers','exercises'].includes(props.initialView||''))dock.value=activateTool(dock.value,'exercises')
  let target=props.lessonId ? data.value.lessons.findIndex(l=>l.id===props.lessonId) : -1
  if(target<0 && props.initialView==='answers') {
    tab.value = 'exercises'; sidebarOpen.value = true
    await syncFeedback()
    const row=answers.rows.value.find(r=>r.action==='REVISION'||r.action==='RETEST') || answers.missing.value[0]
    if(row) target=data.value.lessons.findIndex(l=>l.id===row.lessonId)
  }
  if(target>=0 && target!==index.value) await selectLesson(target)
})
watch(() => [sequenceTheme.value,dockMaxWidth.value, dock.value.width, dock.value.full, sidebarOpen.value, loading.value, data.value?.study.source_changed, answers.recovery.value, notes.recovery.value,
  answers.failed.value, answers.saveFailed.value, notes.saveFailed.value, progressFailed.value,
  !!answers.pending.value && !answers.busy.value, !!notes.pending.value && !notes.busy.value],
  async () => {await nextTick(); fitStudyLayout()})
onUpdated(()=>{
 if(pendingReadingScroll.value!==null)applyPendingReadingScroll(pendingReadingScroll.value)
})
watch(()=>[sidebarOpen.value,dock.value.full,shellPanel?.geometry.value.compact],async()=>{
 await nextTick()
 if(!restoringReadingScroll.value) await restoreReadingScrollAfterLayout(readingScrollTop.value)
})
let layoutObserver:ResizeObserver|undefined
onMounted(async()=>{window.addEventListener('resize', fitStudyLayout); await listenTools(); await load();if(studyLayout.value){layoutObserver=new ResizeObserver(fitStudyLayout);layoutObserver.observe(studyLayout.value)}})
onBeforeUnmount(()=>{shellPanel?.release(panelOwner);layoutObserver?.disconnect();disposed=true;toolListeners.forEach(off=>off());clearTimeout(timer);if(readingRestoreTimer)clearTimeout(readingRestoreTimer);window.removeEventListener('resize', fitStudyLayout)})
</script>

<template>
  <Teleport to="body"><button v-if="selection" class="selection-note-action" :style="{left:selection.x+'px',top:selection.y+'px'}" @mousedown.prevent @click="markNote" @keydown.esc="selection=null">≡ 记入计划笔记</button></Teleport>
  <LeaveStudyDialog v-if="safeExit.dialog.value" :closing="safeExit.dialog.value.path === 'close-window'" :reason="safeExit.dialog.value.reason" :retrying="safeExit.dialog.value.retrying" @retry="safeExit.retry" @discard="safeExit.finish(true, true)" @cancel="safeExit.finish(false)" @export="exportUnsaved"/>
  <div v-if="loading" class="loading-state" role="status">正在恢复课程、笔记与反馈…</div>
  <div v-else-if="!data" class="error-state"><p>课程暂时无法打开，没有覆盖学习记录。</p><button class="secondary-button" @click="load()">重新打开</button></div>
  <div v-else :class="['study-workspace', {'layout-overflow': layoutOverflow}]">
    <Teleport v-if="shellPanel?.navigationVisible?.value" defer to="#course-sidebar-content"><CourseOutline :plan-title="data.course.plan_line || '我的计划'" :course-title="data.course.title" :position="planPosition.current" :total="planPosition.total" :lessons="data.lessons" :index="index" :rows="answers.rows.value" :headings="documentHeadings" :active-heading="activeHeading" :busy="blocked" :reading-percent="readingPercent" @select="selectLesson" @heading="jumpToHeading" @back="navigate(data.course.plan_line_id ? '/plan/'+data.course.plan_line_id : '/plans')"/></Teleport>
    <div class="sequence-reader-bar" v-if="sequenceTheme"><button class="sequence-exit" @click="navigate(data.course.plan_line_id ? '/plan/'+data.course.plan_line_id : '/plans')" aria-label="退出课程详情，返回课程目录"><span>←</span> 课程目录</button><span class="sequence-breadcrumb" :title="data.course.title">{{data.course.title}}</span><div class="sequence-reader-controls"><button class="sequence-sound" :aria-pressed="soundEnabled" :aria-label="soundEnabled?'关闭操作音效':'开启操作音效'" :title="soundEnabled?'关闭操作音效':'开启操作音效'" @click="toggleSound"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 8h3l4-4v12l-4-4H3z"/><path v-if="soundEnabled" d="M13 7q3 3 0 6m2-9q6 6 0 12"/><path v-else d="m13 8 4 4m0-4-4 4"/></svg></button><button class="text-button" :disabled="blocked" @click="syncFeedback" aria-label="同步反馈">↻</button><button class="tools-toggle" :aria-expanded="sidebarOpen" :aria-label="sidebarOpen?'收起学习工具':'打开答题与笔记'" aria-controls="workspace-tool-panel" @click="toggleTools"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M12 4v12"/></svg><span>{{sidebarOpen?'收起工具':'答题与笔记'}}</span></button></div></div>
    <div v-if="!sequenceTheme" class="reader-toolbar"><button class="back-link" @click="navigate(data.course.plan_line_id ? '/plan/'+data.course.plan_line_id : '/plans')">← {{data.course.plan_line || '我的计划'}}</button>
    <header class="reader-heading">
      <div class="reader-heading-copy">
        <p class="reader-context">{{data.course.plan_line || '我的计划'}} <span>/</span> 当前学习课程</p>
        <h2>{{data.course.title}}</h2>
        <p class="reader-subtitle">第 {{planPosition.current}} 节 · {{data.course.subject || '课程阅读与练习'}}</p>
      </div>
      <section class="reader-progress-summary" aria-label="课程学习进度">
        <div class="reader-progress-position"><span>课程位置</span><strong>{{String(planPosition.current).padStart(2,'0')}} / {{String(planPosition.total).padStart(2,'0')}}</strong></div>
        <div class="reader-progress-track" role="progressbar" :aria-valuenow="courseProgressPercent" aria-valuemin="0" aria-valuemax="100"><span :style="{width:courseProgressPercent+'%'}"/></div>
        <div class="reader-progress-meta"><span>本课阅读 {{readingPercent}}%</span><span class="reader-progress-status">{{courseStatus}}</span></div>
        <button class="text-button" :disabled="blocked" @click="syncFeedback">同步反馈 ↻</button>
      </section>
    </header>
    </div>
    <div v-if="['PASSED','READ_COMPLETED'].includes(data.course.study_status||'')&&!data.study.source_changed" class="study-version-note"><span>本轮已通过。可以只回看，或明确开启一轮新的复习；旧答案保留。</span><button class="text-button" @click="newVersionConfirm=true">开启复习轮次</button><span v-if="newVersionConfirm"><button class="text-button" @click="async()=>{if(await flushCurrent()){newVersionConfirm=false;await load(false,true)}}">确认重新学习与作答</button><button class="text-button" @click="newVersionConfirm=false">取消</button></span></div>
    <div v-if="data.study.source_changed" class="study-version-note"><span>{{data.study.source_available ? '材料已更新，本次学习仍使用开始时的版本。' : '源文件暂时不可读，仍可使用本次学习的固定材料。'}}</span><button v-if="data.study.source_available && ['PASSED','READ_COMPLETED'].includes(data.course.study_status || '')" class="text-button" @click="newVersionConfirm=true">开始新版学习</button><span v-if="newVersionConfirm">旧答案和反馈将保留。<button class="text-button" @click="startNewVersion">确认开始</button><button class="text-button" @click="newVersionConfirm=false">取消</button></span></div>
    <StudyRecovery :answers="answers" :notebook="notes" :progress-failed="progressFailed" @retry="retrySaving" @notes="sidebarOpen=true;tab='notes'"/>
    <div v-if="answers.failed.value" class="error-state"><p>作答状态读取失败，没有覆盖已有答案。</p><button class="secondary-button" @click="answers.load">重新读取作答</button></div>
    <template v-else-if="lesson">
      <div v-if="!sequenceTheme" class="reader-navigation"><KnowledgePointPager :lessons="data.lessons" :index="index" :busy="blocked" :answer-states="answers.rows.value" @select="selectLesson"/><span class="reader-current-title" :class="{visible:readingScrollTop>90}">{{lesson.title}}</span><button ref="toolsToggle" class="tools-toggle" :aria-expanded="sidebarOpen" aria-controls="workspace-tool-panel" :aria-label="sidebarOpen?'收起学习工具':'打开答题与笔记'" @click="toggleTools"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="2.5" y="3.5" width="15" height="13" rx="2"/><path d="M12 4v12"/></svg><span>{{sidebarOpen?'收起工具':'答题与笔记'}}</span></button></div>
      <DisplaySlot slot="reading-shell" :fallback="'div'" :view-props="readingShellProps">
        <div ref="studyLayout" :style="{'--study-height': layoutHeight+'px'}" :class="layoutClass">
        <article :key="lesson.id" class="study-material" aria-label="知识点正文"><div ref="body" data-reading-scroll-container class="study-material-body" tabindex="0" @scroll.passive="onScroll();selection=null" @mouseup="captureSelection" @keyup="captureSelection"><header class="study-unit-heading"><ThemeReadingArtwork v-if="!sequenceTheme"/><p class="eyebrow"><template v-if="sequenceTheme">第 {{planPosition.current}} / {{planPosition.total}} 课 · </template>知识点 {{String(index+1).padStart(2,'0')}} / {{data.lessons.length}}</p><h3>{{lesson.title.replace(/^\d+[｜|·.、\s]+/,'')}}</h3><p v-if="sequenceTheme && lesson.summary" class="sequence-lesson-summary">{{lesson.summary}}</p><span v-if="sequenceTheme" class="sequence-reading-status">{{courseStatus}} · 本课阅读 {{readingPercent}}%</span></header><TeachingContent v-if="lesson.content_blocks?.length" :blocks="lesson.content_blocks" :exercises="lesson.exercises" :notes="notes.blocks.value" :study-id="data.study.id" :lesson-id="lesson.id" :blocked="blocked" @practice="openPractice"/><div v-else class="markdown-body legacy-teaching-content" v-html="renderedLesson"/>
        <section v-if="sequenceTheme && lesson.exercises.length" class="sequence-practice-entry"><div><span class="sequence-practice-icon">✓</span><h4>知识点练习</h4><span>{{lesson.exercises.length}} 道练习</span></div><p>把理解写下来，答案会随本课自动保存。也可以暂时跳过，最后统一提交。</p><button class="secondary-button" :disabled="blocked" @click="openPractice(lesson.exercises[0].id)">打开本节练习 <span>→</span></button></section>
        <nav v-if="sequenceTheme" class="sequence-page-turn" aria-label="上下知识点"><button :disabled="index===0||blocked" @click="selectLesson(index-1)"><small>‹ 上一节</small><span>{{index>0?data.lessons[index-1].title:'已是第一节'}}</span></button><span class="sequence-page-number"><b>{{String(index+1).padStart(2,'0')}}</b> / {{String(data.lessons.length).padStart(2,'0')}}</span><button :disabled="index===data.lessons.length-1||blocked" @click="selectLesson(index+1)"><small>下一节 ›</small><span>{{index<data.lessons.length-1?data.lessons[index+1].title:'已是最后一节'}}</span></button></nav>
        </div></article>
        <Teleport defer to="#workspace-tool-panel">
        <CourseToolsSidebar v-if="!answers.loading.value" :dock="dock" :lessons="data.lessons" :index="index" :rows="answers.rows.value" :blocked="blocked" :notebook="notes" :plan-title="data.course.plan_line||undefined" :course-id="data.course.id" :detached="detached" :max-width="dockMaxWidth" :effective-width="shellPanel?.geometry.value.width||dock.width" :course-title="data.course.title" :compact="shellPanel?.geometry.value.compact" :sequence="sequenceTheme" :course-position="planPosition.current" :course-total="planPosition.total" :course-progress="courseProgressPercent" :save-label="saveLabel" :save-failed="answers.saveFailed.value||notes.saveFailed.value||progressFailed" @activate="(t,p)=>dock=activateTool(dock,t,p)" @close="t=>dock=closeTool(dock,t)" @select="selectLesson" @section="jumpToBlock" @collapse="sidebarOpen=false" @width="setDockWidth" @full="dock={...dock,full:!dock.full}" @split="splitTool" @unsplit="dock={...dock,panes:dock.panes.slice(0,1)}" @ratio="r=>dock={...dock,split:r}" @detach="detachTool" @dock="putBackTool" @reorder="(from,to)=>dock=reorderTools(dock,from,to)"><template v-if="dock.full||shellPanel?.geometry.value.compact" #actions><StudyActions :blocked="blocked||progressSaving||answers.loading.value" :read="lesson.progress.status==='COMPLETED'" :last="index===data.lessons.length-1" :can-submit="!!answers.editable.value.length||!data.course.exercise_total&&!data.course.learning_submitted" :submitting="submitting" :feedback-needed="!!feedbackNeeded" :has-exercises="!!data.course.exercise_total" @read="confirmRead" @next="continueLearning" @submit="submitCourse" @done="navigate('/today')"/></template><template v-if="sequenceTheme||dock.full||shellPanel?.geometry.value.compact" #recovery><StudyRecovery :answers="answers" :notebook="notes" :progress-failed="progressFailed" @retry="retrySaving" @notes="sidebarOpen=true;tab='notes'"/></template></CourseToolsSidebar>
        <div v-else class="loading-state" role="status">正在恢复学习工具…</div>
        </Teleport>
        </div>
      </DisplaySlot>
      <p v-if="answers.cacheUnavailable?.value" class="recovery-note" role="status">本机恢复缓存不可用，输入仍在当前窗口；成功写入工作区后才算保存。失败时请导出再退出。</p>
      <footer ref="actionBar" class="study-action-bar"><div class="study-save-status" aria-live="polite"><span :class="['save-dot',{'is-error':answers.saveFailed.value || notes.saveFailed.value || progressFailed,'is-saving':!!answers.busy.value || notes.busy.value || progressSaving}]"/><div><strong>{{saveLabel}}</strong><span>{{answers.editable.value.length ? '待作答 '+answers.editable.value.length+' 道 · 未答 '+answers.missing.value.length+' 道' : feedbackNeeded ? '按反馈完成修正或复测' : data.course.learning_submitted ? '本次学习已提交，阅读与通过分别记录' : '确认学习不代表长期掌握'}}</span></div></div><StudyActions :blocked="blocked||progressSaving||answers.loading.value" :read="lesson.progress.status==='COMPLETED'" :last="index===data.lessons.length-1" :can-submit="!!answers.editable.value.length||!data.course.exercise_total&&!data.course.learning_submitted" :submitting="submitting" :feedback-needed="!!feedbackNeeded" :has-exercises="!!data.course.exercise_total" @read="confirmRead" @next="continueLearning" @submit="submitCourse" @done="navigate('/today')"/></footer>
    </template>
  </div>
</template>
