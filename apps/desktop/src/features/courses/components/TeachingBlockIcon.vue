<script setup lang="ts">
import type { TeachingBlock } from '../../../shared/api/contracts/content'
defineProps<{kind: TeachingBlock['type']}>()
const paths: Record<TeachingBlock['type'], string> = {
  concept: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z',
  comparison: 'M3 4h14v12H3zM3 8h14M8 4v12',
  steps: 'M7 5h10M7 10h10M7 15h10M3 5h.01M3 10h.01M3 15h.01',
  example: 'M7 4H4v13h12V4h-3M7 2h6v4H7zM7 10h6M7 13h4',
  callout: 'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14Zm0 3v5M10 14h.01',
  summary: 'M3 5l2 2 3-3M10 5h7M3 12l2 2 3-3M10 12h7',
  practice: 'm4 14-1 4 4-1L17 7l-3-3L4 14Zm8-8 3 3',
}
</script>
<template><svg class="teaching-kind-icon" viewBox="0 0 20 20" aria-hidden="true"><path :d="paths[kind]"/></svg></template>
