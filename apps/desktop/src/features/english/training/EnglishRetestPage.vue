<script setup lang="ts">
import {onMounted, ref} from 'vue'
import {navigate, reportError} from '../../../shared/ui'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import LeaveStudyDialog from '../../courses/components/LeaveStudyDialog.vue'
import {useEnglishRetest} from './useEnglishRetest'
import TokenEditor from './TokenEditor.vue'
const props = defineProps<{id: string}>()
const session = useEnglishRetest(props.id)
const {task, tokens, busy, result, failed, recovery} = session
const loading = ref(true)
const exit = useSafeStudyExit({busy: () => busy.value, hasProblem: () => !!(failed.value || session.pending.value || recovery.value), flush: session.save, retry: async () => {await session.retryPending()}, suspend: () => {session.suspend(); if (exit.dialog.value?.path === 'close-window') window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}})
onMounted(async () => {try {await session.load()} catch (cause) {failed.value = (cause as Error).message; reportError(cause)} finally {loading.value = false}})
</script>
<template>
  <LeaveStudyDialog v-if="exit.dialog.value" :closing="exit.dialog.value.path==='close-window'" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="session.exportInput"/>
  <p v-if="loading" class="loading-state">正在恢复复测草稿…</p>
  <section v-else-if="task" class="english-learning">
    <header class="english-training-header"><button @click="navigate('/mistakes')">← 返回复习清单</button><strong>无提示复测</strong><small>{{busy?'正在确认保存…':session.dirty.value?'有未保存输入':'草稿已同步'}}</small></header>
    <div v-if="recovery" class="english-recovery" role="status">发现本机未确认输入。<button @click="session.restore">恢复输入</button><button @click="session.discardRecovery">保留工作区版本</button><button @click="session.exportInput">导出</button></div>
    <div v-if="failed" class="english-error" role="alert">{{failed}}<button :disabled="busy" @click="session.retryPending">重试原请求</button><button @click="session.exportInput">导出输入</button><button @click="navigate('/mistakes')">离开复测…</button></div>
    <main class="english-stage"><span class="english-kicker">{{task.title}}</span><h1>{{task.prompt}}</h1><p>不展示参考答案或目标语音；本次检验回忆结果。输入自动保存，确认后本次答案不可覆盖。</p>
      <TokenEditor v-model="tokens" :disabled="busy||!!result||!!recovery" @edited="session.edited" @check="session.check"/>
      <button v-if="!result&&['READY','IN_PROGRESS'].includes(task.status)" class="primary-button" :disabled="busy||!!recovery" @click="session.check">{{busy?'正在确认…':'确认本次复测'}}</button>
      <div v-if="result"><h2>{{result.matched?'本次无提示复测通过':'本次仍有不匹配，已保留证据'}}</h2><p>再次练习时，从复习清单创建新任务；不覆盖这一份原输入。</p><button class="primary-button" @click="navigate('/mistakes')">返回复习清单</button></div>
      <p v-if="session.pending.value">请求尚未确认；重试将使用原幂等键，不重复记录复测。</p>
    </main>
  </section>
  <section v-else class="empty-state"><h1>复测暂时无法打开</h1><p>{{failed}}</p><button @click="navigate('/mistakes')">返回复习清单</button></section>
</template>
