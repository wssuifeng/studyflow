<script setup lang="ts">
import type {ContentStep} from '../../../shared/api/contracts/content'
import type {NotebookBlock} from '../../../shared/api/contracts'
import TeachingRichText from './TeachingRichText.vue'
defineProps<{steps:ContentStep[];notes:NotebookBlock[];studyId:string;lessonId:string}>()
</script>
<template><ol class="teaching-steps"><li v-for="(step,i) in steps" :key="i"><span class="teaching-step-index" aria-hidden="true">{{String(i+1).padStart(2,'0')}}</span><div><h5>{{step.title}}</h5><TeachingRichText :html="step.body_html" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/></div></li></ol></template>
