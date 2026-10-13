<script setup lang="ts">
import {computed,ref} from 'vue'
import type {Source} from '../editor/model'
import NotebookIcon from './NotebookIcon.vue'
const props=defineProps<{source:Source;state:'ORIGINAL'|'PARTIAL'|'EDITED';readonly:boolean;x:number;y:number}>()
const emit=defineEmits<{close:[];remove:[];restore:[];navigate:[];pin:[value:boolean]}>()
const original=ref(false),pinned=ref(false)
const label=computed(()=>({ORIGINAL:'原文',PARTIAL:'原文片段',EDITED:'已改写'}[props.state]))
</script>
<template><div class="source-popover popover" role="dialog" aria-label="引用来源" :style="{left:x+'px',top:y+'px'}" @click.stop @keydown.esc.stop="emit('close')"><header><span class="source-label"><NotebookIcon name="quote"/>引用出处</span><div><span class="source-state">{{label}}</span><button class="icon-btn" title="固定来源浮层" :aria-pressed="pinned" @click="pinned=!pinned;emit('pin',pinned)"><NotebookIcon name="pin"/></button><button class="icon-btn" aria-label="关闭来源" @click="emit('close')"><NotebookIcon name="close"/></button></div></header><h4>{{source.lessonTitle}}</h4><p class="source-context">{{source.courseTitle}} · {{source.version}}</p><small v-if="source.verification!=='VERIFIED'">{{source.verification==='PENDING'?'保存时由 Core 核验出处':'旧来源待核验，原摘录已保留'}}</small><button class="source-original-toggle" @click="original=!original">{{original?'收起原始摘录':'查看原始摘录'}}<NotebookIcon name="chevron"/></button><blockquote v-if="original">{{source.original}}</blockquote><div class="source-buttons"><button v-if="source.studyId" @click="emit('navigate')">查看冻结正文</button><button :disabled="readonly" @click="emit('remove')">转为普通笔记</button><button :disabled="readonly" @click="emit('restore')">恢复原文</button></div></div></template>
