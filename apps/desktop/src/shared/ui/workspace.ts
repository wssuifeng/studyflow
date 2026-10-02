import { ref } from 'vue'

export const workspaceScope = ref('unconnected')
export function storageKey(name: string) { return 'studyflow:' + workspaceScope.value + ':' + name }
