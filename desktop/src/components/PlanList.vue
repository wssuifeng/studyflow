<script setup lang="ts">
import type { Plan } from '../types'
import { navigate } from '../ui'
defineProps<{plans:Plan[]}>()
</script>
<template><p class="page-lead">每条计划都有自己的课程顺序。选一个方向，继续往前走。</p><div class="plan-grid"><button class="plan-card" v-for="(plan,i) in plans" :key="plan.id" @click="navigate('/plan/'+plan.id)"><div class="plan-card-top"><span class="plan-icon">{{['◇','◈','○','▧'][i%4]}}</span><span class="status-chip">进行中</span></div><h2>{{plan.name}}</h2><p>优先级 {{plan.priority}} · 查看课程与学习进度</p><span class="text-link">打开学习计划 →</span></button></div><div v-if="!plans.length" class="empty-state"><h2>从一个清晰的目标开始。</h2><p>还没有学习计划。外部 Agent 可通过 CLI 创建计划并导入课程，之后会显示在这里。</p></div></template>
