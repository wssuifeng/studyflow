<script setup lang="ts">
import {computed} from 'vue'
import type {NotebookBlock} from '../../../shared/api/contracts'
import {highlightNotebookExcerpts} from '../../notes/highlight'
const props=defineProps<{html:string;notes?:NotebookBlock[];studyId?:string;lessonId?:string}>()
const rendered=computed(()=>props.studyId&&props.lessonId?highlightNotebookExcerpts(props.html,props.notes||[],props.studyId,props.lessonId):props.html)
</script>
<template><div class="teaching-richtext markdown-body" v-html="rendered"/></template>
