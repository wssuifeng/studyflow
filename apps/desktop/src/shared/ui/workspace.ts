import { ref } from 'vue'
import { isTauri } from '@tauri-apps/api/core'
import { getCurrentWindow } from '@tauri-apps/api/window'

export const workspaceScope = ref('unconnected')
export function storageKey(name: string) { return 'studyflow:' + workspaceScope.value + ':' + name }

// Preserve existing main-window recovery keys; isolate detached window input caches.
export function windowStorageKey(name: string) {
  const label = isTauri() ? getCurrentWindow().label : 'main'
  return storageKey(label === 'main' ? name : 'window:' + label + ':' + name)
}
