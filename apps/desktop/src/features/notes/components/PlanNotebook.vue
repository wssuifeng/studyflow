<script setup lang="ts">
import {computed,ref,nextTick,watch} from 'vue'
import {navigate,reportError,notify} from '../../../shared/ui'
import type {NotebookBlock} from '../../../shared/api/contracts'
import type {PlanNotebookController} from '../composables/usePlanNotebook'
const props=defineProps<{notebook:PlanNotebookController;planTitle?:string;courseId?:string;lessonId?:string;blocked?:boolean}>()
const query=ref(''),readMode=ref(false)
const filter=ref<'PLAN'|'COURSE'|'LESSON'>('PLAN'),documentElement=ref<HTMLElement|null>(null)
const shown=computed(()=>props.notebook.blocks.value.filter(b=>(filter.value==='PLAN'||filter.value==='COURSE'&&b.course_id===props.courseId||filter.value==='LESSON'&&b.lesson_id===props.lessonId)&&(!query.value||(b.text+' '+(b.quote||'')).toLocaleLowerCase().includes(query.value.toLocaleLowerCase()))))
const noteCount=computed(()=>props.notebook.blocks.value.length)
const scopeLabel=computed(()=>filter.value==='PLAN'?'全计划':filter.value==='COURSE'?'本课程':'本知识点')
const saveLabel=computed(()=>props.notebook.busy.value?'正在保存…':props.notebook.saveFailed.value?'保存未确认':props.notebook.dirty.value?'已修改 · 等待保存':props.notebook.savedAt.value?props.notebook.savedAt.value+' 已保存':'保存在本地')
function source(block:NotebookBlock){if(!block.source_study_id||!block.lesson_id)return;const q=new URLSearchParams({lesson:block.lesson_id});if(block.source_block_id)q.set('block',block.source_block_id);navigate('/source/'+block.source_study_id+'?'+q)}
function exportNotes(){try{const lines=['# '+(props.planTitle||'学习笔记'),''];for(const block of props.notebook.blocks.value){lines.push('## '+(block.lesson_title||block.course_title||'计划笔记'),'');if(block.quote)lines.push('> '+block.quote.replaceAll('\n','\n> '),'');lines.push(block.text,'');if(block.source_study_id)lines.push('来源轮次：'+block.source_study_id+' · 版本：'+block.content_hash,'')}const url=URL.createObjectURL(new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'})),a=document.createElement('a');a.href=url;a.download='StudyFlow-学习笔记.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);notify('已导出当前笔记，包含尚未保存的输入。')}catch(cause){reportError(cause)}}
const readonly=computed(()=>!props.notebook.available.value||!!props.blocked||props.notebook.loading.value||props.notebook.failed.value||!!props.notebook.recovery.value||props.notebook.cacheUnreadable.value||!!props.notebook.pending.value&&!props.notebook.busy.value)
function size(element:HTMLTextAreaElement){element.style.height='auto';element.style.height=Math.max(76,Math.min(1200,element.scrollHeight))+'px'}
function fit(event:Event){size(event.target as HTMLTextAreaElement)}
async function add(){if(props.notebook.add(filter.value==='LESSON'?{course_id:props.courseId,lesson_id:props.lessonId}:filter.value==='COURSE'?{course_id:props.courseId}:{})){await nextTick();const editors=documentElement.value?.querySelectorAll('textarea');editors?.[editors.length-1]?.focus()}}
function remove(id:string){props.notebook.removeBlock(id)}
function associate(block:NotebookBlock,scope:'PLAN'|'COURSE'|'LESSON') {block.course_id=scope==='PLAN'?null:props.courseId;block.lesson_id=scope==='LESSON'?props.lessonId:null;block.course_title=null;block.lesson_title=null}
watch(()=>[filter.value,props.notebook.blocks.value.length,props.notebook.loading.value],async()=>{await nextTick();documentElement.value?.querySelectorAll('textarea').forEach(size)},{immediate:true})
watch(()=>props.notebook.blocks.value,async()=>{await nextTick();documentElement.value?.querySelectorAll('textarea').forEach(size)})
watch(()=>props.courseId,()=>{if(!props.courseId)filter.value='PLAN'})
</script>
<template>
 <section class="plan-notebook" aria-label="计划学习笔记">
  <p v-if="!notebook.available.value" class="notebook-alert">这门课程尚未归属学习计划。请通过 Agent 归入计划后使用连续笔记；旧随手草稿仍保留在工作区中。</p>
  <header class="notebook-heading"><div><span class="notebook-kicker">连续学习笔记 · {{noteCount}} 段</span><h3>{{planTitle||'学习计划'}}</h3><p class="notebook-subtitle">把每个知识点的理解串成一份可回看的长期文档。</p></div><button type="button" class="notebook-action" :disabled="readonly" @click="add">＋ 写一段</button></header>
  <div class="notebook-toolbar">
   <div class="notebook-scope-tabs" role="tablist" aria-label="笔记范围">
    <button v-for="item in [{id:'PLAN',label:'全计划'},{id:'COURSE',label:'本课程'},{id:'LESSON',label:'本知识点'}]" v-show="item.id==='PLAN'||item.id==='COURSE'&&courseId||item.id==='LESSON'&&lessonId" :key="item.id" type="button" :class="{selected:filter===item.id}" :aria-selected="filter===item.id" role="tab" @click="filter=item.id as 'PLAN'|'COURSE'|'LESSON'">{{item.label}}</button>
   </div>
   <div class="notebook-actions"><label class="notebook-search"><span aria-hidden="true">⌕</span><input v-model="query" placeholder="查找笔记" aria-label="搜索笔记与摘录"/></label><button type="button" class="text-button" @click="readMode=!readMode">{{readMode?'编辑':'阅读'}}</button><button type="button" class="text-button" @click="exportNotes">导出</button></div>
  </div>
  <div class="notebook-status-line"><span>{{scopeLabel}} · {{shown.length}} 段可见</span><span class="notebook-save-state" :class="{error:notebook.saveFailed.value,dirty:notebook.dirty.value}">{{saveLabel}}</span></div>
  <div v-if="notebook.canUndo.value" class="notebook-undo" role="status"><span>已移除笔记段落</span><button type="button" class="text-button" :disabled="readonly" @click="notebook.undoDelete">撤销删除</button><small>离开此编辑器前可撤销</small></div>
  <div v-if="notebook.cacheUnreadable.value" class="notebook-alert"><p>本机恢复副本无法解析，原始内容仍保留。请先导出，或明确选择使用工作区版本。</p><button type="button" class="text-button" @click="notebook.exportRecovery">导出本机副本</button><button type="button" class="text-button" @click="notebook.discardCache">使用工作区版本</button></div>
  <div v-if="notebook.recovery.value" class="notebook-alert"><p>本机与工作区内容不同。合并会保留双方段落，不静默覆盖。</p><button type="button" class="text-button" :disabled="blocked" @click="notebook.restoreCache">合并本机笔记</button><button type="button" class="text-button" @click="notebook.exportRecovery">导出</button><button type="button" class="text-button" :disabled="blocked" @click="notebook.discardCache">使用工作区版本</button></div>
  <div v-if="notebook.failed.value" class="notebook-alert">笔记暂时无法读取，没有覆盖原内容。<button type="button" class="text-button" @click="notebook.load()">重试读取</button></div>
  <div v-else-if="notebook.loading.value" class="loading-state" role="status">正在恢复计划笔记…</div>
  <template v-else>
   <div v-if="!shown.length" class="notebook-empty"><span>{{query?'没有匹配的笔记':'从这里开始建立你的长期理解'}}</span><p>{{query?'换一个关键词，或切换查看范围。':'这里不是一次性草稿，而是贯穿整个学习计划的可回看记录。'}}</p><button type="button" class="text-button" :disabled="readonly" @click="add">＋ {{query?'写一段新笔记':'记录第一段理解'}}</button></div>
   <div ref="documentElement" class="notebook-document">
    <section v-for="(block,index) in shown" :key="block.id" :data-note-id="block.id" class="notebook-block">
     <header><span class="notebook-block-index">{{String(index+1).padStart(2,'0')}}</span><span class="notebook-block-source">{{block.lesson_title||block.course_title||(block.lesson_id?'知识点笔记':block.course_id?'课程笔记':'计划笔记')}}</span><button type="button" :disabled="readonly" aria-label="移除这段笔记" title="移除这段笔记（保存后生效）" @click="remove(block.id)">×</button></header>
     <button v-if="block.source_study_id" type="button" class="notebook-source-link" @click="source(block)">查看冻结来源 ↗</button><blockquote v-if="block.quote" class="notebook-quote">{{block.quote}}<footer>摘自 {{block.course_title}} / {{block.lesson_title}} · 冻结学习轮次</footer></blockquote>
     <pre v-if="readMode" class="notebook-reading">{{block.text||'（空白段落）'}}</pre><textarea v-else v-model="block.text" :disabled="readonly" class="notebook-editor" :aria-label="'笔记：'+(block.lesson_title||block.course_title||'计划')" placeholder="写下你的理解、联系与疑问…" spellcheck="false" maxlength="200000" @input="fit"/>
     <details v-if="!block.quote" class="notebook-link"><summary>关联范围：{{block.lesson_id?'知识点':block.course_id?'课程':'整个计划'}}</summary><button type="button" :disabled="readonly" @click="associate(block,'PLAN')">归入计划</button><button v-if="courseId" type="button" :disabled="readonly" @click="associate(block,'COURSE')">关联本课程</button><button v-if="lessonId" type="button" :disabled="readonly" @click="associate(block,'LESSON')">关联本知识点</button></details>
    </section>
   </div>
   <button v-if="shown.length" type="button" class="notebook-add-line" :disabled="readonly" @click="add">＋ 继续写笔记</button>
   <details v-if="notebook.legacy.value.length" class="notebook-legacy"><summary>旧版随手草稿（{{notebook.legacy.value.length}}，原文保留）</summary><section v-for="old in notebook.legacy.value" :key="old.id"><small>{{old.course_title}}</small><pre>{{old.text}}</pre><button type="button" class="text-button" :disabled="readonly" @click="notebook.add({text:old.text,course_id:old.course_id,lesson_id:old.lesson_id})">复制到学习笔记</button></section></details>
  </template>
  <footer v-if="notebook.saveFailed.value||notebook.pending.value" class="notebook-alert"><span>保存尚未确认，笔记未丢弃。</span><button type="button" class="text-button" :disabled="notebook.busy.value||blocked" @click="notebook.retry">重试／读取冲突版本</button><button type="button" class="text-button" @click="notebook.exportRecovery">导出笔记</button></footer>
 </section>
</template>
