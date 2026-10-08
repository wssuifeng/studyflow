<script setup lang="ts">
import type {LessonDetail} from '../../../shared/api/contracts'
import type {AnswerRow} from '../../learning/composables/useCourseAnswers'
import type {PlanNotebookController} from '../../notes/composables/usePlanNotebook'
import PlanNotebook from '../../notes/components/PlanNotebook.vue'
import KnowledgeExercises from '../../learning/components/KnowledgeExercises.vue'
import type {ToolTab} from '../dock/state'

defineProps<{tool:ToolTab|string;lessons:LessonDetail[];index:number;rows:AnswerRow[];blocked:boolean;notebook:PlanNotebookController;planTitle?:string;courseId?:string}>()
</script>
<template>
 <KnowledgeExercises v-if="tool==='exercises'" :key="lessons[index]?.id" :rows="rows.filter(r=>r.lessonId===lessons[index]?.id)" :blocked="blocked"/>
 <PlanNotebook v-else-if="tool==='notes'" :notebook="notebook" :plan-title="planTitle" :course-id="courseId" :lesson-id="lessons[index]?.id" :blocked="blocked"/>
 <section v-else class="tool-unavailable" role="status" aria-live="polite">
  <strong>工具暂不可用</strong>
  <p>当前工具状态无法识别。重新打开练习或笔记后即可继续，已保存的内容不会受影响。</p>
 </section>
</template>
