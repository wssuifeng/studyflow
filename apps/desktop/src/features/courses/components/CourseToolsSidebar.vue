<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue'
import {isTauri} from '../../../shared/api'
import type {LessonDetail} from '../../../shared/api/contracts'
import type {AnswerRow} from '../../learning/composables/useCourseAnswers'
import type {PlanNotebookController} from '../../notes/composables/usePlanNotebook'
import CourseToolContent from './CourseToolContent.vue'
import {toolTabs,type ToolTab,type DockState} from '../dock/state'
const props=defineProps<{dock:DockState;lessons:LessonDetail[];index:number;rows:AnswerRow[];blocked:boolean;notebook:PlanNotebookController;planTitle?:string;courseId:string;detached:ToolTab[];maxWidth:number;effectiveWidth?:number;courseTitle?:string;compact?:boolean;sequence?:boolean;coursePosition?:number;courseTotal?:number;courseProgress?:number;saveLabel?:string;saveFailed?:boolean}>()
const emit=defineEmits<{activate:[tool:ToolTab,pane?:number];close:[tool:ToolTab];select:[index:number];section:[lessonIndex:number,blockId:string];collapse:[];width:[width:number];full:[];unsplit:[];split:[tool:ToolTab];ratio:[ratio:number];detach:[tool:ToolTab];dock:[tool:ToolTab];reorder:[from:ToolTab,to:ToolTab]}>()
const panel=ref<HTMLElement|null>(null),menu=ref<ToolTab|null>(null),addMenu=ref(false),dragging=ref(false)
const tabs=computed(()=>props.dock.order.filter(t=>props.dock.open.includes(t)).map(id=>toolTabs.find(t=>t.id===id)!))
const activePane=ref(0)
const sequenceTool=computed<ToolTab>(()=>props.dock.panes[activePane.value]==='notes'?'notes':'exercises')
const completedLessons=computed(()=>props.lessons.filter(item=>item.progress.status==='COMPLETED').length)
const nextLesson=computed(()=>props.lessons[props.index+1])
const safeCourseProgress=computed(()=>Math.max(0,Math.min(100,Math.round(props.courseProgress||0))))
watch(()=>props.dock.panes.length,count=>{activePane.value=Math.min(activePane.value,Math.max(0,count-1))})
let dragged:ToolTab|null=null,frame=0,moveX=0,startX=0,startWidth=0,rectLeft=0,rectWidth=1
function resizeStart(e:PointerEvent,split=false){if(e.button!==0)return;e.preventDefault();(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);dragging.value=true;startX=e.clientX;startWidth=props.effectiveWidth??props.dock.width;const rect=panel.value!.getBoundingClientRect();rectLeft=rect.left;rectWidth=rect.width;(e.currentTarget as HTMLElement).dataset.split=String(split)}
function resizeMove(e:PointerEvent){if(!dragging.value)return;moveX=e.clientX;if(frame)return;const split=(e.currentTarget as HTMLElement).dataset.split==='true';frame=requestAnimationFrame(()=>{frame=0;if(split)emit('ratio',Math.max(.2,Math.min(.8,(moveX-rectLeft)/rectWidth)));else emit('width',Math.max(280,Math.min(props.maxWidth,startWidth+startX-moveX)))})}
function resizeEnd(){dragging.value=false;cancelAnimationFrame(frame);frame=0}
function beginDrag(e:DragEvent,tool:ToolTab){dragged=tool;if(e.dataTransfer){e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',tool)}}
function dragEnd(e:DragEvent){if(!dragged||!panel.value)return;if(e.clientX===0&&e.clientY===0){dragged=null;return}const r=panel.value.getBoundingClientRect();if(e.clientX<r.left-20||e.clientX>r.right+20||e.clientY<r.top-20||e.clientY>r.bottom+20)emit('detach',dragged);dragged=null}
function focusTool(tool:ToolTab){const existing=props.dock.panes.indexOf(tool);if(existing>=0)activePane.value=existing;emit('activate',tool,activePane.value)}
function key(e:KeyboardEvent){const ids=tabs.value.map(t=>t.id);const current=ids.indexOf(props.dock.panes[activePane.value]!);let i=current;if(e.key==='ArrowRight')i=(current+1)%ids.length;else if(e.key==='ArrowLeft')i=(current+ids.length-1)%ids.length;else if(e.key==='Home')i=0;else if(e.key==='End')i=ids.length-1;else return;e.preventDefault();const t=ids[i];if(t){focusTool(t);requestAnimationFrame(()=>document.getElementById('dock-tab-'+t)?.focus())}}
onBeforeUnmount(()=>cancelAnimationFrame(frame))
</script>
<template>
 <aside ref="panel" class="course-tools unified-tools-panel sequence-tools-panel" :data-dragging="dragging||undefined" aria-label="学习工具侧栏" @keydown.esc="menu=null;addMenu=false">
  <div v-if="!dock.full&&!compact" class="dock-resizer" role="separator" aria-label="调整学习工具宽度" aria-orientation="vertical" tabindex="0" :aria-valuemin="280" :aria-valuemax="maxWidth" :aria-valuenow="effectiveWidth??dock.width" aria-controls="workspace-tool-panel" @pointerdown="resizeStart($event)" @pointermove="resizeMove" @pointerup="resizeEnd" @pointercancel="resizeEnd" @lostpointercapture="resizeEnd" @keydown.left.prevent="emit('width',Math.min(maxWidth,(effectiveWidth??dock.width)+20))" @keydown.right.prevent="emit('width',Math.max(280,(effectiveWidth??dock.width)-20))"/>
  <header class="sequence-tool-heading">
   <div class="sequence-tool-heading-copy"><span>当前知识点</span><strong :title="lessons[index]?.title">{{lessons[index]?.title||'学习工具'}}</strong></div>
   <div class="sequence-tool-heading-actions"><button class="sequence-icon-action" :title="dock.full?'恢复侧栏宽度':'展开工具区域'" :aria-label="dock.full?'恢复侧栏宽度':'展开工具区域'" @click="emit('full')"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3 7V3h4M13 3h4v4M17 13v4h-4M7 17H3v-4"/></svg></button><button class="sequence-icon-action" title="收起学习工具" aria-label="收起学习工具" @click="emit('collapse')"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12 4-6 6 6 6"/></svg></button></div>
  </header>
  <nav class="sequence-tool-tabs" role="tablist" aria-label="学习工具与笔记">
   <button id="sequence-tools-tab" role="tab" :aria-selected="sequenceTool==='exercises'" aria-controls="sequence-tools-pane" :class="{active:sequenceTool==='exercises'}" @click="focusTool('exercises')"><span class="sequence-tab-icon" aria-hidden="true">✎</span>学习工具<span v-if="rows.length" class="sequence-tab-count">{{rows.length}}</span></button>
   <button id="sequence-notes-tab" role="tab" :aria-selected="sequenceTool==='notes'" aria-controls="sequence-tools-pane" :class="{active:sequenceTool==='notes'}" @click="focusTool('notes')"><span class="sequence-tab-icon" aria-hidden="true">▤</span>笔记</button>
   <div class="sequence-tab-actions"><button class="sequence-icon-action" title="其他工具操作" aria-label="其他工具操作" @click="menu=menu?null:sequenceTool;addMenu=false">···</button><button class="sequence-icon-action" title="重新打开工具" aria-label="重新打开工具" :aria-expanded="addMenu" @click="addMenu=!addMenu;menu=null">＋</button></div>
  </nav>
  <div v-if="addMenu" class="sequence-tool-menu" role="menu"><button v-for="t in toolTabs" :key="t.id" role="menuitem" @click="emit('activate',t.id);addMenu=false">{{t.label}}<span>{{dock.open.includes(t.id)?'切换':'重新打开'}}</span></button></div>
  <div v-if="menu" class="sequence-tool-menu" role="menu"><button v-if="isTauri()" role="menuitem" @click="emit('detach',sequenceTool);menu=null">拆为独立窗口 ↗</button><button v-if="dock.panes.length<2" role="menuitem" @click="emit('split',sequenceTool);menu=null">在第二窗格查看</button><button v-else role="menuitem" @click="emit('unsplit');menu=null">回到单窗格</button><button role="menuitem" @click="emit('close',sequenceTool);menu=null">关闭当前工具（保留数据）</button></div>
  <div v-if="$slots.recovery" class="sequence-recovery"><slot name="recovery"/></div>
  <div id="sequence-tools-pane" class="sequence-tool-scroll" role="tabpanel" :aria-labelledby="sequenceTool==='notes'?'sequence-notes-tab':'sequence-tools-tab'">
   <template v-if="sequenceTool==='exercises'">
    <section class="sequence-tool-section sequence-answer-section"><div class="sequence-section-heading"><h3>答案草稿</h3><span :class="['sequence-tool-caption',{error:saveFailed}]">{{saveLabel||'正在同步答案'}}</span></div><CourseToolContent tool="exercises" :lessons="lessons" :index="index" :rows="rows" :blocked="blocked" :notebook="notebook" :plan-title="planTitle" :course-id="courseId" @select="emit('select',$event)" @section="(i,b)=>emit('section',i,b)"/></section>
    <section class="sequence-tool-section"><div class="sequence-section-heading"><h3>学习进度</h3><span class="sequence-tool-caption">当前课程</span></div><div class="sequence-progress-card"><div class="sequence-progress-ring" role="progressbar" aria-label="当前课程学习进度" :aria-valuenow="safeCourseProgress" aria-valuemin="0" aria-valuemax="100" :style="{'--sequence-progress':safeCourseProgress+'%'}"><b>{{safeCourseProgress}}%</b></div><div class="sequence-progress-copy"><strong>已读 {{completedLessons}} / {{lessons.length}} 个知识点</strong><span>本课第 {{index+1}} / {{lessons.length}} 个知识点</span></div></div></section>
    <section class="sequence-tool-section"><div v-if="nextLesson" class="sequence-next-card"><small>下一知识点</small><strong :title="nextLesson.title">{{nextLesson.title}}</strong><button :disabled="blocked" @click="emit('select',index+1)">前往下一知识点 <span aria-hidden="true">→</span></button></div><div v-else class="sequence-next-card is-finished"><small>学习路径</small><strong>已经到达本课最后一个知识点</strong></div></section>
    <section v-if="isTauri()" class="sequence-tool-section"><div class="sequence-section-heading"><h3>窗口协作</h3><span class="sequence-tool-caption">共享本轮状态</span></div><div class="sequence-window-card"><span class="sequence-window-mark" aria-hidden="true">↗</span><div><strong>{{detached.includes(sequenceTool)?'工具已在独立窗口':'学习中需要更大空间？'}}</strong><span>{{detached.includes(sequenceTool)?'输入与主窗口共用同一工作区':'把当前学习工具弹出为独立窗口'}}</span></div><button :disabled="blocked" @click="detached.includes(sequenceTool)?emit('dock',sequenceTool):emit('detach',sequenceTool)">{{detached.includes(sequenceTool)?'放回':'弹出'}}</button></div></section>
    <section class="sequence-tool-section sequence-save-protection"><div class="sequence-section-heading"><h3>保存保护</h3><span :class="['sequence-save-mark',{error:saveFailed}]">{{saveFailed?'需要处理':'已启用'}}</span></div><p>{{saveFailed?'输入仍保留在当前窗口；可重试保存或使用下方恢复操作。':'答案与笔记自动保存到本地工作区，离开前会再次检查未保存内容。'}}</p></section>
   </template>
   <CourseToolContent v-else :tool="sequenceTool" :lessons="lessons" :index="index" :rows="rows" :blocked="blocked" :notebook="notebook" :plan-title="planTitle" :course-id="courseId" @select="emit('select',$event)" @section="(i,b)=>emit('section',i,b)"/>
  </div>
  <footer class="sequence-tool-footer" :class="{'has-error':saveFailed}" role="status"><span aria-hidden="true"/><strong>{{saveLabel||'与主窗口共享本轮学习记录'}}</strong></footer>
 </aside>

</template>
