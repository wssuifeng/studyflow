<script setup lang="ts">
import {onMounted,ref} from 'vue'
import {engineCall} from '../../../shared/api'
import {reportError} from '../../../shared/ui'
import type {CourseDetailData} from '../../../shared/api/contracts'
import CourseReader from './CourseReader.vue'
import EnglishCourseOverview from '../../english/course/EnglishCourseOverview.vue'
const props=defineProps<{id:string;planLineId?:string;lessonId?:string;initialView?:string;studyId?:string;exerciseId?:string}>()
const data=ref<CourseDetailData|null>(null),failed=ref(false)
async function load(){failed.value=false;try{data.value=await engineCall<CourseDetailData>('course.detail',{course_id:props.id})}catch(e){failed.value=true;reportError(e)}}
onMounted(load)
</script>
<template><EnglishCourseOverview v-if="data?.course.learning_mode==='english'" :data="data" :plan-line-id="planLineId"/><CourseReader v-else-if="data" v-bind="props"/><div v-else-if="failed" class="error-state"><p>课程读取未完成。</p><button @click="load">重试</button></div><div v-else class="loading-state">正在读取课程…</div></template>
