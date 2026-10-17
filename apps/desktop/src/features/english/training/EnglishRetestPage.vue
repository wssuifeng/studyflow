<script setup lang="ts">
import {nextTick, onMounted, ref} from 'vue'
import {navigate} from '../../../shared/ui'
import {useSafeStudyExit} from '../../learning/composables/useSafeStudyExit'
import RequestProblemDialog from '../../../shared/components/RequestProblemDialog.vue'
import LeaveStudyDialog from '../../courses/components/LeaveStudyDialog.vue'
import {useEnglishRetest} from './useEnglishRetest'
import TokenEditor from './TokenEditor.vue'
const props = defineProps<{id: string}>()
const session = useEnglishRetest(props.id)
const {task, tokens, busy, result, failed, recovery} = session
const loading = ref(true)
const problemDialog = ref<InstanceType<typeof RequestProblemDialog>|null>(null)
const editor = ref<InstanceType<typeof TokenEditor>|null>(null)
async function confirm(){
 await session.check()
 // 空输入等校验提示只落在输入附近，焦点交回第一个空词，不出失败横幅。
 if(session.validationNotice.value){await nextTick();const firstEmpty=tokens.value.findIndex(t=>!t.trim());editor.value?.focusWord(firstEmpty<0?0:firstEmpty)}
}
const exit = useSafeStudyExit({busy: () => busy.value, hasProblem: () => !!(failed.value || session.pending.value || recovery.value), flush: session.save, retry: async () => {await session.retryPending()}, suspend: () => {session.suspend(); if (exit.dialog.value?.path === 'close-window') window.dispatchEvent(new CustomEvent('studyflow-discard-close'))}})
onMounted(async () => {try {await session.load()} catch (cause) {failed.value = (cause as Error).message} finally {loading.value = false}})
</script>
<template>
  <RequestProblemDialog ref="problemDialog" :error="failed" :request-key="String(session.pending.value?.params.idempotency_key||'')" context="english-retest" :retrying="busy" :can-retry="!!session.pending.value" @retry="session.retryPending" @export="session.exportInput"/>
  <LeaveStudyDialog v-if="exit.dialog.value" :closing="exit.dialog.value.path==='close-window'" :reason="exit.dialog.value.reason" :retrying="exit.dialog.value.retrying" @retry="exit.retry" @discard="exit.finish(true,true)" @cancel="exit.finish(false)" @export="session.exportInput"/>
  <p v-if="loading" class="loading-state">正在恢复复测草稿…</p>
  <section v-else-if="task" class="english-learning">
    <header class="english-training-header"><button @click="navigate('/mistakes')">← 返回复习清单</button><strong>无提示复测</strong><button v-if="failed" type="button" class="english-save-status is-problem" @click="problemDialog?.open()">保存待确认</button><small v-else>{{busy?'保存中':session.dirty.value?'待保存':session.pending.value?'保存待确认':'已保存'}}</small></header>
    <div v-if="recovery" class="english-recovery" role="status">发现本机未确认输入。<button @click="session.restore">恢复输入</button><button @click="session.discardRecovery">保留工作区版本</button><button @click="session.exportInput">导出</button></div>
    <main class="english-stage"><span class="english-kicker">{{task.title}}</span><h1>{{task.prompt}}</h1><p>不展示参考答案或目标语音；本次检验回忆结果。输入自动保存，确认后本次答案不可覆盖。</p>
      <TokenEditor v-model="tokens" ref="editor" :minimum="task.token_count" :maximum="task.token_count" :disabled="busy||!!result||!!recovery" @edited="session.edited" @check="confirm"/>
      <p v-if="session.validationNotice.value" class="english-assistance" role="status">{{session.validationNotice.value}}</p>
      <button v-if="!result&&['READY','IN_PROGRESS'].includes(task.status)" class="primary-button" :disabled="busy||!!recovery" @click="confirm">{{busy?'正在确认…':'确认本次复测'}}</button>
      <div v-if="result"><h2>{{result.matched?'本次无提示复测通过':'本次仍有不匹配，已保留证据'}}</h2><p>再次练习时，从复习清单创建新任务；不覆盖这一份原输入。</p><button class="primary-button" @click="navigate('/mistakes')">返回复习清单</button></div>
      <p v-if="session.pending.value">请求尚未确认；重试将使用原幂等键，不重复记录复测。</p>
    </main>
  </section>
  <section v-else class="empty-state"><h1>复测暂时无法打开</h1><p>暂时无法读取工作区，请稍后重试。</p><button @click="navigate('/mistakes')">返回复习清单</button></section>
</template>
