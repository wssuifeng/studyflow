<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { studyApi } from '../bridge'
import type { ExerciseSubmission, LessonDetail } from '../types'
import { makeRequestKey, navigate, notify, reportError, statusLabel, storageKey } from '../ui'
const props = defineProps<{ exercise: LessonDetail['exercises'][number] }>()
const emit = defineEmits<{ changed: [] }>()
const draft = ref<ExerciseSubmission | null>(props.exercise.draft)
const formal = ref<ExerciseSubmission | null>(props.exercise.latest_submission)
const answer = ref('')
const savedAnswer = ref('')
const loading = ref(true)
const busy = ref('')
const loadFailed = ref(false)
const savedAt = ref('')
const recoveryAvailable = ref(false)
const pending = ref<{operation: string; params: Record<string, unknown>} | null>(null)
const dirty = computed(() => answer.value !== savedAnswer.value)
const locked = computed(() => !draft.value && !!formal.value)
const bufferKey = storageKey('answer:' + props.exercise.id)
const requestKey = storageKey('request:' + props.exercise.id)

async function load() {
  loading.value = true; loadFailed.value = false
  try {
    const row = draft.value || formal.value
    if (row) {
      const detail = await studyApi.submission(row.id)
      answer.value = detail.answer_text; savedAnswer.value = detail.answer_text
      if (detail.status === 'DRAFT') draft.value = detail
      else { formal.value = detail; draft.value = null }
    }
    const buffer = localStorage.getItem(bufferKey)
    recoveryAvailable.value = !locked.value && buffer !== null && buffer !== answer.value
    const request = localStorage.getItem(requestKey)
    if (request) { try { pending.value = JSON.parse(request) } catch { localStorage.removeItem(requestKey) } }
  } catch (cause) { loadFailed.value = true; reportError(cause) }
  finally { loading.value = false }
}
function recover() {
  answer.value = localStorage.getItem(bufferKey) || ''; recoveryAvailable.value = false
  notify('已恢复当前设备的临时内容，请保存到工作区。', 'info')
}
function discardRecovery() { localStorage.removeItem(bufferKey); recoveryAvailable.value = false }
watch(answer, value => { if (!loading.value && !locked.value) localStorage.setItem(bufferKey, value) })
function beforeUnload(event: BeforeUnloadEvent) { if (dirty.value && !locked.value) { event.preventDefault(); event.returnValue = '' } }
onMounted(() => { load(); window.addEventListener('beforeunload', beforeUnload) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))

async function writeAnswer(operation: 'save' | 'submit', retry = false) {
  if (busy.value || loadFailed.value || locked.value) return
  if (operation === 'submit' && !answer.value.trim()) { notify('先写下你的答案，再正式提交。', 'info'); return }
  busy.value = operation
  const params = retry && pending.value?.operation === operation ? pending.value.params : {
    exercise_id: props.exercise.id,
    answer_text: answer.value,
    ...(draft.value ? { submission_id: draft.value.id, expected_version: draft.value.version } : {}),
    idempotency_key: makeRequestKey(operation),
  }
  pending.value = { operation, params }; localStorage.setItem(requestKey, JSON.stringify(pending.value))
  try {
    const row = operation === 'save' ? await studyApi.saveDraft(params as Parameters<typeof studyApi.saveDraft>[0]) : await studyApi.submit(params as Parameters<typeof studyApi.submit>[0])
    pending.value = null; localStorage.removeItem(requestKey)
    savedAnswer.value = String(params.answer_text || ''); savedAt.value = new Date().toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'})
    if (answer.value === savedAnswer.value) localStorage.removeItem(bufferKey)
    if (operation === 'save') { draft.value = row; notify('草稿已保存到本地工作区。'); emit('changed') }
    else { formal.value = row; draft.value = null; localStorage.removeItem(bufferKey); notify('正式作答已提交，进入等待批改。'); emit('changed'); navigate('/submission/' + row.id) }
  } catch (cause) { reportError(cause) }
  finally { busy.value = '' }
}
</script>

<template>
  <div class="exercise-composer">
    <div class="exercise-title"><span class="eyebrow accent">PRACTICE</span><h3>{{ exercise.title }}</h3></div>
    <p class="exercise-prompt">{{ exercise.prompt }}</p>
    <div v-if="exercise.requirements" class="requirement-note"><strong>作答要求</strong><p>{{ exercise.requirements }}</p></div>
    <div v-if="loading" class="loading-state" role="status">正在恢复作答内容…</div>
    <div v-else-if="loadFailed" class="error-state"><p>作答未能读取，编辑已暂停。</p><button class="secondary-button" @click="load">重新读取</button></div>
    <template v-else>
      <div v-if="recoveryAvailable" class="recovery-note"><span>发现尚未保存到工作区的临时内容。</span><button class="text-button" @click="recover">恢复内容</button><button class="text-button muted" @click="discardRecovery">忽略</button></div>
      <div v-if="locked && formal" class="submitted-answer"><div class="answer-toolbar"><span :class="['status-chip', formal.status.toLowerCase()]">{{statusLabel(formal.status)}}</span><span class="muted small">第 {{formal.attempt_number}} 次作答 · 原稿只读保留</span></div><pre>{{answer}}</pre><button class="primary-button" @click="navigate('/submission/'+formal.id)">查看作答与反馈 →</button></div>
      <template v-else>
        <label class="input-label" :for="'answer-'+exercise.id">我的作答</label>
        <textarea :id="'answer-'+exercise.id" v-model="answer" :disabled="!!busy" placeholder="用自己的话说明思路，也可以贴入代码。" rows="10" spellcheck="false" />
        <div class="composer-status" aria-live="polite"><span :class="{unsaved:dirty}">{{busy ? '正在写入工作区…' : dirty ? '有未保存更改 · 临时内容仅在当前设备保留' : draft ? '草稿已保存'+(savedAt?' · '+savedAt:'') : '尚未保存'}}</span><span>{{answer.length}} 字符</span></div>
        <div v-if="pending && !busy" class="recovery-note"><span>上一次操作尚未收到确认。</span><button class="text-button" @click="writeAnswer(pending.operation as 'save'|'submit',true)">重试上次操作</button></div>
        <div class="composer-actions"><button class="secondary-button" :disabled="!!busy" @click="writeAnswer('save')">{{busy==='save'?'保存中…':'保存草稿'}}</button><button class="primary-button" :disabled="!!busy || !answer.trim()" @click="writeAnswer('submit')">{{busy==='submit'?'提交中…':'正式提交'}} <span>↗</span></button></div>
        <p class="muted small">草稿可继续编辑；正式提交后保留原答案，后续修正和复测将创建新版本。</p>
      </template>
    </template>
  </div>
</template>
