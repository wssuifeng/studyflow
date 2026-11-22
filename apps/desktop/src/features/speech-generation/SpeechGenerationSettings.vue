<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, reactive, shallowRef} from 'vue'
import {engineCall, EngineError} from '../../shared/api'
import {windowStorageKey} from '../../shared/ui'

interface Settings {
  profile_id: string; name: string; provider: 'step_plan' | 'compatible'; endpoint: string; model: string; voice: string
  format: 'mp3' | 'wav'; version: number; has_credential: boolean
}
interface Job {job_id: string; profile_id?: string; status: string; duration?: number; message?: string; completed_segments?: number; total_segments?: number}
interface Adopted {audio: {sha256: string; format: string}; relative_path: string; duration: number}

const settings = shallowRef<Settings>()
const profiles = shallowRef<Settings[]>([])
const form = reactive({name: '', provider: 'step_plan' as Settings['provider'], endpoint: '', model: '', voice: '', format: 'mp3' as Settings['format']})
const key = shallowRef('')
const script = shallowRef('')
const segments = reactive<{id: string; text: string; voice: string}[]>([])
const hasScript = computed(() => segments.length ? segments.every(segment => segment.text.trim()) : !!script.value.trim())
const instruction = shallowRef('')
const job = shallowRef<Job>()
const adopted = shallowRef<Adopted>()
const audioUrl = shallowRef('')
const busy = shallowRef('')
const error = shallowRef('')
const status = shallowRef('')
const receiptRequest = shallowRef<JobRequest>()
const receiptKey = windowStorageKey('speech-last-job')
const profileDirty = computed(() => !settings.value || !!key.value || (Object.keys(form) as (keyof typeof form)[]).some(field => form[field] !== settings.value?.[field]))
const requestEndpoint = computed(() => form.provider === 'step_plan'
  ? 'https://api.stepfun.com/step_plan/v1/audio/speech' : form.endpoint)
const jobProfileName = computed(() => profiles.value.find(profile => profile.profile_id === job.value?.profile_id)?.name)
const adoptedReference = computed(() => adopted.value ? JSON.stringify(adopted.value.audio) : '')
let timer: ReturnType<typeof setTimeout> | undefined
let disposed = false
let autoPreview = false
interface JobRequest {
  job_id: string; profile_id: string; expected_profile_version: number; text?: string
  segments?: {text: string; voice: string | null}[]; instruction: string | null
}
let unconfirmed: JobRequest | undefined

function readProfile(value: Settings) {
  settings.value = value
  const {provider, endpoint, model, voice, format, name} = value
  Object.assign(form, {provider, endpoint, model, voice, format, name})
  key.value = ''
}
async function action(name: string, run: () => Promise<void>) {
  if (busy.value) return
  busy.value = name
  error.value = ''
  try {await run()} catch (cause) {error.value = cause instanceof Error ? cause.message : '语音操作未完成。'}
  finally {busy.value = ''}
}
async function load() {
  await action('load', async () => {
    profiles.value = (await engineCall<{profiles: Settings[]}>('speech.profile.list')).profiles
    readProfile(profiles.value[0]!)
  })
}
function switchProfile(id: string) {
  if (id === 'new') {
    readProfile({profile_id: crypto.randomUUID(), name: '', provider: 'compatible', endpoint: '', model: '', voice: '',
      format: 'mp3', has_credential: false, version: 0})
    return
  }
  const selected = profiles.value.find(value => value.profile_id === id)
  if (selected) readProfile(selected)
}
function addSegment() {
  if (segments.length === 0) segments.push({id: crypto.randomUUID(), text: script.value, voice: ''})
  if (segments.length < 10) segments.push({id: crypto.randomUUID(), text: '', voice: ''})
}
async function save(clear = false) {
  if (!settings.value) return
  await action('save', async () => {
    readProfile(await engineCall<Settings>('speech.profile.save', {...form, credential: !clear && key.value || null,
      clear_credential: clear, profile_id: settings.value!.profile_id, expected_version: settings.value!.version}))
    profiles.value = (await engineCall<{profiles: Settings[]}>('speech.profile.list')).profiles
    key.value = ''
    status.value = clear ? '已清除 API Key。' : '配置已保存。生成音频后可试听。'
  })
}
function resetAudio() {
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audioUrl.value = ''
}
async function poll(jobId: string) {
  clearTimeout(timer)
  try {
    const next = await engineCall<Job>('speech.job.get', {job_id: jobId})
    if (disposed || job.value?.job_id !== jobId) return
    job.value = next
    if (next.status === 'running') {
      status.value = `生成中，已完成 ${next.completed_segments ?? 0} / ${next.total_segments ?? 1} 段。`
      timer = setTimeout(() => void poll(jobId), 800)
    }
    else if (next.status === 'ready') {
      status.value = `已生成 ${next.duration} 秒音频。`
      if (autoPreview) {
        autoPreview = false
        await preview()
      }
    }
    else status.value = next.message || '生成未完成。'
  } catch (cause) {
    if (!disposed) error.value = cause instanceof Error ? cause.message : '读取任务失败。'
  }
}
async function launch(request: JobRequest, retry = false, test = false) {
  await action('generate', async () => {
    clearTimeout(timer)
    autoPreview = test
    adopted.value = undefined
    resetAudio()
    unconfirmed = request
    try {localStorage.setItem(receiptKey, JSON.stringify(request))} catch {}
    try {
      job.value = await engineCall<Job>('speech.job.start', {...request, retry})
      receiptRequest.value = request
      status.value = '正在读取生成任务…'
      unconfirmed = undefined
      void poll(job.value.job_id)
    } catch (cause) {
      if (cause instanceof EngineError && ['KEY_REQUIRED','VERSION_CONFLICT','SPEECH_BUSY','INVALID_ARGUMENT','IDEMPOTENCY_KEY_CONFLICT'].includes(cause.code)) {
        unconfirmed = undefined
        try {
          if (receiptRequest.value) localStorage.setItem(receiptKey, JSON.stringify(receiptRequest.value))
          else localStorage.removeItem(receiptKey)
        } catch {}
      }
      throw cause
    }
  })
}
async function generate(test = false) {
  if (!settings.value) return
  const request: JobRequest = unconfirmed ?? {
    job_id: crypto.randomUUID(), profile_id: settings.value.profile_id, expected_profile_version: settings.value.version,
    instruction: instruction.value.trim() || null, ...(test ? {text: 'Please bring your ticket and a jacket.'} :
      segments.length ? {segments: segments.map(segment => ({text: segment.text, voice: segment.voice.trim() || null}))} : {text: script.value}),
  }
  await launch(request, false, test)
}
async function preview() {
  if (!job.value) return
  await action('preview', async () => {
    const audio = await engineCall<{data: string; mime: string}>('speech.job.preview', {job_id: job.value!.job_id})
    if (disposed) return
    resetAudio()
    audioUrl.value = URL.createObjectURL(new Blob([Uint8Array.from(atob(audio.data), character => character.charCodeAt(0))], {type: audio.mime}))
  })
}
async function adopt() {
  if (!job.value) return
  await action('adopt', async () => {
    adopted.value = await engineCall<Adopted>('speech.asset.adopt', {job_id: job.value!.job_id})
    status.value = '音频已保存到工作区，可以将引用加入课程包。'
  })
}
async function copyReference() {
  try {await navigator.clipboard.writeText(adoptedReference.value); status.value = '已复制音频引用。'}
  catch {error.value = '无法访问剪贴板。可以从引用框手动复制。'}
}
onMounted(async () => {
  await load()
  try {
    const cached = localStorage.getItem(receiptKey)
    if (!cached || disposed) return
    const request = JSON.parse(cached) as JobRequest
    if (!request.job_id) return
    receiptRequest.value = request
    script.value = request.text || ''
    instruction.value = request.instruction || ''
    if (request.segments) segments.push(...request.segments.map(segment => ({...segment, voice: segment.voice || '', id: crypto.randomUUID()})))
    switchProfile(request.profile_id)
    job.value = {job_id: request.job_id, status: 'loading'}
    void poll(request.job_id)
  } catch { /* A stale local receipt does not prevent editing a profile. */ }
})
onBeforeUnmount(() => {disposed = true; clearTimeout(timer); resetAudio()})
</script>

<template>
  <section class="workspace-panel speech-settings" aria-label="语音生成">
    <h3>语音生成</h3>
    <p>用配置的服务生成课程音频。采用后，学习者可以离线播放。</p>
    <div v-if="settings" class="management-controls">
      <label class="field-label">语音服务<select :value="settings.profile_id" :disabled="!!busy" @change="switchProfile(($event.target as HTMLSelectElement).value)">
        <option v-for="profile in profiles" :key="profile.profile_id" :value="profile.profile_id">{{ profile.name }}</option>
        <option v-if="!profiles.some(profile => profile.profile_id === settings?.profile_id)" :value="settings.profile_id">新配置</option>
        <option value="new">添加服务</option>
      </select></label>
    </div>
    <form v-if="settings" class="speech-fields" @submit.prevent="save()">
      <label class="field-label">服务名称<input v-model.trim="form.name" required maxlength="160" /></label>
      <label class="field-label">接入方式<select v-model="form.provider"><option value="step_plan">阶跃星辰 · Step Plan</option><option value="compatible">兼容 Audio Speech 接口</option></select></label>
      <label v-if="form.provider === 'compatible'" class="field-label">完整接口地址<input v-model.trim="form.endpoint" required maxlength="500" placeholder="https://…/v1/audio/speech" /></label>
      <p v-if="requestEndpoint" class="speech-endpoint muted small">请求地址 <code>{{ requestEndpoint }}</code></p>
      <label class="field-label">模型<input v-model.trim="form.model" required maxlength="160" /></label>
      <label class="field-label">音色 ID<input v-model.trim="form.voice" required maxlength="160" /></label>
      <label class="field-label">文件格式<select v-model="form.format"><option value="mp3">MP3</option><option value="wav">WAV</option></select></label>
      <label class="field-label">API Key<input v-model="key" type="password" maxlength="500" autocomplete="new-password"
        :placeholder="settings.has_credential ? '已保存，留空保留当前 Key' : '输入当前服务的 API Key'" /></label>
      <div class="management-controls"><button type="submit" class="secondary-button" :disabled="!!busy || !profileDirty">保存配置</button>
        <button v-if="settings.has_credential" type="button" class="text-button" :disabled="!!busy" @click="save(true)">清除 Key</button></div>
    </form>
    <button v-else type="button" class="secondary-button" :disabled="!!busy" @click="load">读取配置</button>
    <div v-if="settings" class="speech-editor">
      <h4>生成课程音频</h4>
      <label v-if="!segments.length" class="field-label">台词<textarea v-model="script" rows="5" maxlength="1200" placeholder="输入本段音频的台词" /></label>
      <fieldset v-for="(segment, index) in segments" :key="segment.id" class="speech-segment">
        <legend>第 {{ index + 1 }} 段</legend>
        <label class="field-label">台词<textarea v-model="segment.text" rows="2" maxlength="1200" /></label>
        <label class="field-label">音色覆盖<input v-model.trim="segment.voice" maxlength="160" placeholder="留空使用配置音色" /></label>
        <button type="button" class="text-button" @click="segments.splice(index, 1)">移除本段</button>
      </fieldset>
      <button type="button" class="text-button" :disabled="segments.length >= 10 || job?.status === 'running'" @click="addSegment">添加对话段</button>
      <p v-if="segments.length > 1 && form.format !== 'wav'" class="muted small">多段对话请选择 WAV 并保存配置。</p>
      <label class="field-label">朗读要求（可选）<input v-model="instruction" maxlength="500" placeholder="例如使用清晰的英文发音，语速适中" /></label>
      <p v-if="jobProfileName" class="muted small">当前任务使用 {{ jobProfileName }}</p>
      <div class="management-controls">
        <button type="button" class="primary-button" :disabled="!!busy || job?.status === 'running' || !settings.has_credential || profileDirty || !hasScript || segments.length > 1 && form.format !== 'wav'" @click="generate()">生成音频</button>
        <button type="button" class="secondary-button" :disabled="!!busy || job?.status === 'running' || !settings.has_credential || profileDirty" @click="generate(true)">测试并试听</button>
        <button v-if="job && !['ready','failed','interrupted'].includes(job.status)" type="button" class="text-button" @click="poll(job.job_id)">刷新任务</button>
        <button v-if="job?.status === 'ready'" type="button" class="secondary-button" :disabled="!!busy" @click="preview">试听成品</button>
        <button v-if="receiptRequest && ['failed','interrupted'].includes(job?.status || '')" type="button" class="secondary-button" :disabled="!!busy" @click="launch(receiptRequest, true)">重试未完成段</button>
        <button v-if="job?.status === 'ready'" type="button" class="secondary-button" :disabled="!!busy" @click="adopt">采用为课程音频</button>
      </div>
      <audio v-if="audioUrl" :src="audioUrl" controls autoplay aria-label="合成音频试听" @error="error = '无法解码这段音频。'" />
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="status" role="status">{{ status }}</p>
    <div v-if="adopted"><p class="workspace-path">{{ adopted.relative_path }}</p><label class="field-label">课程包的 audio 引用<input readonly :value="adoptedReference" /></label>
      <button type="button" class="text-button" @click="copyReference">复制引用</button></div>
  </section>
</template>

<style scoped>
.speech-fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 10px 18px; }
.speech-fields .management-controls, .speech-endpoint { grid-column: 1 / -1; }
.speech-endpoint { overflow-wrap: anywhere; }
.speech-segment { border: 1px solid var(--theme-border-subtle); margin: 10px 0; padding: 10px; }
.speech-editor { margin-top: 20px; border-top: 1px solid var(--theme-border-subtle); }
.speech-settings textarea, .speech-settings select { width: 100%; color: inherit; background: var(--theme-surface-input); border: 1px solid var(--theme-border-subtle); padding: 8px; }
.speech-settings audio { width: min(100%, 480px); margin-top: 12px; }
</style>
