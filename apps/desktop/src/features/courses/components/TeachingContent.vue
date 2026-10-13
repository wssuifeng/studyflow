<script setup lang="ts">
import { computed,ref,watch,nextTick,onMounted } from 'vue'
import {revealTeachingTarget} from '../detailsDisclosure'
import { teachingGroups } from '../teachingPresentation'
import TeachingBlockIcon from './TeachingBlockIcon.vue'
import type {TeachingBlock} from '../../../shared/api/contracts/content'
import type {LessonDetail,NotebookBlock} from '../../../shared/api/contracts'
import TeachingRichText from './TeachingRichText.vue'
import TeachingSteps from './TeachingSteps.vue'
import TeachingDisclosure from './TeachingDisclosure.vue'
import TeachingSections from './TeachingSections.vue'
const props = defineProps<{blocks:TeachingBlock[];lessonTitle?:string;exercises:LessonDetail['exercises'];notes:NotebookBlock[];studyId:string;lessonId:string;blocked:boolean;preferenceScope?:string;revealBlockId?:string;revealSectionId?:string;revealAllDetails?:boolean}>()
const content=ref<HTMLElement|null>(null)
async function reveal(){await nextTick();if(props.revealSectionId){const node=content.value?.querySelector<HTMLElement>(`[data-content-section="${props.revealSectionId}"]`)||null;revealTeachingTarget(node);node?.scrollIntoView({block:'start'})}if(props.revealAllDetails)content.value?.querySelectorAll<HTMLElement>('[data-reading-component="details"],.section-supplement').forEach(node=>revealTeachingTarget(node,true));if(props.revealBlockId)revealTeachingTarget(content.value?.querySelector<HTMLElement>(`[data-content-block="${props.revealBlockId}"]`)||null,true)}
onMounted(reveal);watch(()=>[props.revealBlockId,props.revealSectionId,props.revealAllDetails,props.blocks],reveal,{flush:'post'})
const groups = computed(() => teachingGroups(props.blocks))
const emit=defineEmits<{practice:[exerciseId:string]}>()
const labels:Record<string,string>={details:'展开理解',concept:'理解概念',comparison:'对比辨析',steps:'过程拆解',example:'推导案例',callout:'留意这里',summary:'带走这些',practice:'学以致用'}
</script>
<template>
 <div ref="content" class="teaching-content document-template continuous-reading">
  <div v-for="group in groups" :key="group.key" class="teaching-group" :class="{'is-concept-pair':group.paired}">
  <section v-for="block in group.blocks" :key="block.id" :id="'content-block-'+lessonId+'-'+block.id" :data-content-block="block.id" :data-reading-component="block.type" :class="['teaching-block','teaching-'+block.type,block.type==='callout'?'tone-'+(block.tone||'note'):'']" :aria-labelledby="'block-title-'+lessonId+'-'+block.id">
   <header class="teaching-block-heading" :class="{'sr-only':block.title===lessonTitle}" :data-outline-hidden="block.title===lessonTitle?'true':undefined"><span v-if="!['concept','details','summary'].includes(block.type)" class="teaching-kind"><TeachingBlockIcon :kind="block.type"/>{{labels[block.type]}}</span><h4 :id="'block-title-'+lessonId+'-'+block.id">{{block.title}}</h4></header>
   <TeachingDisclosure v-if="block.type==='details'" :block="block" :notes="notes" :study-id="studyId" :lesson-id="lessonId" :scope="preferenceScope||studyId"/>
   <TeachingSections v-else-if="block.type==='concept'&&block.sections" :sections="block.sections" :block-id="block.id" :lesson-id="lessonId" :study-id="studyId" :scope="preferenceScope||studyId" :notes="notes"/>
   <TeachingRichText v-else-if="block.type==='concept'||block.type==='callout'" :html="block.body_html||''" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/>
   <div v-else-if="block.type==='comparison'" class="teaching-table-scroll" tabindex="0" :aria-label="block.title+'，可横向滚动'"><table><caption class="sr-only">{{block.title}}</caption><thead><tr><th v-for="(col,i) in block.columns" :key="i" scope="col">{{col}}</th></tr></thead><tbody><tr v-for="(row,i) in block.rows" :key="i"><template v-for="(cell,j) in row" :key="j"><th v-if="j===0" scope="row">{{cell}}</th><td v-else>{{cell}}</td></template></tr></tbody></table></div>
   <TeachingSteps v-else-if="block.type==='steps'" :steps="block.items" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/>
   <template v-else-if="block.type==='example'"><div class="example-given"><span class="example-label">已知条件</span><TeachingRichText :html="block.given_html" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/></div><TeachingSteps :steps="block.steps" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/><div class="example-conclusion"><span class="example-label">结论</span><TeachingRichText :html="block.conclusion_html" :notes="notes" :study-id="studyId" :lesson-id="lessonId"/></div></template>
   <ul v-else-if="block.type==='summary'" class="teaching-takeaways"><li v-for="(item,i) in block.items" :key="i">{{item}}</li></ul>
   <div v-else-if="block.type==='practice'" class="teaching-practice-links"><button v-for="id in block.exercise_ids" :key="id" :disabled="blocked" @click="emit('practice',id)"><span>{{exercises.find(e=>e.id===id)?.title||'打开练习'}}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4 10h12m-5-5 5 5-5 5"/></svg></button></div>
  </section>
  </div>
 </div>
</template>
