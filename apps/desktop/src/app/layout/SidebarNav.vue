<script setup lang="ts">
defineProps<{ active: string; count: number; connected: boolean }>()
const emit=defineEmits<{ navigate:[path:string] }>()
const items=[{id:'today',label:'学习控制台',icon:'◈'},{id:'plans',label:'我的计划',icon:'▤'},{id:'queue',label:'作答与反馈',icon:'◎'},{id:'settings',label:'工作区',icon:'⚙'}]
</script>
<template><aside class="sidebar"><div class="brand"><div class="brand-mark">S</div><div><strong>StudyFlow</strong><span>让每一次学习有迹可循</span></div></div><p class="nav-caption">WORKSPACE</p><nav aria-label="主导航"><button v-for="item in items" :key="item.id" :class="['nav-item',{active:active===item.id}]" @click="emit('navigate','/'+item.id)"><span class="nav-icon">{{ item.icon }}</span>{{ item.label }}<b v-if="item.id==='queue' && count" class="nav-badge">{{ count }}</b></button></nav><div class="sidebar-bottom"><div class="connection" :class="{connected}"><i/>{{connected?'本地工作区已连接':'正在连接工作区'}}</div><span class="muted small">你的课程与记录，保存在本地。</span></div></aside></template>
