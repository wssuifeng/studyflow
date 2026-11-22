<script setup lang="ts">
import {computed, shallowRef, watch} from 'vue'
import {studyApi} from '../../shared/api'
import type {SubmissionDetailData} from '../../shared/api/contracts'
import WritingWorkspace from './WritingWorkspace.vue'

type EssayItem = {
  title: string
  prompt: string
  requirements?: string
  essay?: {suggested_words?: [number, number]; points?: string[]}
  answer_text: string
  submission_id: string | null
  status: string
}

const props = defineProps<{item: EssayItem; text: string; dirty: boolean; blocked: boolean}>()
const emit = defineEmits<{edit: [value: string]; save: []; submit: []}>()
const firstDraft = computed(() => ['NOT_STARTED', 'DRAFT'].includes(props.item.status))
const action = computed<'FIRST' | 'REVISION' | 'LOCKED'>(() => firstDraft.value ? 'FIRST' : props.item.status === 'NEEDS_REVISION' ? 'REVISION' : 'LOCKED')
const submitted = computed(() => ['WAITING_REVIEW', 'PASSED', 'RECHECKED', 'REVIEWED'].includes(props.item.status))
const submission = shallowRef<SubmissionDetailData | null>(null)
const feedbackError = shallowRef(false)
watch(() => firstDraft.value ? null : props.item.submission_id, async (id, _, cleanup) => {
  let active = true
  cleanup(() => {active = false})
  submission.value = null
  feedbackError.value = false
  if (!id) return
  try {
    const current = await studyApi.submission(id)
    if (active) submission.value = current
  } catch {
    if (active) feedbackError.value = true
  }
}, {immediate: true})
const row = computed(() => ({
  title: props.item.title,
  prompt: props.item.prompt,
  requirements: props.item.requirements ?? '',
  essay: props.item.essay,
  answer: props.text,
  savedAnswer: props.item.answer_text,
  action: action.value,
  submission: submission.value,
  draft: null,
}))
</script>

<template>
  <section aria-label="写作练习" class="essay-exercise">
    <WritingWorkspace training owned :row="row" :blocked="blocked" :saved-at="!dirty && text ? '到本机' : ''"
      @answer="emit('edit', $event)" @save="emit('save')" @submit="emit('submit')" />
    <p v-if="feedbackError" role="status">暂时无法读取稿件与批改反馈。</p>
    <slot v-if="submitted" name="continue" />
  </section>
</template>
