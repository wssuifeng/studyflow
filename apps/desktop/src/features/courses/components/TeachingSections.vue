<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {TeachingSection} from '../../../shared/api/contracts/content'
import type {NotebookBlock} from '../../../shared/api/contracts'
import TeachingRichText from './TeachingRichText.vue'
import {detailsPreferenceKey,readDetailsPreference,saveDetailsPreference} from '../detailsDisclosure'
const props=withDefaults(defineProps<{sections:TeachingSection[];blockId:string;lessonId:string;studyId:string;scope:string;notes:NotebookBlock[];depth?:number}>(),{depth:1})
const expanded=ref<Record<string,boolean>>({})
function storage(){try{return window.localStorage}catch{return null}}
const key=(id:string)=>detailsPreferenceKey(props.scope,props.lessonId,props.blockId+':section:'+id)
watch(()=>[props.scope,props.lessonId,props.blockId,props.sections],()=>{expanded.value=Object.fromEntries(props.sections.map(s=>[s.id,readDetailsPreference(storage(),key(s.id))]))},{immediate:true})
const anchor=(id:string)=>'content-section-'+props.lessonId+'-'+props.blockId+'-'+id
const heading=computed(()=>props.depth===1?'h5':'h6')
function toggle(id:string,event:Event){const value=(event.target as HTMLDetailsElement).open;expanded.value={...expanded.value,[id]:value};saveDetailsPreference(storage(),key(id),value)}
</script>
<template>
 <div class="teaching-sections">
  <template v-for="section in sections" :key="section.id">
   <section v-if="section.role==='main'" class="teaching-section section-main" :data-content-section="section.id" :aria-labelledby="anchor(section.id)"><component :is="heading" :id="anchor(section.id)" class="teaching-section-title" :data-outline-level="depth+2">{{section.title}}</component><TeachingRichText :html="section.body_html" :heading-base="6" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/><TeachingSections v-if="section.children" :sections="section.children" :block-id="blockId" :lesson-id="lessonId" :study-id="studyId" :scope="scope" :notes="notes" :depth="depth+1"/></section>
   <details v-else class="teaching-section section-supplement" :data-content-section="section.id" :open="expanded[section.id]" @toggle="toggle(section.id,$event)"><summary :aria-expanded="expanded[section.id]" :aria-controls="anchor(section.id)+'-body'"><component :is="heading" :id="anchor(section.id)" class="teaching-section-title" :data-outline-level="depth+2">{{section.title}}</component><span class="section-summary markdown-body" v-html="section.summary_html"/><span class="section-disclosure-label">{{expanded[section.id]?'收起详解':'展开详解'}}</span></summary><div :id="anchor(section.id)+'-body'" class="section-detail"><TeachingRichText :html="section.body_html" :heading-base="6" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/><TeachingSections v-if="section.children" :sections="section.children" :block-id="blockId" :lesson-id="lessonId" :study-id="studyId" :scope="scope" :notes="notes" :depth="depth+1"/></div></details>
  </template>
 </div>
</template>
