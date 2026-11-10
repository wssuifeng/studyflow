<script setup lang="ts">
import {computed,ref,onBeforeUnmount,onMounted} from 'vue'
import NotebookIcon from './NotebookIcon.vue'
import type {Course,Scope} from '../editor/model'

const props=defineProps<{courses:Course[];scope:Scope;current?:Scope}>()
const emit=defineEmits<{change:[scope:Scope];selectCourse:[id:string]}>()
const picker=ref(false),query=ref(''),root=ref<HTMLElement>()
const course=computed(()=>props.courses.find(item=>item.id===props.scope.courseId))
const lesson=computed(()=>course.value?.lessons.find(item=>item.id===props.scope.lessonId))
const selectionLabel=computed(()=>props.scope.mode==='PLAN'?'全计划':props.scope.mode==='COURSE'?course.value?.title||'当前课程':[course.value?.title,lesson.value?.title].filter(Boolean).join(' · ')||'当前知识点')
const filteredCourses=computed(()=>props.courses.filter(item=>!query.value||item.title.includes(query.value)||item.lessons.some(lesson=>lesson.title.includes(query.value))))
function visibleLessons(item:Course){return item.lessons.filter(lesson=>!query.value||item.title.includes(query.value)||lesson.title.includes(query.value))}
function chooseCourse(id:string){emit('change',id==='__plan'?{mode:'PLAN'}:{mode:'COURSE',courseId:id});if(id!=='__plan')emit('selectCourse',id);picker.value=false}
function chooseLesson(courseId:string,lessonId:string){emit('change',{mode:'LESSON',courseId,lessonId});picker.value=false}
function keyboard(event:KeyboardEvent){
 if(event.key==='Escape'){picker.value=false;return}
 if(!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return
 event.preventDefault()
 const buttons=[...root.value!.querySelectorAll<HTMLButtonElement>('.picker-item:not(:disabled)')]
 let at=buttons.indexOf(document.activeElement as HTMLButtonElement)
 at=event.key==='Home'?0:event.key==='End'?buttons.length-1:(at+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length
 buttons[at]?.focus()
}
function outside(event:MouseEvent){if(!root.value?.contains(event.target as Node))picker.value=false}
onMounted(()=>window.addEventListener('click',outside))
onBeforeUnmount(()=>window.removeEventListener('click',outside))
</script>

<template>
 <div ref="root" class="scope-bar" :class="{'is-plan-scope':scope.mode==='PLAN'}" @keydown="keyboard">
  <div class="picker-wrap">
   <button type="button" class="scope-button" aria-label="当前笔记位置" :aria-expanded="picker" aria-haspopup="dialog" @click="picker=!picker;query=''">
    <span class="scope-label">{{selectionLabel}}</span><NotebookIcon name="chevron"/>
   </button>
   <div v-if="picker" class="picker-panel scope-picker-panel" role="dialog" aria-label="选择笔记位置">
    <input v-model="query" aria-label="查找课程或知识点" placeholder="查找课程或知识点…">
    <button class="picker-item" :aria-pressed="scope.mode==='PLAN'" @click="chooseCourse('__plan')">全计划</button>
    <div v-for="item in filteredCourses" :key="item.id" class="scope-course-options" role="group" :aria-label="item.title">
     <button class="picker-item scope-course-option" :aria-pressed="scope.mode==='COURSE'&&scope.courseId===item.id" @click="chooseCourse(item.id)">{{item.title}}<span>整门课程</span></button>
     <button v-for="part in visibleLessons(item)" :key="part.id" class="picker-item scope-lesson-option" :aria-pressed="scope.mode==='LESSON'&&scope.courseId===item.id&&scope.lessonId===part.id" @click="chooseLesson(item.id,part.id)">{{part.title}}</button>
    </div>
   </div>
  </div>
  <button v-if="current" class="follow-button" type="button" aria-label="回到当前知识点" data-tooltip="回到当前" @click="emit('change',current)"><NotebookIcon name="return"/></button>
  <slot/>
 </div>
</template>
