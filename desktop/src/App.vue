<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { engineCall } from './bridge'
import type { DoctorData, Plan, QueueData, TodayData } from './types'
import { navigate, notify, reportError, storageKey, workspaceScope } from './ui'
import AppShell from './components/AppShell.vue'
import TodayWorkspace from './components/TodayWorkspace.vue'
import PlanList from './components/PlanList.vue'
import PlanDetail from './components/PlanDetail.vue'
import CourseReader from './components/CourseReader.vue'
import QueueView from './components/QueueView.vue'
import SubmissionFeedback from './components/SubmissionFeedback.vue'
import WorkspaceSettings from './components/WorkspaceSettings.vue'
const today = ref<TodayData | null>(null)
const plans = ref<Plan[]>([])
const queue = ref<QueueData | null>(null)
const doctor = ref<DoctorData | null>(null)
const loading = ref(true)
const refreshing = ref(false)
const failed = ref(false)
const route = ref(window.location.hash.slice(1) || '/today')
const revision = ref(0)
const parsed = computed(()=>{
  const [path, query] = route.value.split('?')
  const pieces = path!.split('/').filter(Boolean)
  return {name:pieces[0] || 'today', id:pieces[1] || '', lesson:new URLSearchParams(query).get('lesson') || undefined, tab:new URLSearchParams(query).get('tab') || undefined}
})
const active = computed(()=> parsed.value.name==='plan' || parsed.value.name==='course' ? 'plans' : parsed.value.name==='submission' ? 'queue' : parsed.value.name)
const titles: Record<string,string> = {today:'学习控制台',plans:'我的计划',plan:'学习计划',course:'课程工作区',queue:'作答与反馈',submission:'作答与反馈',settings:'工作区'}
const title = computed(()=>titles[parsed.value.name] || 'StudyFlow')
const dateLabel = computed(()=>new Date().toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'}))
const feedbackCount = computed(()=> (today.value?.queue_counts.needs_revision || 0)+(today.value?.queue_counts.waiting_retest || 0)+(today.value?.queue_counts.waiting_review || 0))
function readRoute() { route.value = window.location.hash.slice(1) || '/today'; localStorage.setItem(storageKey('last-route'),route.value); if(!loading.value && !refreshing.value) load() }
async function load(refresh=false) {
  refreshing.value=true
  try {
    const nextDoctor=await engineCall<DoctorData>('system.doctor')
    doctor.value=nextDoctor; workspaceScope.value=nextDoctor.workspace.root
    if (loading.value && !window.location.hash) {
      const saved=localStorage.getItem(storageKey('last-route'))
      if (saved) { route.value=saved; window.history.replaceState(null,'','#'+saved) }
    }
    const results = await Promise.all([engineCall<TodayData>('study.today'),engineCall<{plans:Plan[]}>('plan.list'),engineCall<QueueData>('assignment.queue')])
    today.value=results[0]; plans.value=results[1].plans; queue.value=results[2]; failed.value=false
    if(refresh) {revision.value++; notify('课程与反馈已同步到最新状态。')}
  } catch(cause) {failed.value=true;reportError(cause)}
  finally {loading.value=false;refreshing.value=false}
}
onMounted(()=>{window.addEventListener('hashchange',readRoute);load()})
onBeforeUnmount(()=>window.removeEventListener('hashchange',readRoute))
</script>

<template>
  <AppShell :active="active" :count="feedbackCount" :connected="!!doctor?.healthy && !failed" :title="title" :date="dateLabel" :refreshing="refreshing" @navigate="navigate" @refresh="load(true)">
    <div v-if="loading" class="loading-state initial-loading" role="status"><span class="loading-orbit"/><h2>正在打开本地学习空间</h2><p>恢复计划、课程与反馈…</p></div>
    <div v-else-if="failed" class="error-state initial-loading"><h2>工作区暂时无法连接</h2><p>你的记录仍保存在本地。连接恢复后可以继续。</p><button class="primary-button" @click="() => load()">重新连接 ↻</button></div>
    <Transition v-else name="page" mode="out-in">
      <div :key="parsed.name+':'+parsed.id+':'+revision" class="page-content">
        <TodayWorkspace v-if="parsed.name==='today' && today" :data="today" />
        <PlanList v-else-if="parsed.name==='plans'" :plans="plans" />
        <PlanDetail v-else-if="parsed.name==='plan' && parsed.id" :id="parsed.id" />
        <CourseReader v-else-if="parsed.name==='course' && parsed.id" :id="parsed.id" :lesson-id="parsed.lesson" :initial-view="parsed.tab" />
        <QueueView v-else-if="parsed.name==='queue'" :data="queue" />
        <SubmissionFeedback v-else-if="parsed.name==='submission' && parsed.id" :id="parsed.id" />
        <WorkspaceSettings v-else-if="parsed.name==='settings'" :doctor="doctor" />
        <div v-else class="empty-state"><h2>页面暂不存在</h2><button class="primary-button" @click="navigate('/today')">回到学习控制台</button></div>
      </div>
    </Transition>
    <footer class="app-footer"><span>每天向前一点，知识就有了自己的形状。</span><span>StudyFlow · LOCAL FIRST</span></footer>
  </AppShell>
</template>
