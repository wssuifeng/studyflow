<script setup lang="ts">
import {computed, onBeforeUnmount, shallowRef, useId, useTemplateRef, watch} from 'vue'
import {engineCall} from '../../shared/api'
import {windowStorageKey} from '../../shared/ui'
import type {AuthorPreviewContext} from './usePractice'

interface Caption { start: number; end: number; text: string }
type CaptionSource = {captions: Caption[]} | {transcript: string}
const props = defineProps<{studyId: string; exerciseId: string; preview?: AuthorPreviewContext}>()
const player = useTemplateRef<HTMLAudioElement>('player')
const captionPanel = useTemplateRef<HTMLDivElement>('captionPanel')
const captionId = useId()
const params = {study_session_id: props.studyId, exercise_id: props.exerciseId}
const resumeKey = windowStorageKey(`listening-time:${props.studyId}:${props.exerciseId}`)
const sourceUrl = shallowRef('')
const audioBusy = shallowRef(false)
const audioError = shallowRef('')
const captionsOpen = shallowRef(false)
const captionsBusy = shallowRef(false)
const captionsError = shallowRef('')
const captionSource = shallowRef<CaptionSource>()
const position = shallowRef(0)
const duration = shallowRef(0)
const ended = shallowRef(false)
let active = true
let lastSavedSecond = -1

const estimated = computed(() => !!captionSource.value && 'transcript' in captionSource.value)
const captions = computed(() => {
  const source = captionSource.value
  if (!source || !duration.value) return []
  if ('captions' in source) return source.captions
  const segmenter = new Intl.Segmenter('en', {granularity: 'sentence'})
  const sentences = source.transcript.split(/\r?\n/u)
    .flatMap(line => Array.from(segmenter.segment(line), segment => segment.segment.trim()))
    .filter(Boolean)
  const weights = sentences.map(sentence => sentence.split(/\s+/u).length)
  const total = weights.reduce((sum, weight) => sum + weight, 0)
  let elapsedWeight = 0
  return sentences.map((text, index) => {
    const start = duration.value * elapsedWeight / total
    elapsedWeight += weights[index]!
    return {start, end: duration.value * elapsedWeight / total, text}
  })
})
const currentCaption = computed(() => {
  if (!captionsOpen.value || ended.value || audioError.value) return undefined
  return captions.value.find(caption => caption.start <= position.value && position.value < caption.end)
})
watch(currentCaption, () => {
  if (captionPanel.value?.scrollTop) captionPanel.value.scrollTop = 0
}, {flush: 'post'})

function savePosition(force = false) {
  if (!player.value || props.preview) return
  const time = player.value.currentTime
  const second = Math.floor(time)
  if (!force && second === lastSavedSecond) return
  lastSavedSecond = second
  try {localStorage.setItem(resumeKey, String(time))} catch {}
}

function syncPlayback() {
  const element = player.value
  if (!element) return
  position.value = element.currentTime
  duration.value = Number.isFinite(element.duration) ? element.duration : 0
  ended.value = element.ended
  savePosition()
}

function resumeAudio() {
  const element = player.value
  if (!element) return
  let saved = 0
  if (!props.preview) {
    try {saved = Number(localStorage.getItem(resumeKey)) || 0} catch {}
  }
  if (saved > 0 && saved < element.duration) element.currentTime = saved
  else void element.play().catch(() => { /* Native controls remain available. */ })
  syncPlayback()
}

function replay() {
  const element = player.value
  if (!element) return
  element.currentTime = 0
  void element.play().catch(() => {})
  syncPlayback()
}

async function loadAudio() {
  if (audioBusy.value) return
  audioBusy.value = true
  audioError.value = ''
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)
  sourceUrl.value = ''
  position.value = 0
  duration.value = 0
  ended.value = false
  try {
    const asset = await engineCall<{data: string; mime: string}>(props.preview ? 'practice.author.preview' : 'practice.listening.audio',
      props.preview ? {...props.preview, audio: true} : params)
    if (!active) return
    const bytes = Uint8Array.from(atob(asset.data), char => char.charCodeAt(0))
    sourceUrl.value = URL.createObjectURL(new Blob([bytes], {type: asset.mime}))
  } catch (cause) {
    audioError.value = cause instanceof Error ? cause.message : '音频无法播放。'
  } finally {
    audioBusy.value = false
  }
}

async function loadCaptions() {
  if (captionSource.value || captionsBusy.value) return
  captionsBusy.value = true
  captionsError.value = ''
  try {
    const source = await engineCall<CaptionSource>(props.preview ? 'practice.author.preview' : 'practice.listening.captions',
      props.preview ? {...props.preview, captions: true} : params)
    if (active) captionSource.value = source
  } catch (cause) {
    captionsError.value = cause instanceof Error ? cause.message : '无法读取听力字幕。'
  } finally {
    captionsBusy.value = false
  }
}

function toggleCaptions() {
  captionsOpen.value = !captionsOpen.value
  if (captionsOpen.value) void loadCaptions()
}

onBeforeUnmount(() => {
  active = false
  savePosition(true)
  if (sourceUrl.value) URL.revokeObjectURL(sourceUrl.value)
})
</script>

<template>
  <section class="listening-player" aria-label="听力播放器">
    <div class="listening-controls">
      <audio v-if="sourceUrl" ref="player" :src="sourceUrl" controls preload="metadata" aria-label="听力材料"
        @loadedmetadata="resumeAudio" @timeupdate="syncPlayback" @seeking="syncPlayback"
        @seeked="syncPlayback" @ended="syncPlayback" @error="audioError = '音频解码失败。'" />
      <button v-else type="button" class="secondary-button" :disabled="audioBusy" @click="loadAudio">
        {{ audioBusy ? '正在加载音频…' : '播放音频' }}
      </button>
      <button type="button" class="secondary-button listening-caption-toggle" :aria-pressed="captionsOpen"
        :aria-controls="captionId" @click="toggleCaptions">
        <span class="listening-caption-icon" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
        当前句
      </button>
      <button v-if="sourceUrl" type="button" class="text-button" @click="replay">从头重听</button>
    </div>
    <div v-show="captionsOpen" :id="captionId" ref="captionPanel" class="listening-caption" tabindex="0" aria-label="听力当前句" role="group">
      <div v-if="estimated" class="listening-caption-mode">估算同步</div>
      <p v-if="captionsError" role="alert">{{ captionsError }} <button type="button" class="text-button" @click="loadCaptions">重试字幕</button></p>
      <p v-else-if="captionsBusy" role="status">正在读取字幕…</p>
      <p v-else-if="currentCaption" class="listening-caption-text" lang="en">{{ currentCaption.text }}</p>
      <p v-else class="muted">{{ audioError ? '恢复播放后显示字幕。' : !duration ? '播放音频后显示当前句。' : ended ? '音频已播放完毕。' : '等待下一句…' }}</p>
    </div>
    <p v-if="audioError" role="alert">{{ audioError }} <button type="button" class="text-button" :disabled="audioBusy" @click="loadAudio">重载音频</button></p>
  </section>
</template>

<style scoped>
.listening-player { max-inline-size: 42rem; margin-block-end: 16px; }
.listening-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.listening-controls audio { flex: 1 1 16rem; min-inline-size: min(100%, 16rem); max-inline-size: 100%; height: 42px; }
.listening-controls button { flex: 0 0 auto; min-block-size: 36px; }
button.listening-caption-toggle { gap: 7px; padding: 7px 11px; }
button.listening-caption-toggle[aria-pressed='true'] { color: var(--theme-accent-primary); background: var(--theme-status-info-soft); border-color: currentColor; }
.listening-caption-icon { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; width: 16px; padding: 3px 2px; border: 1px solid currentColor; border-radius: 3px; }
.listening-caption-icon i { height: 1px; background: currentColor; }
.listening-caption { block-size: 5.75rem; overflow: auto; scrollbar-gutter: stable; margin-block-start: 8px; padding: 9px 13px; border: 1px solid var(--theme-border-subtle); border-radius: 10px; background: var(--theme-surface-input); }
.listening-caption p { margin: 0; line-height: 1.55; overflow-wrap: anywhere; }
.listening-caption-mode { color: var(--theme-text-secondary); font-size: .75rem; }
.listening-caption-text { font-size: clamp(1rem, 2vw, 1.2rem); }
</style>
