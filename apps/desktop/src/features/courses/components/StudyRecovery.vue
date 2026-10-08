<script setup lang="ts">
import type {useCourseAnswers} from '../../learning/composables/useCourseAnswers'
import type {PlanNotebookController} from '../../notes/composables/usePlanNotebook'
defineProps<{answers:ReturnType<typeof useCourseAnswers>;notebook:PlanNotebookController;progressFailed:boolean}>()
const emit=defineEmits<{retry:[];notes:[]}>()
</script>
<template>
 <div v-if="answers.recovery.value" class="recovery-note" role="alert"><span>发现本设备未保存的内容，请选择恢复；不会自动覆盖工作区版本。</span><button class="secondary-button" @click="answers.restoreCache">恢复可编辑内容</button><button class="text-button" @click="answers.exportRecovery">导出未保存内容</button><button class="text-button" @click="answers.discardCache">使用工作区版本</button></div>
 <div v-if="notebook.recovery.value" class="recovery-note" role="alert"><span>本窗口有未保存的计划笔记，需要你确认保留的版本。</span><button class="secondary-button" @click="emit('notes')">查看并恢复笔记</button></div>
 <div v-if="answers.saveFailed.value||(answers.pending.value&&!answers.busy.value)||notebook.saveFailed.value||(notebook.pending.value&&!notebook.busy.value)||progressFailed" class="recovery-note" role="alert"><span>{{answers.pending.value?'上次写入尚未确认，使用原请求安全重试。':'保存未完成，输入已保留；请先重试或重新读取。'}}</span><button class="secondary-button" :disabled="!!answers.busy.value||notebook.busy.value" @click="emit('retry')">重试保存</button></div>
</template>
