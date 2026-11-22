<script setup lang="ts">
import {computed} from 'vue'
import type {LessonDetail} from '../../../shared/api/contracts'
import type {AnswerRow} from '../../learning/composables/useCourseAnswers'
import type {PlanNotebookController} from '../../notes/composables/usePlanNotebook'
import PlanNotebook from '../../notes/components/PlanNotebook.vue'
import KnowledgeExercises from '../../learning/components/KnowledgeExercises.vue'
import type {ToolTab} from '../dock/state'

// Native editor events must never fall through as course navigation.
defineOptions({inheritAttrs:false})
const props = defineProps<{tool:ToolTab|string;lessons:LessonDetail[];index:number;rows:AnswerRow[];blocked:boolean;notebook:PlanNotebookController;planTitle?:string;courseId?:string}>()
const emit = defineEmits<{practice: [exerciseId: string]}>()
const specialized = computed(() => props.lessons[props.index]?.exercises.filter(exercise =>
  ['READING_GROUP','LISTENING_GROUP','ESSAY'].includes(exercise.type)) ?? [])
const essays = computed(() => new Set(specialized.value.filter(exercise => exercise.type === 'ESSAY').map(exercise => exercise.id)))
</script>
<template>
 <template v-if="tool==='exercises'">
  <div v-if="specialized.length" class="tool-practice-groups" aria-label="专项题组和作文">
    <button v-for="exercise in specialized" :key="exercise.id" type="button" class="secondary-button" :disabled="blocked"
      @click="emit('practice', exercise.id)">{{ exercise.title }} · {{ exercise.type === 'ESSAY' ? '打开作文' : exercise.latest_submission ? '查看解析' : '打开题组' }}</button>
  </div>
  <KnowledgeExercises v-if="!specialized.length || rows.some(row => row.lessonId === lessons[index]?.id && !essays.has(row.exercise_id))"
    :key="lessons[index]?.id" :rows="rows.filter(row => row.lessonId === lessons[index]?.id && !essays.has(row.exercise_id))" :blocked="blocked"/>
 </template>
 <PlanNotebook v-else-if="tool==='notes'" :notebook="notebook" :plan-title="planTitle" :course-id="courseId" :lesson-id="lessons[index]?.id" :blocked="blocked"/>
 <section v-else class="tool-unavailable" role="status" aria-live="polite">
  <strong>工具暂不可用</strong>
  <p>当前工具状态无法识别。重新打开练习或笔记后即可继续，已保存的内容不会受影响。</p>
 </section>
</template>
