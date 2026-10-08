<script setup lang="ts">
defineProps<{kind:string}>()
</script>
<template><svg class="knowledge-status-icon" viewBox="0 0 20 20" aria-hidden="true">
 <template v-if="kind==='passed'"><circle cx="10" cy="10" r="8" class="status-fill"/><path d="m6 10 2.7 2.8L14 7.2" class="status-check"/></template>
 <template v-else-if="kind==='read'"><path d="M3 4.5h5l2 1.5 2-1.5h5v11h-5L10 17l-2-1.5H3zM10 6v11"/></template>
 <template v-else-if="kind==='revision'"><path d="m10 2.5 8 15H2zM10 7v4m0 2.5v.5"/></template>
 <template v-else-if="kind==='retest'"><path d="M16 7a6.5 6.5 0 1 0 .2 6M16 3v4h-4"/></template>
 <template v-else-if="kind==='review'"><circle cx="10" cy="10" r="7"/><path d="M10 6v4l3 2"/></template>
 <template v-else-if="kind==='draft'"><path d="m4 12 9-9 4 4-9 9-5 1zM11 5l4 4"/></template>
 <template v-else-if="kind==='learning'"><circle cx="10" cy="10" r="7"/><path d="m8 6 6 4-6 4z" class="status-fill"/></template>
 <circle v-else cx="10" cy="10" r="6"/>
</svg></template>
