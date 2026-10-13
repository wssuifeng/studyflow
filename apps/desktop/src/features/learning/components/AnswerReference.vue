<script setup lang="ts">
import {ref,watch,onBeforeUnmount} from 'vue'
import {studyApi,type ExerciseReference} from '../../../shared/api/study-api'
const props=defineProps<{studyId?:string;exerciseId:string;submissionId?:string}>()
const open=ref(false),busy=ref(false),error=ref(''),data=ref<ExerciseReference|null>(null)
let generation=0
watch(()=>[props.studyId,props.exerciseId,props.submissionId],()=>{generation++;open.value=false;busy.value=false;data.value=null;error.value=''})
onBeforeUnmount(()=>generation++)
async function load(){
 if(busy.value)return
 const current=++generation;busy.value=true;error.value=''
 try{
  const params=props.studyId?{study_session_id:props.studyId,exercise_id:props.exerciseId}:{submission_id:props.submissionId}
  const result=await studyApi.viewReference(params)
  if(current===generation)data.value=result
 }catch{if(current===generation)error.value='解析暂未读取成功，答案与草稿不受影响。'}
 finally{if(current===generation)busy.value=false}
}
function toggle(event:Event){open.value=(event.target as HTMLDetailsElement).open;if(open.value&&!data.value)void load()}
</script>
<template>
 <details class="answer-reference" :open="open" @toggle="toggle">
  <summary>答案与解析 <small>主动查看会记录为有提示学习</small></summary>
  <div class="answer-reference-body" aria-live="polite">
   <p v-if="busy">正在读取本轮题面对应的解析…</p>
   <p v-else-if="error">{{error}} <button class="text-button" @click="load">重试</button></p>
   <template v-else-if="data?.available&&data.reference"><h5>参考结果</h5><div class="markdown-body" v-html="data.rendered?.answer"/><h5>为什么</h5><div class="markdown-body" v-html="data.rendered?.explanation"/><h5>检验要点</h5><ul><li v-for="(criterion,i) in data.reference.criteria" :key="i">{{criterion}}</li></ul><template v-if="data.reference.accepted_variants?.length"><h5>可接受的表达</h5><ul><li v-for="(variant,i) in data.reference.accepted_variants" :key="i">{{variant}}</li></ul></template><p v-if="data.reference.source" class="reference-source">依据：{{data.reference.source}} · 内容版本 {{data.content_revision}}</p></template>
   <p v-else-if="data">{{data.reason||'这道题尚未配置答案解析。'}}</p>
  </div>
 </details>
</template>
