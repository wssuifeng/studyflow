<script setup lang="ts">
import {emitTo} from '@tauri-apps/api/event'
import {computed,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {studyApi} from '../../../shared/api'
import type {CourseStudyDetailData,NotebookBlock} from '../../../shared/api/contracts'
import {reportError,windowStorageKey} from '../../../shared/ui'
import {useCourseAnswers} from '../../learning/composables/useCourseAnswers'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import {usePlanNotebook} from '../../notes/composables/usePlanNotebook'
import CourseToolContent from './CourseToolContent.vue'
import LeaveStudyDialog from './LeaveStudyDialog.vue'
import type {ToolTab} from '../dock/state'
import type {ToolContext} from '../dock/toolWindows'
const props=defineProps<{tool:ToolTab;context:ToolContext;paused:boolean}>()
let alive=true
const emit=defineEmits<{ready:[];failed:[]}>()
const data=ref<CourseStudyDetailData|null>(null),loading=ref(true),failed=ref(false),index=ref(0)
const answerOwner=computed(()=>props.tool==='exercises'),noteOwner=computed(()=>props.tool==='notes')
const answers=useCourseAnswers(data,answerOwner)
const notebook=usePlanNotebook(computed(()=>props.tool==='notes'?props.context.planId:undefined),noteOwner)
const blocked=computed(()=>props.paused||!!answers.recovery.value||!!answers.pending.value&&!answers.busy.value)
async function load(){loading.value=true;failed.value=false;try{
 const detail=await studyApi.courseStudy(props.context.studyId)
 if(detail.course.id!==props.context.courseId || detail.course.plan_line_id!==props.context.planId)throw Error('工具窗口与冻结学习轮次不一致，未加载其他课程。')
 if(!alive)return
 data.value=detail;if(props.tool==='notes'&&!await notebook.load())throw Error('计划笔记未能读取，请重试加载。');if(props.tool!=='notes'&&!await answers.load())throw Error('本轮作答状态未能读取，请重试加载。')
 if(!alive)return
 const stored=localStorage.getItem(windowStorageKey('tool-index:'+props.tool+':'+props.context.studyId))||props.context.lessonId
 const found=detail.lessons.findIndex(l=>l.id===stored);index.value=found<0?0:found
 emit('ready')
}catch(cause){failed.value=true;emit('failed');reportError(cause)}finally{loading.value=false}}
watch(index,()=>{const id=data.value?.lessons[index.value]?.id;if(id)localStorage.setItem(windowStorageKey('tool-index:'+props.tool+':'+props.context.studyId),id)})
async function flush(){if(loading.value||failed.value)return false;return props.tool==='notes'?notebook.save():props.tool==='exercises'?answers.write('save'):true}
async function retry(){if(props.tool==='notes')await notebook.retry();else if(props.tool==='exercises')await answers.retry()}
function hasProblem(){return props.tool==='notes'?!!(notebook.failed.value||notebook.saveFailed.value||notebook.pending.value||notebook.recovery.value):props.tool==='exercises'?!!(answers.failed.value||answers.saveFailed.value||answers.pending.value||answers.recovery.value):false}
function suspend(){answers.suspendAutosave();notebook.suspendAutosave()}
function exportUnsaved(){if(props.tool==='notes')notebook.exportRecovery();else{
 const url=URL.createObjectURL(new Blob([JSON.stringify({study_session_id:props.context.studyId,answers:answers.rows.value.map(r=>({exercise_id:r.exercise_id,answer_text:r.answer})),recovery:answers.recovery.value,pending:answers.pending.value},null,2)],{type:'application/json;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='StudyFlow-未保存作答.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}}
function addNote(block:NotebookBlock){if(props.tool!=='notes'||props.paused||notebook.loading.value||notebook.failed.value||notebook.recovery.value||notebook.pending.value)return false;return notebook.blocks.value.some(b=>b.id===block.id)||notebook.add(block)}
const exit=useSafeStudyExit({busy:()=>!!answers.busy.value||notebook.busy.value,hasProblem,flush,retry,suspend})
async function reload(){if(props.tool==='notes'){if(!notebook.dirty.value&&!notebook.pending.value&&!notebook.recovery.value)await notebook.load()}else if(!answers.dirty.value&&!answers.pending.value&&!answers.recovery.value)await answers.load()}
async function select(next:number){if(next>=0&&next<(data.value?.lessons.length||0))index.value=next}
defineExpose({flush,retry,suspend,exportUnsaved,addNote,reload,hasProblem,focusLesson:(id:string)=>{const i=data.value?.lessons.findIndex(l=>l.id===id)??-1;if(i>=0)index.value=i}})
onBeforeUnmount(()=>{alive=false})
onMounted(load)
</script>
<template>
 <LeaveStudyDialog v-if="exit.dialog.value" :closing="true" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="exportUnsaved"/>
 <div v-if="loading" class="loading-state" role="status">正在打开共享的冻结课程…</div>
 <div v-else-if="failed" class="error-state"><p>工具内容未能加载；没有创建新的学习轮次。</p><button class="secondary-button" @click="load">重试加载</button></div>
 <template v-else-if="data">
  <header class="tool-course-context"><span>{{context.planTitle||data.course.plan_line}}</span><h2>{{data.course.title}}</h2><label class="tool-knowledge-select">{{tool==='notes'?'关联知识点':'浏览知识点'}}<select :value="index" :disabled="paused" @change="select(Number(($event.target as HTMLSelectElement).value))"><option v-for="(lesson,i) in data.lessons" :key="lesson.id" :value="i">{{i+1}} · {{lesson.title}}</option></select></label><p v-if="tool==='notes'">全计划连续笔记 · 课程关联不拆分笔记</p></header>
  <div v-if="answers.recovery.value && tool==='exercises'" class="notebook-alert"><p>本窗口有未保存的作答，需要你确认。</p><button class="text-button" @click="answers.restoreCache">恢复</button><button class="text-button" @click="exportUnsaved">导出</button><button class="text-button" @click="answers.discardCache">使用工作区版本</button></div>
  <div class="native-tool-content"><CourseToolContent :tool="tool" :lessons="data.lessons" :index="index" :rows="answers.rows.value" :blocked="blocked" :notebook="notebook" :plan-title="context.planTitle||data.course.plan_line||undefined" :course-id="context.courseId" @select="select" @section="(i,b)=>emitTo('main','studyflow-focus-section',{lessonId:data!.lessons[i].id,blockId:b,studyId:context.studyId})"/></div>
  <footer v-if="tool==='exercises'" class="native-tool-footer"><span aria-live="polite">{{answers.busy.value?'正在保存':answers.saveFailed.value?'保存失败，输入已保留':answers.dirty.value?'等待自动保存':answers.savedAt.value?'已保存 '+answers.savedAt.value:'答案自动保存 · 整课提交在主窗口完成'}}</span><button v-if="answers.saveFailed.value||answers.pending.value" class="text-button" @click="retry">重试保存</button></footer>
 </template>
</template>
