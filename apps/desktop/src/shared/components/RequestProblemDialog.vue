<script setup lang="ts">
import {computed, nextTick, onBeforeUnmount, shallowRef, watch} from 'vue'
import {describeRequestProblem, persistRequestDiagnostic, requestDiagnostic, type DiagnosticContext, type RequestDiagnostic} from '../ui/requestDiagnostics'
const props = defineProps<{error: string; requestKey?: string; context: DiagnosticContext; retrying: boolean; canRetry: boolean}>()
const emit = defineEmits<{retry: []; export: []}>()
const dialog = shallowRef<HTMLDialogElement | null>(null)
const diagnostic = shallowRef<RequestDiagnostic | null>(null), stored = shallowRef(false)
const description = computed(() => describeRequestProblem(props.error))
const titleId = props.context + '-request-problem-title', bodyId = props.context + '-request-problem-body'
let generation = 0
function close() {dialog.value?.close()}
async function open() {if (!props.error) return; await nextTick(); if (props.error && !dialog.value?.open) dialog.value?.showModal()}
watch([() => props.error, () => props.requestKey], async ([error]) => {
  const ticket = ++generation
  if (!error) {close(); diagnostic.value = null; return}
  diagnostic.value = requestDiagnostic(props.context, error); stored.value = false
  const entry = diagnostic.value
  void persistRequestDiagnostic(entry).then(saved => {if (ticket === generation) stored.value = saved})
  await nextTick()
  if (ticket === generation) await open()
}, {immediate: true, flush: 'post'})
onBeforeUnmount(() => {generation++; close()})
defineExpose({open})
</script>
<template>
 <Teleport to="body"><dialog ref="dialog" class="request-problem-modal" role="alertdialog" :aria-labelledby="titleId" :aria-describedby="bodyId" @cancel.prevent="close" @click="event=>{if(event.target===dialog)close()}">
  <section class="leave-study-dialog request-problem-card">
   <h2 :id="titleId">{{description.title}}</h2>
   <p :id="bodyId">{{description.description}}</p>
   <details class="request-problem-details"><summary>技术信息</summary><p><code>{{diagnostic?.code}}</code><br>{{stored?'已写入本地诊断日志':'诊断日志未确认写入'}} · {{diagnostic?.event_id}}</p></details>
   <div class="leave-dialog-actions"><button type="button" class="secondary-button" @click="emit('export')">导出输入</button><button type="button" class="secondary-button" autofocus @click="close">暂时关闭</button><button v-if="canRetry" type="button" class="primary-button" :disabled="retrying" @click="emit('retry')">{{retrying?'正在确认…':'重试原操作'}}</button></div>
  </section>
 </dialog></Teleport>
</template>
<style scoped>
.request-problem-modal{padding:0;border:0;background:transparent;width:min(560px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:visible}
.request-problem-modal::backdrop{background:color-mix(in srgb,var(--theme-overlay-ink) 27%,transparent);backdrop-filter:blur(5px)}
.request-problem-card{width:100%;max-height:calc(100vh - 48px);overflow:auto}
.request-problem-details{margin:18px 0;color:var(--theme-text-muted);font-size:12px}
.request-problem-details summary{cursor:pointer}
.request-problem-details code{overflow-wrap:anywhere}
</style>
