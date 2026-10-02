<script setup lang="ts">
import type { DoctorData } from '../../../shared/api/contracts'
defineProps<{ doctor: DoctorData | null }>()
</script>
<template><div class="page-intro"><p class="eyebrow">LOCAL WORKSPACE</p><h2>学习记录，留在你掌控的地方。</h2><p class="muted">课程、作答与反馈使用同一个本地工作区。</p></div><section class="workspace-panel"><div class="workspace-icon">▱</div><h3>当前工作区</h3><p class="workspace-path">{{doctor?.workspace.root || '尚未连接'}}</p><dl class="workspace-details"><div><dt>连接状态</dt><dd>{{doctor?.healthy?'已连接':'暂未连接'}}</dd></div><div><dt>数据存储</dt><dd>{{doctor?.database.managed_by_app?'应用管理的本地数据库':doctor?.database.driver || '未知'}}</dd></div><div><dt>学习材料</dt><dd>Markdown 原文 + 安全阅读视图</dd></div><div><dt>课程与批改</dt><dd>由外部 Agent 通过统一 CLI 维护</dd></div></dl><p class="muted small">阅读百分比记录阅读位置；通过状态来自练习与批改证据。</p></section></template>
