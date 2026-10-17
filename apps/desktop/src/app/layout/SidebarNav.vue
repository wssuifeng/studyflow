<script setup lang="ts">
import {computed} from 'vue'
import {themeAssets,imageIntensity} from '../../shared/themes/display-loader'
// 主题差异只走展示契约/资产层：图标线/字形变体与签名条都由主题 CSS 在
// :root[data-theme-id] 作用域内切换 .nav-icon-svg/.nav-icon-glyph/.sidebar-signature
// 三个纯装饰槽；业务骨架（导航项/按钮/徽标）单一实现，不出现主题ID分支。
const artwork=computed(()=>themeAssets('texture'))
const artworkStyle=computed(()=>({
  '--sidebar-landscape':artwork.value[0]?`url("${artwork.value[0].url}")`:'none',
  '--sidebar-origami':artwork.value[1]?`url("${artwork.value[1].url}")`:'none',
}))

defineProps<{ active: string; count: number; connected: boolean }>()
const emit=defineEmits<{ navigate:[path:string] }>()
const items=[{id:'today',label:'学习控制台',icon:'◈'},{id:'plans',label:'我的计划',icon:'▤'},{id:'queue',label:'作答与反馈',icon:'◎'},{id:'mistakes',label:'错误与复习',icon:'◇'},{id:'settings',label:'工作区',icon:'⚙'}]
</script>
<template><aside class="sidebar" :class="{'subtle-artwork':imageIntensity==='subtle'}" :style="artworkStyle"><div class="brand"><div class="brand-mark">S</div><div><strong>StudyFlow</strong><span>让每一次学习有迹可循</span></div></div><p class="nav-caption">WORKSPACE</p><nav aria-label="主导航"><button v-for="item in items" :key="item.id" :class="['nav-item',{active:active===item.id}]" :aria-label="item.label" :title="item.label" @click="emit('navigate','/'+item.id)"><span class="nav-icon"><svg class="nav-icon-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path v-if="item.id==='today'" d="m3 9 7-6 7 6v8H3zM8 17v-5h4v5"/><path v-else-if="item.id==='plans'" d="M4 3h12v14H4zM7 3v14m3-10h3m-3 4h3"/><path v-else-if="item.id==='queue'" d="M4 4h12v10H9l-4 3v-3H4zm3 4h6m-6 3h4"/><g v-else><circle cx="10" cy="10" r="3"/><path d="m8 3-1 2-3 1v3l-1 2 2 2 1 3h3l2 1 2-2 3-1v-3l1-2-2-2-1-3h-3z"/></g></svg><i class="nav-icon-glyph" aria-hidden="true">{{item.icon}}</i></span>{{ item.label }}<b v-if="item.id==='queue' && count" class="nav-badge">{{ count }}</b></button></nav><div id="course-sidebar-content" class="course-sidebar-slot"/><div class="sidebar-signature" aria-hidden="true"></div><div class="sidebar-bottom"><div class="connection" :class="{connected}"><i/>{{connected?'本地工作区已连接':'正在连接工作区'}}</div><span class="muted small">你的课程与记录，保存在本地。</span></div></aside></template>
