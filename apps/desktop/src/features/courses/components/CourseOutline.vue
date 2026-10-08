<script setup lang="ts">
import {computed,ref} from 'vue'
import type {LessonDetail} from '../../../shared/api/contracts'
import type {AnswerRow} from '../../learning/composables/useCourseAnswers'
import {knowledgePointState} from '../knowledgePointState'
import KnowledgeStatusIcon from './KnowledgeStatusIcon.vue'
const props=defineProps<{planTitle:string;courseTitle:string;position:number;total:number;lessons:LessonDetail[];index:number;rows:AnswerRow[];headings:{id:string;title:string;level:number}[];activeHeading:string;busy:boolean;readingPercent:number}>()
const emit=defineEmits<{select:[index:number];heading:[id:string];back:[]}>()
const mode=ref<'course'|'section'>('course')
const steps=computed(()=>props.lessons.map((lesson,i)=>({lesson,state:knowledgePointState(lesson,props.rows,i===props.index)})))
</script>
<template>
 <section class="sequence-course-outline" aria-label="课程与本节大纲">
  <div class="sequence-plan-summary"><p class="sequence-kicker">当前学习计划</p><div class="sequence-plan-row"><strong :title="planTitle">{{planTitle}}</strong><div class="sequence-mini-progress"><span>本课阅读 <b>{{readingPercent}}%</b></span><div role="progressbar" aria-label="本课阅读进度" :aria-valuenow="readingPercent" aria-valuemin="0" aria-valuemax="100"><i :style="{width:readingPercent+'%'}"/></div></div></div><p class="sequence-course-meta" :title="courseTitle">第 {{position}} / {{total}} 课 · {{courseTitle}}</p></div>
  <div class="sequence-outline-switch" role="tablist" aria-label="大纲类型"><span :class="{right:mode==='section'}" aria-hidden="true"/><button role="tab" id="sequence-course-tab" :aria-selected="mode==='course'" aria-controls="sequence-outline-list" @click="mode='course'">课程大纲</button><button role="tab" id="sequence-section-tab" :aria-selected="mode==='section'" aria-controls="sequence-outline-list" @click="mode='section'">本节大纲</button></div>
  <p class="sequence-outline-caption">{{mode==='course'?'课程知识点':'文档标题导航'}}</p>
  <nav id="sequence-outline-list" class="sequence-outline-list" role="tabpanel" :aria-labelledby="mode==='course'?'sequence-course-tab':'sequence-section-tab'">
   <template v-if="mode==='course'"><button v-for="({lesson,state},i) in steps" :key="lesson.id" :class="['sequence-outline-item','state-'+state.kind,{current:i===index}]" :disabled="busy" :aria-current="i===index?'step':undefined" :aria-label="lesson.title+'，'+state.label" @click="emit('select',i)"><KnowledgeStatusIcon :kind="state.kind"/><span class="sequence-outline-copy"><strong>{{lesson.title.replace(/^\d+[｜|·.、\s]+/,'')}}</strong><small>{{state.label}}</small></span><small class="sequence-outline-index">{{String(i+1).padStart(2,'0')}}</small></button></template>
   <template v-else><button v-for="heading in headings" :key="heading.id" class="sequence-outline-item section-link" :class="{current:activeHeading===heading.id}" :style="{paddingLeft:12+Math.max(0,heading.level-2)*12+'px'}" :aria-current="activeHeading===heading.id?'location':undefined" @click="emit('heading',heading.id)"><i/><span>{{heading.title}}</span></button><p v-if="!headings.length" class="sequence-outline-empty">本节暂无分级标题</p></template>
  </nav>
  <button class="sequence-return" @click="emit('back')"><span>←</span> 返回课程目录</button>
 </section>
</template>
