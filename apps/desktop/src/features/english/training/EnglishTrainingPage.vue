<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,ref,watch} from 'vue'
import {navigate,notify,reportError} from '../../../shared/ui'
import {interactionFeedback} from '../../../shared/ui/interaction'
import {useEnglishTraining} from './useEnglishTraining'
import TokenEditor from './TokenEditor.vue'
import AnswerReference from '../../learning/components/AnswerReference.vue'
import TeachingContent from '../../courses/components/TeachingContent.vue'
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
const {data,item,tokens,position,busy,failed,reference,phase,recovery}=training
const notesDetached=ref(false)
const notes=usePlanNotebook(computed(()=>data.value?.course.plan_line_id||undefined),computed(()=>!notesDetached.value))
const noteContext=computed<ToolContext|null>(()=>data.value?.course.plan_line_id?{courseId:data.value.course.id,studyId:props.id,planId:data.value.course.plan_line_id,planTitle:data.value.course.plan_line||data.value.course.title,lessonId:item.value?.lesson_id}:null)
const noteWindow=useEnglishNotesWindow(noteContext,notesDetached,notes)
const stageLabels:Record<string,string>={vocabulary:'必要词汇',chunk:'短语组合',pattern:'句型应用',variation:'句型变式',transfer:'无提示迁移'}
const currentGroup=computed(()=>data.value?.groups?.find(g=>g.lesson_id===item.value?.lesson_id))
const drawer=ref<'notes'|null>(null),directoryOpen=ref(false),lessonOpen=ref(false)
const directoryDialog=ref<HTMLDialogElement|null>(null)
watch(directoryOpen,async open=>{await nextTick();if(open&&directoryDialog.value&&!directoryDialog.value.open)directoryDialog.value.showModal();else directoryDialog.value?.close()})
const settings=ref(false),loading=ref(true),speechNotice=ref(''),dictionary=ref<DictionaryInfo|null>(null)
const editor=ref<InstanceType<typeof TokenEditor>|null>(null),actions=ref<HTMLElement|null>(null)
const locked=computed(()=>['WAITING_REVIEW','PASSED','RECHECKED','REVIEWED'].includes(item.value?.status||''))
const completed=computed(()=>data.value?.items.filter(i=>i.matched||['PASSED','RECHECKED','REVIEWED'].includes(i.status)).length||0)
const exit=useSafeStudyExit({busy:()=>busy.value||notes.busy.value,hasProblem:()=>!!(failed.value||training.pending.value||recovery.value||notes.saveFailed.value||notes.pending.value||notes.recovery.value),flush:async()=>await training.save()&&await notes.save(),retry:async()=>{await training.retryPending();await notes.retry()},suspend:()=>{training.suspend();notes.suspendAutosave();stopSpeech();if(exit.dialog.value?.path==='close-window')window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}})
async function check(){const result=await training.check();if(result?.matched){interactionFeedback('complete');await nextTick();if(drawer.value!=='notes')actions.value?.querySelector<HTMLButtonElement>('.primary-button')?.focus();if(speechAuto.value)void play()}else if(result){await nextTick();editor.value?.focusWord(result.differences[0]?.index||0)}}
async function move(index:number){stopSpeech();dictionary.value=null;speechNotice.value='';if(await training.move(index)){directoryOpen.value=false;lessonOpen.value=false;interactionFeedback('move');await nextTick();editor.value?.focusWord(0)}}
async function skip(){if(await training.save(true))await move(position.value+1)}
async function play(wordIndex?:number){speechNotice.value='正在读取词典发音…';try{dictionary.value=await playDictionary(props.id,item.value!.exercise_id,wordIndex);speechNotice.value=dictionary.value?.notice||''}catch(e){speechNotice.value=(e as Error).message}}
async function quote(){if(!reference.value)return;const block={id:'english-quote-'+crypto.randomUUID(),quote:reference.value.target,course_id:data.value?.course.id,lesson_id:item.value?.lesson_id,source_study_id:props.id,text:''};const added=notesDetached.value?await noteWindow.add(block):notes.add(block);if(added){drawer.value='notes';notify('已将本句加入计划笔记。')}else notify('笔记尚未确认接收，请保留摘录并重试。','info')}
watch([speechAccent,speechVolume,speechMuted,speechAuto],()=>{stopSpeech();saveSpeechPreferences()})
onMounted(async()=>{try{await training.load();if(item.value?.matched)await nextTick();await nextTick();editor.value?.focusWord(0)}catch(e){reportError(e);failed.value=(e as Error).message}finally{loading.value=false}})
onBeforeUnmount(stopSpeech)
</script>
<template>
 <LeaveStudyDialog v-if="exit.dialog.value" :closing="exit.dialog.value.path==='close-window'" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="training.exportInput"/>
 <div v-if="loading" class="loading-state">正在恢复英语训练…</div>
 <section v-else-if="data&&item" class="english-learning" aria-label="英语专注训练">
  <header class="english-training-header"><button class="text-button" @click="navigate('/course/'+data.course.id)">← 返回课程</button><div class="english-header-title"><strong>{{data.course.title}}</strong><span>{{position+1}} / {{data.items.length}}<template v-if="item.progression"> · {{stageLabels[item.progression.stage]}}</template> · 已有效完成 {{completed}} · 固定材料 r{{data.course.content_revision||'—'}}</span></div><div class="english-header-tools"><button :aria-expanded="settings" @click="settings=!settings">发音设置</button><button :aria-expanded="drawer==='notes'" @click="drawer=drawer==='notes'?null:'notes'">笔记</button></div></header>
  <div v-if="settings" class="english-speech-settings"><label>口音请求 <select v-model="speechAccent"><option value="en-US">美式</option><option value="en-GB">英式</option></select></label><label>语音音量 {{speechVolume}}% <input v-model.number="speechVolume" type="range" min="0" max="100"/></label><label><input v-model="speechMuted" type="checkbox"/>静音</label><label><input v-model="speechAuto" type="checkbox"/>检查通过后朗读</label><small>使用网络词典；口音是提供方请求，不承诺声音质量。界面音效在工作区另行设置。</small></div>
  <p v-if="data.course.source_changed" class="english-assistance">课程已有新修订，本轮仍使用开始时的材料；新材料需从课程概览开启新轮次。</p>
  <div v-if="recovery" class="english-recovery" role="status">发现此轮的本机未保存输入。<button @click="training.restore">恢复输入</button><button @click="training.discardRecovery">保留工作区版本</button><button @click="training.exportInput">导出</button></div>
  <div v-if="failed" class="english-error" role="alert">{{failed}}<button :disabled="busy" @click="training.retryPending">重试原请求</button><button @click="training.exportInput">导出输入</button><button @click="navigate('/course/'+data.course.id)">离开训练…</button></div>
  <div class="english-work-surface" :class="{'has-drawer':drawer}">
   <main class="english-stage">
    <template v-if="phase!=='result'"><div class="english-question"><span class="english-kicker">{{item.group_title}}</span><h1>{{item.prompt}}</h1><p>将意思写成英文 · {{item.evaluation_mode==='agent'?'开放表达，由Agent审核':'按单词输入，空格或回车向前'}}</p></div>
     <button v-if="currentGroup?.blocks.length&&(item.progression?.stage!=='transfer'||item.matched)" class="text-button english-explain-toggle" :aria-expanded="lessonOpen" @click="lessonOpen=!lessonOpen">查看本组讲解</button>
     <section v-if="lessonOpen&&currentGroup" class="english-inline-teaching"><TeachingContent :blocks="currentGroup.blocks.filter(b=>b.type!=='practice')" :exercises="[]" :notes="notes.blocks.value" :study-id="id" :lesson-id="item.lesson_id" :blocked="busy" :preference-scope="(data.workspace_key||id)+':'+(data.content_hash||id)"/></section>
     <TokenEditor v-if="phase!=='answer'" ref="editor" v-model="tokens" :disabled="busy||locked" :differences="phase==='correction'?item.differences:[]" @edited="training.edited" @check="check"/>
     <div v-else class="english-answer"><p class="english-target">{{reference?.target||item.answer_text}}</p><p v-if="reference?.phonetic" class="english-phonetic">{{reference.phonetic}}</p><p>{{reference?.gloss}}</p><p class="english-explanation">{{reference?.explanation}}</p><div class="english-audio-actions"><button @click="play()">▷ 朗读本句</button><button @click="quote">摘录到笔记</button></div><div class="english-word-lookup"><button v-for="(word,i) in reference?.tokens||item.answer_text.split(/\s+/)" :key="i" @click="play(i)">{{word}}</button></div></div>
     <p v-if="phase==='correction'" class="english-inline-feedback">{{item.evaluation_mode==='agent'?'本项需要Agent审核，不作本地对错判断。':'已定位不匹配的词位。原输入仍保留；直接输入即可替换。'}}</p><p v-if="item.assisted" class="english-assistance">本项查看过辅助信息，和无提示结果分开记录。</p><p v-if="locked" class="english-assistance">{{item.status==='WAITING_REVIEW'?'此项等待Agent审核，其余项可继续。':'此项已经正式确认；原答案不可覆盖。'}}</p>
     <div ref="actions" class="english-main-actions"><button v-if="phase!=='answer'&&!locked" class="primary-button" :disabled="busy" @click="item.evaluation_mode==='agent'?training.requestReview():check()">{{busy?'正在处理…':item.evaluation_mode==='agent'?'提交本项审核':'检查答案 ↵'}}</button><button v-else-if="position<data.items.length-1" class="primary-button" :disabled="busy" @click="move(position+1)">下一项 →</button><button v-else class="primary-button" :disabled="busy" @click="training.submit">完成并提交本课</button><button v-if="phase==='answer'&&!locked&&!item.matched" class="text-button" @click="training.resumeInput">回到输入继续练习</button><button v-if="!locked&&phase!=='answer'" class="text-button" :disabled="busy" @click="training.reveal">查看答案</button><button v-if="!locked&&phase!=='answer'&&position<data.items.length-1" class="text-button" :disabled="busy" @click="skip">暂时跳过</button><button v-if="phase==='correction'&&item.evaluation_mode!=='agent'" class="text-button" :disabled="busy" @click="training.requestReview">表达合理？交给Agent审核</button></div>
     <p v-if="speechNotice" class="english-assistance" role="status">{{speechNotice}}</p><div v-if="dictionary?.definitions.length" class="english-dictionary"><strong>{{dictionary.target}} {{dictionary.phonetic}}</strong><p v-for="(meaning,i) in dictionary.definitions.slice(0,3)" :key="i"><span>{{meaning.part_of_speech}}</span> {{meaning.definition}}</p></div>
    </template>
    <div v-else class="english-result"><span class="english-kicker">本轮已提交</span><h1>这门课的训练已确认</h1><p>{{completed}} / {{data.items.length}} 项有有效结果；开放表达或争议仍以Agent反馈为准。</p><p>一次通过不代表长期掌握。之后可以从计划课程或复习清单继续。</p><button class="primary-button" @click="navigate('/course/'+data.course.id)">返回课程</button><button class="secondary-button" @click="navigate('/mistakes')">查看错误与复习</button></div>
    <AnswerReference v-if="item&&!data.completed" :key="item.exercise_id" :study-id="data.study_session_id" :exercise-id="item.exercise_id"/>
   </main>
   <aside v-if="drawer==='notes'" class="english-drawer" aria-label="计划笔记"><header><h2>计划笔记</h2><button @click="drawer=null" aria-label="关闭侧栏">×</button></header><div class="english-note-tools"><button v-if="isTauri()&&!notesDetached" class="text-button" :disabled="noteWindow.opening.value" @click="noteWindow.detach">弹出笔记窗口</button><button v-if="notesDetached" class="text-button" @click="noteWindow.putBack">放回侧栏</button><button v-if="notesDetached" class="text-button" @click="noteWindow.detach">聚焦笔记窗口</button></div><p v-if="noteWindow.notice.value" role="status">{{noteWindow.notice.value}} <button class="text-button" @click="noteWindow.refresh(true)">重试连接</button></p><p v-if="notesDetached" class="muted">笔记在独立窗口编辑，这里只读显示。</p><PlanNotebook :notebook="notes" :plan-title="data.course.plan_line||data.course.title" :course-id="data.course.id" :lesson-id="item.lesson_id" :blocked="notesDetached"/></aside>
  </div>
  <footer class="english-training-footer"><button @click="directoryOpen=!directoryOpen">☰ 课程目录</button><button :disabled="position===0||busy" @click="move(position-1)">← 上一项</button><span>空格 / 回车向前 · 可暂时跳过</span><span role="status">{{busy?'正在保存或检查…':training.dirty.value?'尚有未保存输入':failed?'保存未确认':'草稿已同步'}}</span></footer>
  <dialog v-if="directoryOpen" ref="directoryDialog" class="english-directory-overlay" aria-labelledby="english-directory-title" @cancel.prevent="directoryOpen=false"><section class="english-directory-dialog"><header><h2 id="english-directory-title">课程目录</h2><button autofocus @click="directoryOpen=false" aria-label="关闭课程目录">×</button></header><ol class="english-directory"><li v-for="(entry,i) in data.items" :key="entry.exercise_id"><button :aria-current="position===i?'step':undefined" @click="move(i)"><span>{{i+1}}</span><strong>{{entry.title}}</strong><i>{{entry.matched?'✓':entry.skipped?'暂跳':''}}</i></button></li></ol></section></dialog>
 </section>
 <div v-else class="error-state"><h2>英语课程暂未读取</h2><button @click="navigate('/plans')">返回计划</button></div>
</template>
