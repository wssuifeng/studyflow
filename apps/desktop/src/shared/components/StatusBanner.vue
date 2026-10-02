<script setup lang="ts">
import { notice } from '../ui'
</script>
<template><Transition name="notice"><div v-if="notice.message" :class="['status-banner',notice.tone]" :role="notice.tone === 'error' ? 'alert' : 'status'"><span class="status-mark">{{ notice.tone === 'error' ? '!' : '✓' }}</span><div><strong>{{ notice.message }}</strong><p v-if="notice.action">{{ notice.action }}</p></div><button class="text-button" aria-label="关闭提示" @click="notice.message=''">×</button></div></Transition></template>
