<script setup lang="ts">
import {onBeforeUnmount,ref,watch} from 'vue'
import {engineCall} from '../../../shared/api'
import {navigate} from '../../../shared/ui'
import type {SupplementCourse,SupplementDetail} from '../../../shared/api/contracts/english'
const props=defineProps<{planId:string;sourceCourseId?:string;aggregateId?:string}>()
const rows=ref<SupplementCourse[]>([]),loading=ref(false),error=ref(''),next=ref<number|null>(null),detail=ref<SupplementDetail|null>(null)
let generation=0,detailGeneration=0
const labels:Record<string,string>={NOT_STARTED:'未开始',IN_PROGRESS:'学习中',COMPLETED:'补充学习已完成'}
async function load(more=false){
 const token=++generation;detailGeneration++;detail.value=null;loading.value=true;error.value=''
 const scope={plan_line_id:props.planId,source_course_id:props.sourceCourseId||null,aggregate_id:props.aggregateId||null,limit:30,offset:more?next.value||0:0}
 if(!more){rows.value=[];next.value=null}
 try {const result=await engineCall<{items:SupplementCourse[];next_offset:number|null}>('course.remediation.list',scope);if(token!==generation)return;rows.value=more?[...rows.value,...result.items.filter(r=>!rows.value.some(old=>old.course_id===r.course_id))]:result.items;next.value=result.next_offset}
 catch(e){if(token===generation)error.value=(e as Error).message}finally{if(token===generation)loading.value=false}
}
async function inspect(course:SupplementCourse){const token=++detailGeneration;try{const value=await engineCall<SupplementDetail>('course.remediation.get',{course_id:course.course_id});if(token===detailGeneration)detail.value=value}catch(e){if(token===detailGeneration)error.value=(e as Error).message}}
function closeDetail(){detailGeneration++;detail.value=null}
watch(()=>[props.planId,props.sourceCourseId,props.aggregateId],()=>void load(),{immediate:true})
onBeforeUnmount(()=>{generation++;detailGeneration++})
</script>
<template>
 <section class="supplement-courses" aria-label="英语补充学习">
  <header><div><span class="english-kicker">针对性学习</span><h2>补充学习</h2></div><button class="text-button" :disabled="loading" @click="load()">刷新</button></header>
  <p class="muted">围绕相关错误，从必要词汇逐步组合到新的表达；独立于主线推进。</p>
  <p v-if="error" class="error-state" role="alert">{{error}} <button class="text-button" @click="load()">重试读取</button></p>
  <p v-if="loading" role="status">正在读取补充课程…</p>
  <ol v-if="rows.length" class="supplement-course-list"><li v-for="course in rows" :key="course.course_id"><div><span class="supplement-status">{{labels[course.learning_status]}}</span><h3>{{course.title}}</h3><p>{{course.summary||course.rationale}}</p><p v-if="course.transfer_status==='UNASSISTED_PASS'" class="muted">本轮迁移验证无提示通过；原错题复测单独记录。</p><p v-else-if="course.transfer_status==='ASSISTED_PASS'" class="muted">迁移验证使用过辅助信息，未记为无提示通过。</p></div><div class="supplement-actions"><button class="text-button" @click="inspect(course)">学习目标与来源</button><button class="secondary-button" @click="navigate('/course/'+course.course_id+'?plan='+course.plan_line_id)">{{course.learning_status==='NOT_STARTED'?'开始学习':'继续 / 查看'}} →</button></div></li></ol>
  <p v-else-if="!loading&&!error" class="supplement-empty">此范围暂无补充课程。外部 Agent 可读取英语错误证据，经授权编写并发布；软件不会自动生成或改变主线。</p>
  <button v-if="next!==null" class="secondary-button" :disabled="loading" @click="load(true)">读取更多补充课程</button>
  <section v-if="detail" class="supplement-source"><header><h3>{{detail.title}} · 目标与来源</h3><button class="text-button" @click="closeDetail">收起</button></header><p>{{detail.rationale}}</p><p class="muted">目标：{{detail.objective_ids.join(' · ')}}</p><ul><li v-for="source in detail.sources" :key="source.evidence_id"><strong>{{source.source_course_title}}</strong> · 来源规则版本 {{source.source_version}} <span v-if="!source.evidence_still_valid">（原证据已被重新裁定，历史关联保留）</span></li></ul><p class="muted">补充完成不自动消除原错误。原题复测仍从英语错误与复习页进行。</p><button class="text-button" @click="navigate('/mistakes')">返回错误与复习 →</button></section>
 </section>
</template>
