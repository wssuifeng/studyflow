<script setup lang="ts">
import {ref,onMounted} from 'vue'
import {engineCall} from '../../../shared/api'
import type {LessonDetail} from '../../../shared/api/contracts'
import {reportError,navigate} from '../../../shared/ui'
import type {TeachingBlock} from '../../../shared/api/contracts/content'
import TeachingContent from '../../courses/components/TeachingContent.vue'
const props=defineProps<{studyId:string;lessonId:string;blockId?:string}>()
const data=ref<{content_hash:string;course:{title:string};lesson:LessonDetail;block?:TeachingBlock|null}|null>(null),failed=ref(false)
onMounted(async()=>{try{data.value=await engineCall('course.source.read',{study_session_id:props.studyId,lesson_id:props.lessonId,...(props.blockId?{block_id:props.blockId}:{})})}catch(cause){failed.value=true;reportError(cause)}})
</script>
<template><button class="back-button" @click="navigate('/plans')">← 学习计划</button><p class="source-readonly-label">冻结来源 · 只读，不开启学习轮次</p><template v-if="data"><h2>{{data.lesson.title}}</h2><p class="muted">{{data.course.title}} · 版本 {{data.content_hash.slice(0,10)}}</p><article class="source-reader"><TeachingContent v-if="data.lesson.content_blocks?.length" :blocks="data.block?[data.block]:data.lesson.content_blocks" :exercises="data.lesson.exercises" :notes="[]" :study-id="studyId" :lesson-id="lessonId" :blocked="true"/><div v-else class="markdown-body" v-html="data.lesson.rendered_html"/></article></template><p v-else>{{failed?'来源无法读取，请回到笔记查看已保存摘录。':'正在读取冻结来源…'}}</p></template>
