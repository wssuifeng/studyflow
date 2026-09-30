<script setup lang="ts">
import type {LessonDetail} from '../types'
defineProps<{lessons:LessonDetail[];index:number;busy:boolean}>()
const emit=defineEmits<{select:[index:number]}>()
</script>
<template><nav class="knowledge-pager" aria-label="知识点导航"><button class="secondary-button" :disabled="index===0 || busy" @click="emit('select',index-1)">← 上一知识点</button><div class="pager-center"><span class="muted small">知识点 {{index+1}} / {{lessons.length}}</span><div class="pager-dots"><button v-for="(lesson,i) in lessons" :key="lesson.id" :class="{selected:i===index,completed:lesson.progress.status==='COMPLETED'}" :title="lesson.title" :aria-label="'跳转到知识点 '+(i+1)+' '+lesson.title" :aria-current="i===index?'step':undefined" :disabled="busy" @click="emit('select',i)"/></div></div><button class="secondary-button" :disabled="index===lessons.length-1 || busy" @click="emit('select',index+1)">下一知识点 →</button></nav></template>
