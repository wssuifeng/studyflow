<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,provide,reactive,ref} from 'vue'
import { isTauri } from '../../shared/api'
import {panelGeometry,workspacePanelKey,type PanelPresentation} from '../../shared/layout/workspacePanel'
import DisplaySlot from '../../shared/components/DisplaySlot.vue'
import WindowTitlebar from './WindowTitlebar.vue'
import SidebarNav from './SidebarNav.vue'
import StatusBanner from '../../shared/components/StatusBanner.vue'
import { activeDisplay, primaryBackground, hasDisplayView, displayThemeId } from '../../shared/themes/display-loader'
const props=defineProps<{ focus?: boolean; windowChrome?: boolean; active:string; count:number; connected:boolean; title:string; date:string; refreshing:boolean }>()
const emit=defineEmits<{navigate:[path:string];refresh:[]}>()
const panel=reactive<PanelPresentation>({visible:false,width:420,full:false})
const viewport=ref(window.innerWidth)
const sequenceNavigation=computed(()=>displayThemeId.value==='sequence-light'?Math.round(viewport.value<900?64:Math.min(280,Math.max(216,viewport.value*.14))):undefined)
const geometry=computed(()=>panelGeometry(viewport.value,panel.width,panel.full,!!props.focus,sequenceNavigation.value))
let owner:symbol|undefined
provide(workspacePanelKey,{geometry,navigationVisible:computed(()=>!props.focus),publish:(id,state)=>{owner=id;Object.assign(panel,state)},release:id=>{if(owner===id){panel.visible=false;panel.full=false;owner=undefined}}})
const resize=()=>{viewport.value=window.innerWidth}
onMounted(()=>window.addEventListener('resize',resize))
onBeforeUnmount(()=>window.removeEventListener('resize',resize))
/**
 * 主题声明的背景素材：只使用构建期注册表解析出的本地 URL。
 * 缺图或用户选择「无图」时 primaryBackground() 返回 null，走纯色回退。
 */
const background=computed(()=>props.focus?null:primaryBackground())
const shellClass=computed(()=>['app-shell',{'desktop-shell':isTauri(),'focus-shell':props.focus,'workspace-shell':!props.focus,'learning-shell':props.title==='课程工作区','panel-open':panel.visible,'panel-expanded':panel.visible&&(panel.full||geometry.value.compact),'has-theme-background':!!background.value,'theme-shell-owned':hasDisplayView('shell')}])
const shellProps=computed(()=>({
  class:shellClass.value,
  'data-theme-display':displayThemeId.value,
  style:{
    '--panel-width':geometry.value.width+'px',
    '--panel-nav-width':geometry.value.navigation+'px',
    '--theme-nav-width':(sequenceNavigation.value ?? activeDisplay.value.navigation_width)+'px',
    '--theme-tools-width':activeDisplay.value.tools_width+'px',
    '--theme-radius':activeDisplay.value.radius+'px',
    '--theme-bg-image':background.value?`url("${background.value.url}")`:'none',
    '--theme-bg-fallback':background.value?.fallback ?? 'transparent',
  },
}))
const navigationProps=computed(()=>({active:props.active,count:props.count,connected:props.connected}))
const titlebarProps=computed(()=>({context:props.title}))
// Detached tool windows use the same focus layout as the reader, but they still
// need the custom titlebar because native decorations are disabled. Without
// it a tool window has no reliable close/minimize/maximize/always-on-top entry.
const showTitlebar=computed(()=>!props.focus || !!props.windowChrome)
const showNavigation=computed(()=>!props.focus)
</script>
<template>
  <!-- 窗口壳：产品默认结构保留拖动与窗口按钮；候选可提供不同容器语言，功能入口不变。 -->
  <DisplaySlot v-if="showTitlebar" slot="titlebar" :fallback="WindowTitlebar" :view-props="titlebarProps"/>
  <DisplaySlot slot="shell" :fallback="'div'" :view-props="shellProps">
    <template #navigation>
      <DisplaySlot v-if="showNavigation" slot="navigation" :fallback="SidebarNav" :view-props="navigationProps" @navigate="emit('navigate',$event)"/>
    </template>
    <template #main>
      <main class="main-content">
        <header v-if="!focus && title !== '课程工作区'" class="topbar"><div><p class="eyebrow">{{date}} <span> / </span> STUDYFLOW</p><h1>{{title}}</h1></div><button class="secondary-button" :disabled="refreshing" @click="emit('refresh')"><span :class="{spin:refreshing}">↻</span> {{refreshing?'同步中':'同步最新状态'}}</button></header>
        <slot/>
      </main>
    </template>
    <template #tools>
      <div id="workspace-tool-panel" v-show="panel.visible" class="workspace-tool-panel" :aria-hidden="!panel.visible" :inert="!panel.visible"/>
    </template>
    <template #status>
      <StatusBanner/>
    </template>
  </DisplaySlot>
</template>
