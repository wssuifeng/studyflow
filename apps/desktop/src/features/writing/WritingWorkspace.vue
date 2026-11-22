<script setup lang="ts">
import {computed, nextTick, onMounted, shallowRef, useTemplateRef, watch} from 'vue'
import {studyApi} from '../../shared/api'
import type {SubmissionDetailData} from '../../shared/api/contracts'
import type {AnswerRow} from '../learning/composables/useCourseAnswers'
import {statusLabel, reportError} from '../../shared/ui'

const props = defineProps<{row: Pick<AnswerRow, 'title'|'prompt'|'requirements'|'essay'|'answer'|'savedAnswer'|'action'|'submission'|'draft'>; blocked: boolean; owned: boolean; savedAt: string; training?: boolean}>()
const emit = defineEmits<{answer: [value: string]; back: []; save: []; submit: []}>()
const editor = useTemplateRef<HTMLTextAreaElement>('editor')
const heading = useTemplateRef<HTMLHeadingElement>('heading')
const draft = shallowRef<SubmissionDetailData | null>(null)
const loadingHistory = shallowRef(false)
const revising = shallowRef(false)
const wordCount = computed(() => props.row.answer.match(/[A-Za-z]+(?:['’\-][A-Za-z]+)*/g)?.length ?? 0)
const editable = computed(() => props.owned && (props.row.action === 'FIRST' || props.row.action === 'RETEST' || props.row.action === 'REVISION' && revising.value))
const feedback = computed(() => draft.value ?? props.row.submission)
const historical = computed(() => !!draft.value && draft.value.id !== props.row.submission?.id)
const storageHint = computed(() => props.row.answer !== props.row.savedAnswer ? '有待保存的修改' : props.savedAt ? `已保存 ${props.savedAt}` : props.row.draft ? '已恢复草稿' : '')

watch(() => props.row.submission?.id, () => {draft.value = null; revising.value = false})
onMounted(() => heading.value?.focus())
async function showDraft(id: string) {
  loadingHistory.value = true
  try {draft.value = id === props.row.submission?.id ? null : await studyApi.submission(id)}
  catch (cause) {reportError(cause)}
  finally {loadingHistory.value = false}
}
async function revise() {
  revising.value = true
  await nextTick()
  editor.value?.focus()
}
function editHistory(command: 'undo' | 'redo') {
  editor.value?.focus()
  document.execCommand(command)
  if (editor.value) emit('answer', editor.value.value)
}
function submit() {
  if (props.blocked) return
  if (!props.row.answer.trim()) {editor.value?.focus(); return}
  emit('submit')
}
</script>

<template>
  <section class="writing-workspace" :class="{'in-training': training}" aria-label="作文练习">
    <header>
      <button v-if="!training" class="text-button" type="button" @click="emit('back')">‹ 返回知识点</button>
      <h3 ref="heading" tabindex="-1">{{ row.title }}</h3>
      <details class="writing-topic" open>
        <summary>题干与写作要求</summary>
        <p class="writing-prompt">{{ row.prompt }}</p>
        <p v-if="row.requirements" class="writing-prompt">{{ row.requirements }}</p>
        <p v-if="row.essay?.suggested_words">建议 {{ row.essay.suggested_words[0] }}–{{ row.essay.suggested_words[1] }} 词</p>
        <ul v-if="row.essay?.points?.length"><li v-for="(point, index) in row.essay.points" :key="index">{{ point }}</li></ul>
      </details>
    </header>
    <p v-if="!owned" role="status">请先将独立练习窗口停靠回课程，再编辑作文。</p>
    <div v-if="editable && !historical" class="writing-editor">
      <div class="writing-tools">
        <label for="writing-content">{{ row.action === 'REVISION' ? '修订稿' : '正文' }}</label>
        <button class="text-button" type="button" :disabled="blocked" @click="editHistory('undo')">撤销</button>
        <button class="text-button" type="button" :disabled="blocked" @click="editHistory('redo')">重做</button>
        <span class="muted">{{ wordCount }} 词</span>
      </div>
      <textarea id="writing-content" ref="editor" :value="row.answer" :readonly="blocked" rows="18" maxlength="100000" lang="en" spellcheck="false"
        placeholder="在这里写作文" @input="emit('answer', ($event.target as HTMLTextAreaElement).value)" />
      <div class="writing-tools"><span class="muted" role="status">{{ storageHint }}</span>
        <button class="secondary-button" type="button" :disabled="blocked" @click="emit('save')">保存草稿</button>
        <button class="primary-button" type="button" :disabled="blocked" @click="submit">提交作文</button>
      </div>
    </div>
    <p v-else-if="training && !feedback && row.action === 'LOCKED'" role="status">作文已提交。</p>
    <section v-if="feedback" class="writing-feedback" aria-label="作文稿次与反馈">
      <div class="writing-tools"><h4>第 {{ feedback.attempt_number }} 稿 · {{ statusLabel(feedback.status) }}</h4>
        <button v-if="feedback.parent" class="text-button" type="button" :disabled="loadingHistory" @click="showDraft(feedback.parent.id)">查看上一稿</button>
        <button v-if="historical && row.submission" class="text-button" type="button" @click="draft = null">返回当前稿</button>
        <button v-if="!historical && !revising && row.action === 'REVISION' && owned" class="secondary-button" type="button" :disabled="blocked" @click="revise">按反馈修订</button>
      </div>
      <pre class="writing-copy">{{ feedback.answer_text }}</pre>
      <article v-for="item in feedback.reviews" :key="item.id" class="writing-review">
        <h5>{{ item.summary }}</h5>
        <div class="markdown-body" v-html="item.rendered_html" />
        <div v-for="(issue, index) in item.issues" :key="index"><blockquote>{{ issue.quote }}</blockquote><p>{{ issue.reason }}</p><p>{{ issue.guidance }}</p></div>
        <p v-if="item.next_action">{{ item.next_action }}</p>
      </article>
    </section>
  </section>
</template>

<style scoped>
.writing-workspace { max-height: var(--study-height, 80vh); min-width: 0; overflow: auto; padding: clamp(16px, 3vw, 36px); color: var(--theme-text-primary); background: var(--theme-surface-panel); }
.writing-workspace.in-training { max-height: none; overflow: visible; padding: 0; background: transparent; }
.writing-prompt, .writing-copy { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.65; }
.writing-prompt { margin-block: 8px 0; max-width: 70ch; }
.writing-editor, .writing-feedback { margin: 18px 0 0; max-width: 76ch; }
.writing-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; padding-block: 8px; }
.writing-tools .muted { margin-inline-end: auto; font-variant-numeric: tabular-nums; }
.writing-editor textarea { width: 100%; display: block; min-height: clamp(190px, 34vh, 340px); resize: vertical; padding: 14px 16px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; color: inherit; background: var(--theme-surface-input); font: inherit; line-height: 1.75; }
.writing-copy { padding: 16px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; font: inherit; }
.writing-review { padding-block: 12px; border-top: 1px solid var(--theme-border-subtle); overflow-wrap: anywhere; }
</style>
