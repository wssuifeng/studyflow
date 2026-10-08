<script setup lang="ts">
import { computed } from 'vue'
import KnowledgeStatusIcon from './KnowledgeStatusIcon.vue'
import type { LessonDetail } from '../../../shared/api/contracts'
import type { AnswerRow } from '../../learning/composables/useCourseAnswers'
import { knowledgePointState } from '../knowledgePointState'
const props = defineProps<{lessons: LessonDetail[]; index: number; busy: boolean; answerStates?: AnswerRow[]}>()
const emit = defineEmits<{select: [index: number]}>()
const steps = computed(() => props.lessons.map((lesson, i) => ({lesson, state: knowledgePointState(lesson, props.answerStates || [], i === props.index)})))
</script>
<template>
  <nav class="knowledge-pager" aria-label="知识点导航">
    <button class="pager-arrow" :disabled="index === 0 || busy" aria-label="上一知识点" title="上一知识点" @click="emit('select', index - 1)">←</button>
    <div class="knowledge-steps">
      <button v-for="({lesson, state}, i) in steps" :key="lesson.id" :class="['knowledge-step', 'state-' + state.kind, {current: i === index}]"
        :aria-label="'知识点 ' + (i + 1) + '：' + lesson.title + '，' + state.label" :aria-current="i === index ? 'step' : undefined"
        :title="lesson.title + ' · ' + state.label" :disabled="busy" @click="emit('select', i)">
        <span class="step-number">{{String(i + 1).padStart(2, '0')}}</span><span class="step-title">{{lesson.title.replace(/^\d+[｜|·.、\s]+/,'')}}</span><span class="step-label sr-only">{{state.label}}</span><KnowledgeStatusIcon :kind="state.kind"/>
      </button>
    </div>
    <button class="pager-arrow" :disabled="index === lessons.length - 1 || busy" aria-label="下一知识点" title="下一知识点（暂时跳过，自动保存）" @click="emit('select', index + 1)">→</button>
  </nav>
</template>
