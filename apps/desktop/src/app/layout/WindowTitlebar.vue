<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { isTauri } from '../../shared/api'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { reportError } from '../../shared/ui'
const desktop = isTauri()
const maximized = ref(false)
const focused = ref(true)
let disposeResize: (() => void) | undefined
let disposeFocus: (() => void) | undefined
async function syncMaximized() { if (desktop) maximized.value = await getCurrentWindow().isMaximized() }
async function control(action: 'minimize' | 'maximize' | 'close') {
  try {
    const window = getCurrentWindow()
    if (action === 'minimize') await window.minimize()
    else if (action === 'maximize') { await window.toggleMaximize(); await syncMaximized() }
    else await window.close()
  } catch (cause) { reportError(cause) }
}
async function drag(event: MouseEvent) {
  if (!desktop || event.button !== 0 || (event.target as HTMLElement).closest('button, a, input')) return
  try {
    if (event.detail === 2) await control('maximize')
    else await getCurrentWindow().startDragging()
  } catch (cause) { reportError(cause) }
}
onMounted(async () => {
  if (!desktop) return
  try {
    await syncMaximized()
    disposeResize = await getCurrentWindow().onResized(syncMaximized)
    disposeFocus = await getCurrentWindow().onFocusChanged(event => { focused.value = event.payload })
  } catch (cause) { reportError(cause) }
})
onBeforeUnmount(() => { disposeResize?.(); disposeFocus?.() })
</script>
<template>
  <header v-if="desktop" class="window-titlebar" :class="{unfocused:!focused}" @mousedown="drag">
    <div class="window-brand"><span class="window-mark">S</span><span>StudyFlow</span></div><span class="window-context">个人学习空间</span><div class="window-drag-space"/>
    <nav class="window-controls" aria-label="窗口控制"><button aria-label="最小化" title="最小化" @mousedown.stop @click="control('minimize')"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h10"/></svg></button><button :aria-label="maximized ? '还原窗口' : '最大化'" :title="maximized ? '还原窗口' : '最大化'" @mousedown.stop @click="control('maximize')"><svg viewBox="0 0 16 16" aria-hidden="true"><path v-if="maximized" d="M6 3h7v7M3 6h7v7H3z"/><path v-else d="M3.5 3.5h9v9h-9z"/></svg></button><button class="window-close" aria-label="关闭窗口" title="关闭窗口" @mousedown.stop @click="control('close')"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 4 8 8M12 4l-8 8"/></svg></button></nav>
  </header>
</template>
