<script setup lang="ts">
import {ref,watch,computed} from 'vue'
import type {TeachingBlock} from '../../../shared/api/contracts/content'
import type {NotebookBlock} from '../../../shared/api/contracts'
import {interactionFeedback} from '../../../shared/ui/interaction'
import {detailsPreferenceKey,readDetailsPreference,saveDetailsPreference} from '../detailsDisclosure'
import TeachingRichText from './TeachingRichText.vue'
const props=defineProps<{block:Extract<TeachingBlock,{type:'details'}>;notes:NotebookBlock[];studyId:string;lessonId:string;scope:string}>()
const expanded=ref(false)
const key=computed(()=>detailsPreferenceKey(props.scope,props.lessonId,props.block.id))
function storage(){try{return window.localStorage}catch{return null}}
watch(key,value=>{expanded.value=readDetailsPreference(storage(),value)},{immediate:true})
function toggle(event:Event){const open=(event.target as HTMLDetailsElement).open;if(open===expanded.value)return;expanded.value=open;saveDetailsPreference(storage(),key.value,open);interactionFeedback('open')}
</script>
<template>
 <TeachingRichText class="teaching-detail-summary" :html="block.summary_html" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/>
 <details class="teaching-disclosure" :open="expanded" @toggle="toggle">
  <summary :aria-expanded="expanded" :aria-controls="'detail-body-'+lessonId+'-'+block.id"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6"/></svg><span>{{expanded?'收起详解':'展开详解'}}</span><small>补充解释与推导</small></summary>
  <div :id="'detail-body-'+lessonId+'-'+block.id" class="teaching-detail-body"><TeachingRichText :html="block.body_html" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/></div>
 </details>
</template>
