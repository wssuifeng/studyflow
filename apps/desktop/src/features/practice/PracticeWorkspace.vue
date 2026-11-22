<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, onMounted, shallowRef, useTemplateRef} from 'vue'
import ListeningPlayer from './ListeningPlayer.vue'
import {windowStorageKey} from '../../shared/ui'
import {usePractice, type AuthorPreviewContext} from './usePractice'

const props = defineProps<{studyId: string; exerciseId: string; kind: 'reading' | 'listening'; blocked: boolean; training?: boolean; preview?: AuthorPreviewContext}>()
const emit = defineEmits<{back: []; confirmed: [submitted: boolean]}>()
const {view, draft, pending, busy, error, conflict, dirty, load, save, select, move} =
  usePractice(props.studyId, props.exerciseId, props.kind, submitted => emit('confirmed', submitted), props.preview)
const title = useTemplateRef<HTMLHeadingElement>('title')
const questionTitle = useTemplateRef<HTMLHeadingElement>('questionTitle')
const passage = useTemplateRef<HTMLElement>('passage')
const review = useTemplateRef<HTMLElement>('review')
const activeEvidence = shallowRef('')
const onlyIncorrect = shallowRef(false)
const workspace = useTemplateRef<HTMLElement>('workspace')
const readPositionKey = windowStorageKey(`passage-scroll:${props.studyId}:${props.exerciseId}`)
const question = computed(() => view.value?.questions[draft.value.position])
const answer = computed(() => question.value ? draft.value.answers[question.value.id] : undefined)
const blanks = computed<Record<string,string>>(() => typeof answer.value === 'object' ? answer.value : {})
const locked = computed(() => !!view.value?.result || props.blocked || busy.value || !!pending.value || conflict.value || !!view.value?.read_only)
const last = computed(() => draft.value.position + 1 === view.value?.questions.length)
const complete = computed(() => !!view.value?.questions.every(item => {
  const value = draft.value.answers[item.id]
  return item.options ? typeof value === 'string' && !!value : typeof value === 'object' &&
    item.parts?.every(part => !('blank_id' in part) || !!value[part.blank_id]?.trim())
}))
const result = computed(() => view.value?.result?.items[draft.value.position])
const visibleQuestions = computed(() => (view.value?.questions ?? []).map((item, index) => ({item, index}))
  .filter(({index}) => !onlyIncorrect.value || !view.value?.result?.items[index]?.correct))
const blankScore = computed(() => {
  const entries = view.value?.result?.items.flatMap(item => item.blanks ?? []) ?? []
  return {total: entries.length, correct: entries.filter(entry => entry.correct).length}
})
const firstUnanswered = computed(() => view.value?.questions.findIndex(item => {
  const value = draft.value.answers[item.id]
  return item.options ? !value : item.parts?.some(part => 'blank_id' in part && (typeof value !== 'object' || !value[part.blank_id]?.trim()))
}) ?? -1)

onMounted(async () => {
  await load()
  await nextTick()
  title.value?.focus()
  try {if (passage.value) passage.value.scrollTop = Number(localStorage.getItem(readPositionKey)) || 0} catch {}
})
function savePassagePosition() {
  if (passage.value) {
    try {localStorage.setItem(readPositionKey, String(passage.value.scrollTop))} catch {}
  }
}
onBeforeUnmount(savePassagePosition)

async function go(position: number) {
  activeEvidence.value = ''
  move(position)
  if (!view.value?.read_only) await save()
  await nextTick()
  questionTitle.value?.focus({preventScroll: true})
}

async function advance() {
  if (locked.value || !question.value) return
  if (last.value && complete.value) {
    if (await save(true)) await nextTick().then(() => review.value?.focus())
    return
  }
  if (!last.value && firstUnanswered.value !== draft.value.position && answer.value &&
    !workspace.value?.querySelector('.practice-cloze input[data-empty="true"]')) {
    await go(draft.value.position + 1)
    return
  }
  if (last.value && firstUnanswered.value >= 0 && firstUnanswered.value !== draft.value.position) {
    await go(firstUnanswered.value)
  }
  const missing = workspace.value?.querySelector<HTMLElement>('.practice-cloze input[data-empty="true"], .option-set input')
  missing?.focus()
}

function toggleIncorrect() {
  onlyIncorrect.value = !onlyIncorrect.value
  if (onlyIncorrect.value && result.value?.correct && visibleQuestions.value.length) void go(visibleQuestions.value[0]!.index)
}

function navigateResult(direction: number) {
  const current = visibleQuestions.value.findIndex(item => item.index === draft.value.position)
  const destination = visibleQuestions.value[current + direction]
  if (destination) void go(destination.index)
}

function focusPassage() {passage.value?.focus(); passage.value?.scrollIntoView({block: 'nearest'})}
function focusQuestion() {questionTitle.value?.focus(); questionTitle.value?.scrollIntoView({block: 'nearest'})}

function onBlankKey(event: KeyboardEvent) {
  if (event.isComposing || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
  const input = event.target as HTMLInputElement
  if (input.selectionStart !== input.selectionEnd) return
  const offset = event.key === 'ArrowLeft' && input.selectionStart === 0 ? -1 :
    event.key === 'ArrowRight' && input.selectionEnd === input.value.length ? 1 : 0
  if (!offset) return
  const items = Array.from(workspace.value?.querySelectorAll<HTMLInputElement>('.practice-cloze input') ?? [])
  const target = items[items.indexOf(input) + offset]
  if (!target) return
  event.preventDefault()
  target.focus()
  const caret = offset === -1 ? target.value.length : 0
  target.setSelectionRange(caret, caret)
}

function onKey(event: KeyboardEvent) {
  if (event.isComposing || event.repeat || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey || locked.value || !(event.target instanceof HTMLInputElement)) return
  if (event.key === 'Enter') {event.preventDefault(); void advance()}
}

function goToEvidence(id: string) {
  activeEvidence.value = id
  const paragraph = Array.from(passage.value?.querySelectorAll<HTMLElement>('[data-paragraph]') || []).find(item => item.dataset.paragraph === id)
  paragraph?.scrollIntoView({block: 'nearest'})
  paragraph?.focus({preventScroll: true})
}

async function back() {if (await save()) emit('back')}
function exportDraft() {
  const URLvalue = URL.createObjectURL(new Blob([JSON.stringify(draft.value.answers, null, 2)], {type: 'application/json'}))
  const link = document.createElement('a')
  link.href = URLvalue
  link.download = 'StudyFlow-题组草稿.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(URLvalue), 1000)
}
defineExpose({save, busy, dirty, exportDraft, ready: computed(() => !!view.value), confirmed: computed(() => !!view.value?.result), hasProblem: computed(() => !!pending.value || conflict.value || !!error.value && dirty.value)})
</script>

<template>
  <section ref="workspace" class="practice-workspace" :class="{'in-training': training}" aria-label="题组练习" @keydown="onKey">
    <header class="practice-bar">
      <button v-if="!training" type="button" class="text-button" :disabled="busy" @click="back">{{ preview ? '‹ 退出预览' : '‹ 返回知识点' }}</button>
      <h3 ref="title" tabindex="-1">{{ view?.title ?? (kind === 'reading' ? '阅读练习' : '听力练习') }}</h3>
      <span v-if="view?.result" role="status">答对 {{ view.result.correct }} / {{ view.result.total }} 题</span>
      <span v-if="blankScore.total">补全答对 {{ blankScore.correct }} / {{ blankScore.total }} 空</span>
      <button v-if="view?.result" type="button" class="text-button" :aria-pressed="onlyIncorrect" @click="toggleIncorrect">{{ onlyIncorrect ? '看全部题' : '仅看错题' }}</button>
    </header>
    <p v-if="onlyIncorrect && !visibleQuestions.length" role="status">本组全部答对。</p>
    <div v-if="error" class="practice-error" role="alert">
      <p>{{ error }}</p>
      <button v-if="!view" type="button" @click="load()">重新读取</button>
      <button v-else-if="!conflict" type="button" @click="save()">重试保存</button>
      <template v-else><button type="button" @click="exportDraft">导出本机输入</button><button type="button" @click="load(false)">使用工作区版本</button></template>
    </div>
    <p v-if="!view && busy" role="status">正在读取题组…</p>
    <div v-if="view && question && visibleQuestions.length" class="practice-layout" :class="{ 'with-passage': view.paragraphs }">
      <article v-if="view.paragraphs" ref="passage" class="practice-passage" aria-label="阅读原文" tabindex="0">
        <button type="button" class="text-button" @click="focusQuestion">返回第 {{ draft.position + 1 }} 题</button>
        <p v-for="paragraph in view.paragraphs" :key="paragraph.id" :data-paragraph="paragraph.id" tabindex="-1"
          :class="{ evidence: paragraph.id === activeEvidence }">{{ paragraph.text }}
          <button v-if="paragraph.id === activeEvidence" type="button" class="text-button" @click="review?.focus()">返回解析</button>
        </p>
      </article>
      <div class="practice-questions">
        <ListeningPlayer v-if="view.audio" :key="view.audio.sha256" :study-id="studyId"
          :exercise-id="exerciseId" :preview="preview" />
        <button v-if="view.paragraphs" type="button" class="text-button" @click="focusPassage">回到文章</button>
        <nav class="practice-index" aria-label="题号">
          <button v-for="{item, index} in visibleQuestions" :key="item.id" type="button" class="practice-index-button" :disabled="busy || !!pending || conflict"
            :aria-current="index === draft.position ? 'step' : undefined" :data-answered="!!draft.answers[item.id]"
            :aria-label="`第 ${index + 1} 题${draft.answers[item.id] ? '，已填写' : ''}`" @click="go(index)">{{ index + 1 }}</button>
        </nav>
        <h4 ref="questionTitle" tabindex="-1">{{ question.prompt }}</h4>
        <fieldset v-if="question.options" :disabled="locked" class="option-set">
          <legend class="practice-sr-only">选择一个答案</legend>
          <label v-for="(option, index) in question.options" :key="option.id" class="practice-option" :class="{selected: answer === option.id}">
            <input type="radio" :name="`${exerciseId}-${question.id}`" :checked="answer === option.id" @change="select(question.id, option.id)" />
            <span>{{ String.fromCharCode(65 + index) }}. {{ option.text }}</span>
          </label>
        </fieldset>
        <p v-else-if="question.parts" class="practice-cloze">
          <template v-for="(part, index) in question.parts" :key="index">
            <span v-if="'text' in part">{{ part.text }}</span>
            <input v-else type="text" :aria-label="`填空 ${question.parts.slice(0, index + 1).filter(p => 'blank_id' in p).length}`"
              :value="blanks[part.blank_id] || ''" :data-empty="!blanks[part.blank_id]?.trim()" :disabled="locked" @keydown="onBlankKey" maxlength="120" autocomplete="off" autocapitalize="off" spellcheck="false" lang="en"
              @input="select(question.id, {...blanks, [part.blank_id]: ($event.target as HTMLInputElement).value})" />
          </template>
        </p>
        <section v-if="result" ref="review" class="practice-result" tabindex="-1" aria-label="本题解析">
          <strong>{{ result.correct ? '回答正确' : '回答有误' }}</strong>
          <p v-if="result.correct_option_id">正确答案：{{ question.options?.find(option => option.id === result?.correct_option_id)?.text }}</p>
          <ol v-if="result.blanks"><li v-for="blank in result.blanks" :key="blank.id">{{ blanks[blank.id] }} → {{ blank.accepted }} · {{ blank.correct ? '正确' : '有误' }}</li></ol>
          <p>{{ result.explanation }}</p>
          <button v-for="id in result.evidence" :key="id" type="button" class="text-button" @click="goToEvidence(id)">查看第 {{ (view.paragraphs?.findIndex(p => p.id === id) ?? -1) + 1 }} 段依据</button>
          <details v-if="view.transcript"><summary>查看听力原文</summary><p>{{ view.transcript }}</p></details>
        </section>
        <footer class="practice-bar">
          <template v-if="view.result">
            <button type="button" class="secondary-button" :disabled="visibleQuestions[0]?.index === draft.position" @click="navigateResult(-1)">上一题</button>
            <button type="button" class="secondary-button" :disabled="visibleQuestions.at(-1)?.index === draft.position" @click="navigateResult(1)">下一题</button>
          </template>
          <template v-else>
            <button type="button" class="secondary-button" :disabled="draft.position === 0 || busy || !!pending || conflict" @click="go(draft.position - 1)">上一题</button>
            <button v-if="!view.read_only" type="button" class="primary-button" :disabled="locked" @click="advance">{{ last ? '确认' : '下一题' }}</button>
          </template>
        </footer>
        <p v-if="last && !complete && !view.read_only" class="muted small">确认前请完成本组所有题目。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.practice-workspace { container-type: inline-size; min-width: 0; overflow: auto; max-height: var(--study-height, 80vh); padding: clamp(16px, 3vw, 32px); color: var(--theme-text-primary); background: var(--theme-surface-panel); }
.practice-workspace.in-training { max-height: none; overflow: visible; padding: 0; background: transparent; }
.practice-bar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; justify-content: space-between; margin-block: 12px; }
.practice-bar h3 { margin: 0; }
.practice-layout { display: grid; grid-template-columns: minmax(0,1fr); gap: clamp(12px,2vw,20px); }
.practice-passage, .practice-questions { min-width: 0; }
.practice-passage { scrollbar-gutter: stable; background: var(--theme-surface-input); max-height: min(35vh, 420px); overflow: auto; padding: 0 14px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; }
@container (min-width: 620px) {
  .with-passage { grid-template-columns: minmax(0,1.12fr) minmax(0,1fr); }
  .practice-passage, .with-passage .practice-questions { max-height: min(65vh,700px); }
  .with-passage .practice-questions { overflow: auto; padding-inline: 4px; scrollbar-gutter: stable; }
}
.practice-passage p, .practice-result p { white-space: pre-wrap; line-height: 1.75; overflow-wrap: anywhere; }
.evidence, .practice-option.selected { background: var(--theme-status-info-soft); }
.practice-index { display: flex; gap: 6px; flex-wrap: wrap; margin-block-end: 14px; }
.practice-workspace .practice-index button.practice-index-button { min-width: 36px; min-height: 34px; padding: 5px 8px; border: 1px solid var(--theme-border-subtle); border-radius: 7px; font-variant-numeric: tabular-nums; }
.practice-workspace .practice-index button[aria-current='step'] { border-color: var(--theme-accent-primary); background: var(--theme-accent-soft); color: var(--theme-accent-primary); }
.practice-workspace .practice-index button[data-answered='true'] { color: var(--theme-accent-primary); font-weight: 650; }
.practice-option.selected { border-color: var(--theme-accent-primary); }
.option-set { border: none; padding: 0; margin: 12px 0; display: grid; gap: 8px; min-width: 0; }
.practice-option { display: flex; align-items: flex-start; gap: 10px; padding: 12px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; overflow-wrap: anywhere; }
.practice-option:not(.selected):hover, .practice-option:not(.selected):focus-within { border-color: var(--theme-border-strong); }
.practice-option input { flex: none; accent-color: var(--theme-accent-primary); }
.practice-cloze { line-height: 2.5; white-space: pre-wrap; }
.practice-cloze input { width: min(18ch, 70%); min-height: 32px; margin-inline: 4px; padding-inline: 8px; color: inherit; background: var(--theme-surface-input); border: 1px solid var(--theme-border-subtle); border-radius: 6px; }
.practice-cloze input:focus { border-color: var(--theme-accent-primary); }
.practice-workspace :is(.practice-index, footer) button { transition: none; }
.practice-result, .practice-error { padding: 12px; border: 1px solid var(--theme-border-subtle); border-radius: 8px; }
.practice-sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
</style>
