<script setup lang="ts">
import type {LessonDetail} from '../../../shared/api/contracts'
import type {AnswerRow} from '../../learning/composables/useCourseAnswers'
const props=defineProps<{lessons:LessonDetail[];index:number;busy:boolean;answerStates?:AnswerRow[]}>()
const emit=defineEmits<{select:[index:number]}>()
function label(lesson: LessonDetail) {
  const rows=props.answerStates?.filter(row=>row.lessonId===lesson.id) || []
  if(rows.some(row=>row.action==='REVISION' || row.action==='RETEST')) return '需要处理反馈'
  if(rows.some(row=>row.action!=='LOCKED' && !row.answer.trim())) return '有未答题'
  if(rows.length && rows.every(row=>row.action==='LOCKED')) return '已提交'
  return rows.some(row=>row.answer.trim()) ? '有草稿' : lesson.progress.status==='COMPLETED' ? '已读完' : '未开始'
}
</script>
<template><nav class="knowledge-pager" aria-label="知识点导航"><button class="secondary-button" :disabled="index===0 || busy" @click="emit('select',index-1)">← 上一知识点</button><div class="pager-center"><span class="muted small">知识点 {{index+1}} / {{lessons.length}}</span><div class="pager-dots"><button v-for="(lesson,i) in lessons" :key="lesson.id" :class="{selected:i===index,completed:lesson.progress.status==='COMPLETED','needs-answer':label(lesson)==='有未答题'}" :title="lesson.title+' · '+label(lesson)" :aria-label="'跳转到知识点 '+(i+1)+' '+lesson.title+'，'+label(lesson)" :aria-current="i===index?'step':undefined" :disabled="busy" @click="emit('select',i)">{{i+1}}</button></div></div><button class="secondary-button" :disabled="index===lessons.length-1 || busy" @click="emit('select',index+1)">下一知识点 →</button></nav></template>
