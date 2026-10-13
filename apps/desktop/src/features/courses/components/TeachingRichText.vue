<script setup lang="ts">
import {computed} from 'vue'
import type {NotebookBlock} from '../../../shared/api/contracts'
import {normalizeTeachingHeadings} from '../teachingTypography'
import {highlightNotebookExcerpts} from '../../notes/highlight'
const props=defineProps<{html:string;notes?:NotebookBlock[];studyId?:string;lessonId?:string;headingBase?:5|6}>()
const rendered=computed(()=>{const html=normalizeTeachingHeadings(props.html,props.headingBase||5);return props.studyId&&props.lessonId?highlightNotebookExcerpts(html,props.notes||[],props.studyId,props.lessonId):html})
</script>
<template><div class="teaching-richtext markdown-body" v-html="rendered"/></template>
