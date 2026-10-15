<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {navigate,notify,reportError} from '../../../shared/ui'
import {interactionFeedback} from '../../../shared/ui/interaction'
import {useEnglishTraining} from './useEnglishTraining'
import TokenEditor from './TokenEditor.vue'
import {englishShortcut} from './shortcuts'
import {keyboardEnabled,keyboardVolume,keyboardAudioName,saveKeyboardPreferences,importKeyboardAudio,resetKeyboardAudio} from '../../../shared/audio/keyboard'
import SentenceBreakdown from './SentenceBreakdown.vue'
import {useWordMetadata} from './useWordMetadata'
import PlanNotebook from '../../notes/components/PlanNotebook.vue'
import {usePlanNotebook} from '../../notes/composables/usePlanNotebook'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import LeaveStudyDialog from '../../courses/components/LeaveStudyDialog.vue'
import {playDictionary,stopSpeech,speechAccent,speechAuto,speechMuted,speechVolume,saveSpeechPreferences} from '../../../shared/audio/dictionary'
import {isTauri} from '../../../shared/api'
import {useEnglishNotesWindow} from './useEnglishNotesWindow'
import type {ToolContext} from '../../courses/dock/toolWindows'
import type {DictionaryInfo} from '../../../shared/api/contracts/english'
const props=defineProps<{id:string}>()
const training=useEnglishTraining(props.id)
const {data,item,tokens,position,busy,failed,reference,hintMode,phase,recovery}=training
const notesDetached=ref(false)
const notes=usePlanNotebook(computed(()=>data.value?.course.plan_line_id||undefined),computed(()=>!notesDetached.value))
const noteContext=computed<ToolContext|null>(()=>data.value?.course.plan_line_id?{courseId:data.value.course.id,studyId:props.id,planId:data.value.course.plan_line_id,planTitle:data.value.course.plan_line||data.value.course.title,lessonId:item.value?.lesson_id}:null)
const noteWindow=useEnglishNotesWindow(noteContext,notesDetached,notes)
const stageLabels:Record<string,string>={vocabulary:'必要词汇',chunk:'短语组合',pattern:'句型应用',variation:'句型变式',transfer:'无提示迁移'}
const drawer=ref<'notes'|null>(null),directoryOpen=ref(false),lessonOpen=ref(false)
const directoryDialog=ref<HTMLDialogElement|null>(null)
watch(directoryOpen,async open=>{await nextTick();if(open&&directoryDialog.value&&!directoryDialog.value.open)directoryDialog.value.showModal();else directoryDialog.value?.close()})
const settings=ref(false),loading=ref(true),speechNotice=ref(''),dictionary=ref<DictionaryInfo|null>(null),analysisOpen=ref(false)
const wordMetadata=useWordMetadata(computed(()=>data.value?.workspace_key||''),computed(()=>props.id),computed(()=>item.value?.exercise_id||''),reference,analysisOpen)
let audioGeneration=0
const keyboardFile=ref<HTMLInputElement|null>(null)
const audioImportNotice=ref('')
const editor=ref<InstanceType<typeof TokenEditor>|null>(null),actions=ref<HTMLElement|null>(null)
const locked=computed(()=>['WAITING_REVIEW','PASSED','RECHECKED','REVIEWED'].includes(item.value?.status||''))
const completed=computed(()=>data.value?.items.filter(i=>i.matched||['PASSED','RECHECKED','REVIEWED'].includes(i.status)).length||0)
const pendingReviews=computed(()=>data.value?.items.filter(i=>i.status==='WAITING_REVIEW').length||0)
const exit=useSafeStudyExit({busy:()=>busy.value||notes.busy.value,hasProblem:()=>!!(failed.value||training.pending.value||recovery.value||notes.saveFailed.value||notes.pending.value||notes.recovery.value),flush:async()=>await training.save()&&await notes.save(),retry:async()=>{await training.retryPending();await notes.retry()},suspend:()=>{training.suspend();notes.suspendAutosave();stopSpeech();if(exit.dialog.value?.path==='close-window')window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}})
async function check(){
 const checkedId=item.value?.exercise_id
 const result=await training.check()
 if(!result||item.value?.exercise_id!==checkedId)return
 if(speechAuto.value)void play()
 if(result.matched){analysisOpen.value=false;training.hideHint();interactionFeedback('complete');await nextTick();if(drawer.value!=='notes')actions.value?.querySelector<HTMLButtonElement>('.primary-button')?.focus()}
 else{await nextTick();editor.value?.focusWord(result.differences[0]?.index||0);if((item.value?.error_count||0)>=2)await openAnalysis()}
}
async function move(index:number){
 stopSpeech();audioGeneration++;dictionary.value=null;speechNotice.value='';analysisOpen.value=false;directoryOpen.value=false;lessonOpen.value=false
 if(await training.move(index)){interactionFeedback('move');await nextTick();editor.value?.focusWord(0);if(speechAuto.value)void play()}
}
async function finish(){await training.submit();if(training.navigationNotice.value){analysisOpen.value=false;notify(training.navigationNotice.value,'info');await nextTick();editor.value?.focusWord(0);if(speechAuto.value)void play()}}
async function skip(){if(await training.save(true))await move(position.value+1)}
async function play(wordIndex?:number){
 if(!item.value||speechMuted.value||speechVolume.value<=0)return
 const token=++audioGeneration
 try{const value=await playDictionary(props.id,item.value.exercise_id,wordIndex);if(token!==audioGeneration||!value)return;dictionary.value=value;speechNotice.value=value.playback_provider?value.notice||'':''}
 catch(e){if(token===audioGeneration)speechNotice.value=(e as Error).message}
}
async function openAnalysis(){
 if(phase.value==='answer'||locked.value)return
 await training.reveal('answer')
 if(reference.value)analysisOpen.value=true
}
async function toggleAnalysis(){if(analysisOpen.value){analysisOpen.value=false;training.hideHint()}else await openAnalysis()}
function keydown(event:KeyboardEvent) {
 if(event.defaultPrevented||settings.value||directoryOpen.value||lessonOpen.value||((event.target as HTMLElement|null)?.closest('.english-drawer')))return
 const target=event.target as HTMLElement|null
 if(!target?.closest('.english-token-row,.english-main-actions,.english-answer,.english-training-footer,.english-breakdown'))return
 const action=englishShortcut(event);if(!action)return
 event.preventDefault()
 if(action==='sentence-audio'){void play();return}
 if(action==='word-audio'){void play(editor.value?.focusedIndex??0);return}
 if(training.actionRunning.value)return
 if(action==='previous')void move(position.value-1)
 else if(action==='skip'){if(phase.value==='answer'||locked.value)void move(position.value+1);else void skip()}
 else if(action==='explanation'&&!locked.value)void toggleAnalysis()
}
async function importKeySound(event:Event) {
 const input=event.target as HTMLInputElement,file=input.files?.[0]
 if (!file) return
 try {await importKeyboardAudio(file);audioImportNotice.value='已使用本地键音，不会上传或访问网络。'} catch (error) {audioImportNotice.value=(error as Error).message} finally {input.value=''}
}
watch([keyboardEnabled,keyboardVolume],saveKeyboardPreferences)
watch([speechAccent,speechVolume,speechMuted,speechAuto],()=>{stopSpeech();saveSpeechPreferences()})
onMounted(async()=>{try{await training.load()}catch(e){reportError(e);failed.value=(e as Error).message}finally{loading.value=false};await nextTick();editor.value?.focusWord(0);if(item.value&&speechAuto.value)void play()})
onBeforeUnmount(()=>{audioGeneration++;stopSpeech()})
</script>
<template>
 <LeaveStudyDialog v-if="exit.dialog.value" :closing="exit.dialog.value.path==='close-window'" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="training.exportInput"/>
 <div v-if="loading" class="loading-state">正在恢复英语训练…</div>
 <section v-else-if="data&&item" class="english-learning" aria-label="英语专注训练" @keydown="keydown">
  <header class="english-training-header"><button class="text-button" @click="navigate('/course/'+data.course.id)">← 返回课程</button><div class="english-header-title"><strong>{{data.course.title}}</strong><span>{{position+1}} / {{data.items.length}}<template v-if="item.progression"> · {{stageLabels[item.progression.stage]}}</template> · 已检查通过 {{completed}}<template v-if="pendingReviews"> · 待审核 {{pendingReviews}}</template></span></div><div class="english-header-tools"><button :aria-expanded="settings" @click="settings=!settings">训练设置</button><button :aria-expanded="drawer==='notes'" @click="drawer=drawer==='notes'?null:'notes'">笔记</button></div></header>
  <div v-if="settings" class="english-speech-settings"><label>口音请求 <select v-model="speechAccent"><option value="en-US">美式</option><option value="en-GB">英式</option></select></label><label>语音音量 {{speechVolume}}% <input v-model.number="speechVolume" type="range" min="0" max="100"/></label><label><input v-model="speechMuted" type="checkbox"/>静音</label><label><input v-model="speechAuto" type="checkbox"/>检查通过后朗读</label><label><input v-model="keyboardEnabled" type="checkbox"/>输入键音</label><label>键音音量 {{keyboardVolume}}% <input v-model.number="keyboardVolume" type="range" min="0" max="100"/></label><div class="english-keyboard-asset"><span>{{keyboardAudioName}}</span><button @click="keyboardFile?.click()">导入键音</button><button @click="resetKeyboardAudio">恢复内置</button><input ref="keyboardFile" class="sr-only" type="file" accept=".mp3,.wav,.ogg" @change="importKeySound"/></div><p v-if="audioImportNotice" role="status">{{audioImportNotice}}</p><small>Ctrl+'：当前词提示 · Ctrl+;：本句提示 · Ctrl+.：暂跳 · Ctrl+,：上一项。提示就在输入位置显示，不切换页面。网络发音失败不阻塞训练。</small></div>
  <p v-if="data.course.source_changed" class="english-assistance">课程已有新修订，本轮保留原材料与答案。{{data.completed?'本轮训练已提交，可返回课程概览学习修订后的课程。':'请先完成并提交本轮训练，再从课程概览学习修订后的课程。'}}</p>
  <div v-if="recovery" class="english-recovery" role="status">发现此轮的本机未保存输入。<button @click="training.restore">恢复输入</button><button @click="training.discardRecovery">保留工作区版本</button><button @click="training.exportInput">导出</button></div>
  <div v-if="failed" class="english-error" role="alert">{{failed}}<button :disabled="training.actionRunning.value" @click="training.retryPending">重试原请求</button><button @click="training.exportInput">导出输入</button><button @click="navigate('/course/'+data.course.id)">离开训练…</button></div>
  <div class="english-work-surface" :class="{'has-drawer':drawer}">
   <main class="english-stage">
    <template v-if="phase!=='result'">
     <SentenceBreakdown v-if="analysisOpen&&reference&&phase!=='answer'" :reference="reference" :metadata="wordMetadata.words.value" @word="play"/>
     <p v-if="analysisOpen&&wordMetadata.notice.value" class="english-metadata-status" role="status">{{wordMetadata.notice.value}} <button v-if="['deferred','unavailable'].includes(wordMetadata.status.value)" class="text-button" @click="wordMetadata.refresh">重试辅助信息</button></p>
     <div class="english-question"><h1>{{item.prompt}}</h1></div>
     <p v-if="item.status==='WAITING_REVIEW'" class="english-assistance" role="status">此项已有待审核记录，答案保持不变。无需重复作答，可继续训练或完成本课；待审核不计为检查通过。</p>
     <TokenEditor v-if="phase!=='answer'" ref="editor" v-model="tokens" :minimum="item.min_token_count||item.token_count" :maximum="item.max_token_count||item.token_count" :disabled="training.inputLocked.value||locked" :differences="phase==='correction'?item.differences:[]" @edited="training.edited" @check="check"/>
     <div v-else class="english-answer"><p class="english-target">{{item.answer_text}}</p></div>
     <div ref="actions" class="english-main-actions">
      <button v-if="phase!=='answer'&&!locked" class="primary-button" :disabled="training.actionRunning.value" @click="check">检查答案 <kbd>Enter</kbd></button>
      <button v-else-if="position<data.items.length-1" class="primary-button" :disabled="training.actionRunning.value" @click="move(position+1)">下一项 →</button>
      <button v-else class="primary-button" :disabled="training.actionRunning.value" @click="finish">完成本课</button>
     </div>
     <p v-if="speechNotice" class="english-assistance" role="status">{{speechNotice}}</p>
    </template>
    <div v-else class="english-result"><span class="english-kicker">本轮已完成</span><h1>这门课的训练已确认</h1><p>{{completed}} / {{data.items.length}} 项已检查通过</p><p v-if="pendingReviews" class="english-assistance" role="status">另有 {{pendingReviews}} 项旧记录已提交、仍待审核。本轮训练已确认，原审核状态未改变，不代表全部通过。</p><button class="primary-button" @click="navigate('/course/'+data.course.id)">返回课程</button><button class="secondary-button" @click="navigate('/mistakes')">查看错误与复习</button></div>
   </main>
   <aside v-if="drawer==='notes'" class="english-drawer" aria-label="计划笔记"><header><h2>计划笔记</h2><button @click="drawer=null" aria-label="关闭侧栏">×</button></header><div class="english-note-tools"><button v-if="isTauri()&&!notesDetached" class="text-button" :disabled="noteWindow.opening.value" @click="noteWindow.detach">弹出笔记窗口</button><button v-if="notesDetached" class="text-button" @click="noteWindow.putBack">放回侧栏</button><button v-if="notesDetached" class="text-button" @click="noteWindow.detach">聚焦笔记窗口</button></div><p v-if="noteWindow.notice.value" role="status">{{noteWindow.notice.value}} <button class="text-button" @click="noteWindow.refresh(true)">重试连接</button></p><p v-if="notesDetached" class="muted">笔记在独立窗口编辑，这里只读显示。</p><PlanNotebook :notebook="notes" :plan-title="data.course.plan_line||data.course.title" :course-id="data.course.id" :lesson-id="item.lesson_id" :blocked="notesDetached"/></aside>
  </div>
  <footer class="english-training-footer">
   <button @click="directoryOpen=!directoryOpen" aria-label="打开课程目录">☰</button>
   <button :disabled="position===0||training.actionRunning.value" @click="move(position-1)" aria-label="上一项">←</button>
   <div class="english-shortcuts" aria-label="训练快捷键">
    <button @click="play()"><kbd>Ctrl</kbd><kbd>'</kbd>整句朗读</button>
    <button @click="play(editor?.focusedIndex??0)"><kbd>Ctrl</kbd><kbd>Shift</kbd><kbd>'</kbd>单词朗读</button>
    <span><kbd>Space</kbd>下一词 <kbd>Enter</kbd>检查</span>
    <button :disabled="phase==='answer'||locked" @click="toggleAnalysis"><kbd>Ctrl</kbd><kbd>;</kbd>解析</button>
    <button :disabled="position>=data.items.length-1||training.actionRunning.value" @click="phase==='answer'||locked?move(position+1):skip()"><kbd>Ctrl</kbd><kbd>.</kbd>{{phase==='answer'||locked?'下一项':'暂跳'}}</button>
   </div>
   <span class="english-save-status" role="status">{{training.saving.value?'保存中':training.dirty.value?'待保存':failed?'保存未确认':'已保存'}}</span>
  </footer>
  <dialog v-if="directoryOpen" ref="directoryDialog" class="english-directory-overlay" aria-labelledby="english-directory-title" @cancel.prevent="directoryOpen=false"><section class="english-directory-dialog"><header><h2 id="english-directory-title">课程目录</h2><button autofocus @click="directoryOpen=false" aria-label="关闭课程目录">×</button></header><ol class="english-directory"><li v-for="(entry,i) in data.items" :key="entry.exercise_id"><button :aria-current="position===i?'step':undefined" @click="move(i)"><span>{{i+1}}</span><strong>{{entry.title}}</strong><i>{{entry.matched?'✓':entry.skipped?'暂跳':''}}</i></button></li></ol></section></dialog>
 </section>
 <div v-else class="error-state"><h2>英语课程暂未读取</h2><button @click="navigate('/plans')">返回计划</button></div>
</template>
