<script setup lang="ts">
defineProps<{blocked:boolean;read:boolean;last:boolean;canSubmit:boolean;submitting:boolean;feedbackNeeded:boolean;hasExercises:boolean}>()
const emit=defineEmits<{read:[];next:[];submit:[];done:[]}>()
</script>
<template><div class="study-actions"><button class="text-button" :disabled="blocked" @click="emit('read')">{{read?'✓ 已确认读完':'确认读完'}}</button><button v-if="!last" class="primary-button" :disabled="blocked" @click="emit('next')">下一知识点 →</button><button v-else-if="canSubmit" class="primary-button" :disabled="blocked" @click="emit('submit')">{{submitting?'提交中…':feedbackNeeded?'提交本轮修正／复测':hasExercises?'提交并完成本次学习':'完成本次阅读'}} →</button><button v-else class="primary-button" @click="emit('done')">继续学习 →</button></div></template>
