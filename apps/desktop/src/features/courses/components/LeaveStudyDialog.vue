<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
const props = defineProps<{closing: boolean; reason: string; retrying: boolean}>()
const emit = defineEmits<{retry: []; discard: []; cancel: []; export: []}>()
const panel = ref<HTMLElement | null>(null)
const cancel = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {event.preventDefault(); emit('cancel'); return}
  if (event.key !== 'Tab') return
  const items = panel.value?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')
  if (!items?.length) return
  const first = items[0], last = items[items.length - 1]
  if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus()}
  else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus()}
}
onMounted(async () => {previousFocus = document.activeElement as HTMLElement; await nextTick(); cancel.value?.focus()})
onBeforeUnmount(() => previousFocus?.focus())
</script>
<template>
  <Teleport to="body"><div class="leave-study-backdrop" @click.self="emit('cancel')"><section ref="panel" class="leave-study-dialog" role="alertdialog" aria-modal="true" aria-labelledby="leave-study-title" aria-describedby="leave-study-description" @keydown="keydown">
    <div class="leave-dialog-symbol" aria-hidden="true">!</div><h2 id="leave-study-title">{{closing ? '有内容尚未保存，仍要退出吗？' : '有内容尚未保存，仍要离开吗？'}}</h2>
    <div id="leave-study-description"><p>{{reason}}</p><p>已保存的记录不会被删除。不保存离开将停止后续自动保存，但正在处理的请求可能已写入；下次打开时请以工作区返回的状态为准。</p><p class="leave-loss-warning">未保存内容可能丢失。本机缓存只是尽力保留，磁盘满或缓存不可写时不能保证恢复。</p></div>
    <button class="leave-export text-button" @click="emit('export')">先导出未保存的答案与笔记 ↗</button>
    <div class="leave-dialog-actions"><button ref="cancel" class="secondary-button" @click="emit('cancel')">返回学习</button><button class="secondary-button" :disabled="retrying" @click="emit('retry')">{{retrying ? '正在重试…' : closing ? '重试保存后退出' : '重试保存后离开'}}</button><button class="danger-button" @click="emit('discard')">{{closing ? '不保存并退出' : '不保存并离开'}}</button></div>
    <p v-if="retrying" class="leave-retry-hint" role="status">即使重试未完成，仍可选择不保存退出。</p>
  </section></div></Teleport>
</template>
