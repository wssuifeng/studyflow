<script setup lang="ts">
import {computed,ref} from 'vue'
import type { Plan } from '../../../shared/api/contracts'
import { navigate,statusLabel } from '../../../shared/ui'
const props=defineProps<{plans:Plan[]}>()
const query=ref(''),showHistory=ref(false)
const normalizedQuery=computed(()=>query.value.trim().toLocaleLowerCase())
const shown=computed(()=>props.plans.filter(p=>(showHistory.value||p.status==='ACTIVE')&&p.name.toLocaleLowerCase().includes(normalizedQuery.value)))
</script>
<template><p class="page-lead">每条计划都有自己的课程顺序。</p><div class="plan-list-filters"><input v-model="query" aria-label="查找计划" placeholder="查找计划…"/><label><input v-model="showHistory" type="checkbox"/> 包含暂停与归档</label></div><div v-if="shown.length" class="plan-grid"><button class="plan-card" v-for="(plan,i) in shown" :key="plan.id" @click="navigate('/plan/'+plan.id)"><div class="plan-card-top"><span class="plan-icon">{{['◇','◈','○','▧'][i%4]}}</span><span class="status-chip">{{statusLabel(plan.status)}}</span></div><span class="plan-card-title">{{plan.name}}</span><span class="plan-card-meta">优先级 {{plan.priority}}</span></button></div><div v-else-if="!plans.length" class="empty-state"><p>还没有学习计划。外部 Agent 可通过 CLI 创建计划并导入课程，之后会显示在这里。</p></div><div v-else class="empty-state"><h2>当前筛选条件下没有计划。</h2><p>可以清空搜索，或打开“包含暂停与归档”查看其他计划。</p><button class="text-button" @click="query='';showHistory=false">清除筛选</button></div></template>
