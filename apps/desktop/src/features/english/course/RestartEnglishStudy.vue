<script setup lang="ts">
import {nextTick,onBeforeUnmount,onMounted,ref} from 'vue'
import {invoke} from '@tauri-apps/api/core'
import {isTauri,studyApi} from '../../../shared/api'
import type {StudyRestartPreview} from '../../../shared/api/contracts'
import {navigate,makeRequestKey,windowStorageKey,notify} from '../../../shared/ui'
import {prepareTools,releaseTools} from '../../courses/dock/toolWindows'
import {readRestartRequest,storeRestartRequest,definitiveRestartFailure,type RestartParams} from '../../courses/studyRestartRequest'
const props=defineProps<{studyId:string;workspaceKey:string;courseId:string}>()
const busy=ref(false),error=ref(''),info=ref<StudyRestartPreview|null>(null),pending=ref<RestartParams|null>(null),dialog=ref<HTMLDialogElement|null>(null)
let hold:string|undefined,disposed=false
const key=windowStorageKey('english-restart:'+props.courseId)
function storage(){try{return localStorage}catch{return null}}
async function release(){if(hold){const id=hold;hold=undefined;await releaseTools(id)}}
async function close(){if(busy.value)return;dialog.value?.close();info.value=null;await release()}
async function inspect(){
 if(busy.value)return
 if(pending.value){await confirm();return}
 busy.value=true;error.value=''
 try{
  const held=await prepareTools('hold');hold=held.requestId
  if(!held.ok)throw Error('独立笔记窗口还有未确认内容，请先保存或恢复。')
  info.value=await studyApi.previewStudyRestart(props.studyId)
  if(!disposed){await nextTick();dialog.value?.showModal()}
 }catch(e){error.value=(e as Error).message;await release()}finally{busy.value=false}
}
async function confirm(){
 if(busy.value)return
 if(!pending.value){
  if(!info.value?.can_restart||!info.value.expected_content_hash)return
  pending.value={study_session_id:info.value.study_session_id,expected_version:info.value.expected_version,expected_training_version:info.value.expected_training_version,expected_content_hash:info.value.expected_content_hash,idempotency_key:makeRequestKey('english-restart')}
  if(!storeRestartRequest(storage(),key,props.workspaceKey,pending.value)){pending.value=null;error.value='无法持久保存重开请求，未发送。请检查本机存储。';return}
 }
 busy.value=true;error.value=''
 try{
  if(!hold){const held=await prepareTools('hold');hold=held.requestId;if(!held.ok)throw Error('独立笔记窗口未确认；原重开请求已保留。')}
  const fresh=await studyApi.restartStudy({...pending.value!})
  pending.value=null;storeRestartRequest(storage(),key,props.workspaceKey,null)
  if(disposed)return
  if(isTauri()&&fresh.study.is_current&&fresh.course.plan_line_id){try{await invoke('set_tool_context',{context:{courseId:fresh.course.id,studyId:fresh.study.id,planId:fresh.course.plan_line_id,planTitle:fresh.course.plan_line||'',lessonId:fresh.lessons[0]?.id}})}catch{notify('已重新开始；独立笔记窗口未同步，请重新打开该窗口。','info')}}
  dialog.value?.close()
  await release()
  await navigate(fresh.study.is_current?'/english/'+fresh.study.id:'/course/'+props.courseId)
 }catch(e){error.value=(e as Error).message;if(definitiveRestartFailure((e as {code?:string}).code||'')){pending.value=null;storeRestartRequest(storage(),key,props.workspaceKey,null);info.value=null;dialog.value?.close()}}
 finally{busy.value=false;await release()}
}
onMounted(()=>{pending.value=readRestartRequest(storage(),key,props.workspaceKey)})
onBeforeUnmount(()=>{disposed=true;void release()})
</script>
<template>
 <div class="english-restart-control"><button class="text-button" :disabled="busy" @click="inspect">{{pending?'重试待确认的重开请求':'放弃空轮次，用最新材料重新开始'}}</button><p v-if="error" role="alert">{{error}}</p></div>
 <dialog ref="dialog" class="study-restart-dialog" aria-labelledby="english-restart-title" @cancel.prevent="close">
  <h3 id="english-restart-title">用最新材料重新开始？</h3>
  <p>仅允许没有保存答案、检查、文本提示或提交记录的轮次。旧轮次与笔记保留，阅读位置不转移，不把旧记录算作已学会。</p>
  <ul v-if="info&&!info.can_restart"><li v-for="reason in info.blocked_reasons" :key="reason.code">{{reason.message}}</li></ul>
  <p v-if="error" role="alert">{{error}}</p>
  <div class="dialog-actions"><button :disabled="busy" @click="close">保留当前轮次</button><button v-if="info?.can_restart" class="primary-button" :disabled="busy" @click="confirm">{{busy?'正在重新开始…':'确认重新开始'}}</button></div>
 </dialog>
</template>
