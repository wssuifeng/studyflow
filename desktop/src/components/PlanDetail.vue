<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {studyApi} from '../bridge'
import type {PlanDetailData} from '../types'
import {navigate,reportError} from '../ui'
const props=defineProps<{id:string}>()
const data=ref<PlanDetailData|null>(null)
const loading=ref(true)
async function load(){loading.value=true;try{data.value=await studyApi.planDetail(props.id)}catch(e){reportError(e)}finally{loading.value=false}}
onMounted(load)
</script>
<template><button class="back-button" @click="navigate('/plans')">← 我的计划</button><div v-if="loading" class="loading-state">正在读取课程顺序…</div><template v-else-if="data"><div class="detail-heading"><div><p class="eyebrow">LEARNING PATH</p><h2>{{data.plan.name}}</h2><p>{{data.plan.course_total}} 门课程 · {{data.plan.completed_courses}} 门练习已通过</p></div><button v-if="data.current_course" class="primary-button" @click="navigate('/course/'+data.current_course.id)">继续当前课程 →</button></div><div class="progress-track"><i :style="{width:data.plan.progress_percent+'%'}"/></div><ol class="path-list"><li v-for="course in data.courses" :key="course.id" :class="{current:course.id===data.current_course?.id}"><span class="path-marker">{{course.progress_percent===100?'✓':course.sequence}}</span><div><span class="eyebrow" v-if="course.id===data.current_course?.id">当前推进课程</span><h3>{{course.title}}</h3><p>{{course.knowledge_total}} 个知识点 · 练习通过 {{course.exercise_completed}}/{{course.exercise_total}}</p></div><button class="secondary-button" @click="navigate('/course/'+course.id)">{{course.progress_percent===100?'回顾':'进入课程'}} →</button></li></ol><div v-if="!data.courses.length" class="empty-state"><p>计划已建立，课程内容等待导入。</p></div></template><div v-else class="empty-state"><p>计划未能读取。</p><button class="secondary-button" @click="load">重试</button></div></template>
