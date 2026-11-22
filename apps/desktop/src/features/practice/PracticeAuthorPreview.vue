<script setup lang="ts">
import {computed, shallowRef} from 'vue'
import PracticeWorkspace from './PracticeWorkspace.vue'

type Item = {lessonId: string; id: string; title: string; kind: 'reading' | 'listening'}
const contents = shallowRef<Record<string, unknown>>()
const choices = shallowRef<Item[]>([])
const selected = shallowRef(0)
const opened = shallowRef(false)
const error = shallowRef('')
const source = computed(() => {
  const item = choices.value[selected.value]
  return contents.value && item ? {package: contents.value, lesson_id: item.lessonId, exercise_id: item.id} : undefined
})
async function selectFile(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  opened.value = false
  contents.value = undefined
  choices.value = []
  selected.value = 0
  error.value = ''
  if (!file) return
  try {
    if (file.size > 4 * 1024 * 1024) throw new Error('课程包超过 4 MiB。')
    const data = JSON.parse(await file.text())
    const supported = ['studyflow.course-package/7', 'studyflow.course-package/8']
    if (!supported.includes(data?.schema) || !Array.isArray(data.lessons)) throw new Error('请选择 /7 或 /8 课程包。')
    choices.value = data.lessons.flatMap((lesson: {id: string; title: string; exercises?: {type: string; title: string; id: string}[]}) =>
      (lesson.exercises ?? []).filter(item => ['READING_GROUP','LISTENING_GROUP'].includes(item.type)).map(item => ({
        lessonId: lesson.id, id: item.id, title: `${lesson.title} · ${item.title}`, kind: item.type === 'READING_GROUP' ? 'reading' : 'listening',
      })))
    if (!choices.value.length) throw new Error('该包没有听力或阅读题组。')
    contents.value = data
  } catch (cause) {error.value = cause instanceof Error ? cause.message : '课程包无法读取。'}
}
</script>

<template>
  <section class="workspace-panel" aria-label="题组预览">
    <h3>题组预览</h3>
    <p>选择课程包，检查题面、作答和解析。预览答案随页面关闭清除。</p>
    <label class="field-label">课程包 JSON<input type="file" accept=".json,application/json" @change="selectFile" /></label>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="source" class="management-controls">
      <label>题组 <select v-model.number="selected" @change="opened = false"><option v-for="(item, index) in choices" :key="index" :value="index">{{ item.title }}</option></select></label>
      <button type="button" class="secondary-button" :disabled="opened" @click="opened = true">打开预览</button>
    </div>
    <PracticeWorkspace v-if="opened && source && choices[selected]" :key="selected" :exercise-id="source.exercise_id" study-id="author-preview"
      :kind="choices[selected]!.kind" :blocked="false" :preview="source" @back="opened = false" />
  </section>
</template>
