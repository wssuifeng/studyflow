<script setup lang="ts">
import {computed,onMounted,ref,watch} from 'vue'
import {engineCall} from '../../../shared/api'
import {makeRequestKey,navigate,reportError} from '../../../shared/ui'
import SupplementCourses from '../../english/remediation/SupplementCourses.vue'
import type {Plan} from '../../../shared/api/contracts'
const props=defineProps<{plans:Plan[]}>()
const plan=ref(''),domain=ref<'general'|'english'>('english'),course=ref(''),view=ref<'training_errors'|'review_queue'>('training_errors'),archived=ref(false)
const courses=ref<{id:string;title:string}[]>([]),items=ref<{id:string;version:number;title:string;course_title:string;course_id:string;failed_attempts?:number;failed_rounds?:number;review_status?:string;status?:string}[]>([])
const summary=ref<Record<string,number>>({}),cursor=ref<string|null>(null),loading=ref(false),detail=ref<{next_cursor:string|null;evidence:{answer_text:string;result?:{differences:{index:number;actual:string;expected:string}[]};feedback?:{summary:string;decision:string};frozen_context?:{exercise:{prompt:string}}}[]}|null>(null)
const scope=computed(()=>({plan_line_id:plan.value,domain:domain.value,course_id:course.value||null,view:view.value,archived:archived.value}))
let readGeneration=0, planGeneration=0, detailGeneration=0
async function load(more=false){
 if(!plan.value)return
 const token=++readGeneration, captured={...scope.value}, identity=JSON.stringify(captured)
 loading.value=true;detailGeneration++;detail.value=null
 if(!more){items.value=[];cursor.value=null}
 try{
  const [stats,result]=await Promise.all([engineCall<typeof summary.value>('mistakes.summary',captured),engineCall<{items:typeof items.value;next_cursor:string|null}>('mistakes.list',{...captured,limit:30,cursor:more?cursor.value:null})])
  if(token!==readGeneration||JSON.stringify(scope.value)!==identity)return
  summary.value=stats;items.value=more?[...items.value,...result.items]:result.items;cursor.value=result.next_cursor
 }catch(e){if(token===readGeneration)reportError(e)}finally{if(token===readGeneration)loading.value=false}
}
async function choosePlan(){
 const token=++planGeneration,selected=plan.value;readGeneration++;detailGeneration++;items.value=[];courses.value=[];detail.value=null;course.value=''
 try{const result=await engineCall<{courses:typeof courses.value}>('course.list',{plan_line_id:selected});if(token!==planGeneration||plan.value!==selected)return;courses.value=result.courses;await load()}catch(e){if(token===planGeneration)reportError(e)}
}
async function inspect(entry:typeof items.value[number],more=false){
 const token=++detailGeneration,captured={...scope.value},identity=JSON.stringify(captured)
 try{
  const result=await engineCall<NonNullable<typeof detail.value>>('mistakes.context',{...captured,identifier:entry.id,expected_version:entry.version,limit:10,cursor:more?detail.value?.next_cursor:null})
  if(token!==detailGeneration||JSON.stringify(scope.value)!==identity)return
  detail.value=more&&detail.value?{...result,evidence:[...detail.value.evidence,...result.evidence]}:result
  selectedEntry.value=entry
 }catch(e){if(token===detailGeneration)reportError(e)}
}
const selectedEntry=ref<typeof items.value[number]|null>(null),actionBusy=ref(false)
async function review(entry:typeof items.value[number]){if(actionBusy.value)return;actionBusy.value=true;try{await engineCall('mistakes.english.review.select',{...scope.value,identifier:entry.id,expected_version:entry.version,idempotency_key:makeRequestKey('english-review-select')});await load()}catch(e){reportError(e)}finally{actionBusy.value=false}}
async function retest(entry:typeof items.value[number]){if(actionBusy.value)return;actionBusy.value=true;try{const result=await engineCall<{task_id:string}>('mistakes.retest.request',{...scope.value,identifier:entry.id,expected_version:entry.version,idempotency_key:makeRequestKey('english-retest-publish')});await navigate('/english-retest/'+result.task_id)}catch(e){reportError(e)}finally{actionBusy.value=false}}
watch([domain,course,view,archived],()=>{void load()})
onMounted(async()=>{plan.value=props.plans[0]?.id||'';if(plan.value)await choosePlan()})
</script>
<template><section class="mistake-workspace"><p class="muted">先选择学习计划，再看课程内的错误。训练统计与长期复习清单分开，原始作答始终保留。</p><div class="mistake-controls"><label>计划 <select v-model="plan" @change="choosePlan"><option v-for="p in plans" :key="p.id" :value="p.id">{{p.name}}</option></select></label><label>课程 <select v-model="course"><option value="">本计划全部课程</option><option v-for="c in courses" :key="c.id" :value="c.id">{{c.title}}</option></select></label><div class="mistake-domain-tabs"><button :class="{selected:domain==='general'}" @click="domain='general'">普通错题</button><button :class="{selected:domain==='english'}" @click="domain='english'">英语训练</button></div><label v-if="domain==='english'"><select v-model="view"><option value="training_errors">训练错误统计</option><option value="review_queue">需要复习</option></select></label><label><input v-model="archived" type="checkbox"/>归档历史</label></div><p v-if="domain==='english'" class="mistake-summary">{{summary.entry_total||0}} 个训练项 · {{summary.failed_attempts||0}} 次失败尝试 · {{summary.failed_rounds||0}} 个失败轮次（去重） · {{summary.review_total||0}} 项待复习</p><p v-else class="mistake-summary">{{summary.entry_total||0}} 条普通错题 · 原题内定位多个问题</p><div v-if="loading" class="loading-state">正在读取指定范围…</div><div v-else-if="!items.length" class="empty-state"><h3>这个范围暂无记录</h3><p>无记录不是已掌握；完成训练或Agent批改后会出现真实证据。</p></div><ul v-else class="mistake-entry-list"><li v-for="entry in items" :key="entry.id"><div><span>{{entry.course_title}}</span><h3>{{entry.title}}</h3><p v-if="domain==='english'">{{entry.failed_attempts}} 次失败 · {{entry.failed_rounds}} 个轮次 · {{entry.review_status||'仅统计，未收录复习'}}</p><p v-else>{{entry.status}}</p></div><div><button @click="inspect(entry)">查看原错与证据</button><button v-if="domain==='english'&&!entry.review_status" :disabled="actionBusy" @click="review(entry)">收录复习</button><button v-if="domain==='english'&&entry.review_status" :disabled="actionBusy" @click="retest(entry)">无提示复测</button><button v-if="domain==='general'" @click="navigate('/course/'+entry.course_id)">返回课程修正</button></div></li></ul><button v-if="cursor" class="secondary-button" :disabled="loading" @click="load(true)">读取下一页</button><section v-if="detail" class="mistake-evidence"><header><h2>原始错误证据</h2><button @click="detail=null">关闭</button></header><article v-for="(e,i) in detail.evidence" :key="i"><h3>{{e.frozen_context?.exercise.prompt}}</h3><p class="mistake-original">{{e.answer_text}}</p><p v-if="e.feedback">{{e.feedback.summary}} · {{e.feedback.decision}}</p><ul v-if="e.result"><li v-for="difference in e.result.differences" :key="difference.index">第{{difference.index+1}}词位：{{difference.actual||'缺少'}} → {{difference.expected||'多余'}}</li></ul></article><button v-if="detail.next_cursor&&selectedEntry" class="secondary-button" @click="inspect(selectedEntry,true)">读取更多原始证据</button></section><SupplementCourses v-if="plan&&domain==='english'" :plan-id="plan" :source-course-id="course||undefined" :aggregate-id="detail&&selectedEntry?selectedEntry.id:undefined"/></section></template>
