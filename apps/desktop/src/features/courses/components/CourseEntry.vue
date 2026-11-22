<script setup lang="ts">
import {onBeforeUnmount, onMounted, ref} from 'vue'
import {engineCall, studyApi} from '../../../shared/api'
import {makeRequestKey, navigate, notify, reportError} from '../../../shared/ui'
import type {CourseDetailData} from '../../../shared/api/contracts'
import CourseReader from './CourseReader.vue'
import EnglishCourseOverview from '../../english/course/EnglishCourseOverview.vue'

const props = defineProps<{id: string; planLineId?: string; lessonId?: string; initialView?: string; studyId?: string; exerciseId?: string}>()
const emit = defineEmits<{focused: []}>()
const data = ref<CourseDetailData | null>(null)
const failed = ref(false)
const openKey = makeRequestKey('english-open')
let active = true
onBeforeUnmount(() => {active = false})

async function load() {
  failed.value = false
  try {
    const detail = await engineCall<CourseDetailData>('course.detail', {course_id: props.id})
    if (!active) return
    if (detail.course.learning_mode === 'english' && props.initialView !== 'overview') {
      const opened = props.studyId ? await studyApi.courseStudy(props.studyId)
        : await studyApi.openCourseStudy(props.id, openKey, false, false, props.planLineId)
      if (!active) return
      if (opened.course.id !== props.id) throw new Error('学习轮次与课程不匹配。')
      if (opened.scope_notice) notify(opened.scope_notice)
      const query = props.exerciseId ? '?exercise='+encodeURIComponent(props.exerciseId) : ''
      await navigate('/english/'+opened.study.id+query, true)
      return
    }
    data.value = detail
    if (detail.course.legacy_practice && props.initialView !== 'theory') emit('focused')
  } catch (cause) {
    if (!active) return
    failed.value = true
    reportError(cause)
  }
}
onMounted(load)
</script>

<template>
  <EnglishCourseOverview v-if="data?.course.learning_mode === 'english'" :data="data" :plan-line-id="planLineId" />
  <CourseReader v-else-if="data" v-bind="props" :focused-practice="data.course.legacy_practice && initialView !== 'theory'" />
  <div v-else-if="failed" class="error-state"><p>课程暂时无法打开。</p><button class="secondary-button" @click="load">重试</button></div>
  <div v-else class="loading-state" role="status">正在打开课程…</div>
</template>
