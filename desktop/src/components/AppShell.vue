<script setup lang="ts">
import { isTauri } from '../bridge'
import WindowTitlebar from './WindowTitlebar.vue'
import SidebarNav from './SidebarNav.vue'
import StatusBanner from './StatusBanner.vue'
defineProps<{ active:string; count:number; connected:boolean; title:string; date:string; refreshing:boolean }>()
const emit=defineEmits<{navigate:[path:string];refresh:[]}>()
</script>
<template><WindowTitlebar/><div :class="['app-shell', {'desktop-shell':isTauri()}]"><SidebarNav :active="active" :count="count" :connected="connected" @navigate="emit('navigate',$event)"/><main class="main-content"><header :class="['topbar', {'compact-topbar':active==='plans' && title==='课程工作区'}]"><div><p class="eyebrow">{{date}} <span> / </span> STUDYFLOW</p><h1>{{title}}</h1></div><button class="secondary-button" :disabled="refreshing" @click="emit('refresh')"><span :class="{spin:refreshing}">↻</span> {{refreshing?'同步中':'同步最新状态'}}</button></header><StatusBanner/><slot/></main></div></template>
