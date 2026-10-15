<script setup lang="ts">
import {nextTick,ref} from 'vue'
import type {EnglishDifference} from '../../../shared/api/contracts/english'
import {inputAdvance} from './shortcuts'
import {playKeyboardSound} from '../../../shared/audio/keyboard'
const props=defineProps<{modelValue:string[];differences?:EnglishDifference[];disabled?:boolean;hintTokens?:string[];minimum?:number;maximum?:number}>()
const emit=defineEmits<{'update:modelValue':[string[]];edited:[];check:[]}>()
const elements:HTMLInputElement[]=[]
const focusedIndex=ref(0)
function focusWord(index:number,select=true){elements[index]?.focus();if(select)elements[index]?.select()}
function input(index:number,event:Event){const values=[...props.modelValue];values[index]=(event.target as HTMLInputElement).value;emit('update:modelValue',values);emit('edited')}
function key(event:KeyboardEvent,index:number){
 if(event.isComposing||event.key==='Process')return
 playKeyboardSound(event)
 if(event.repeat||event.ctrlKey||event.metaKey||event.altKey)return
 if(event.key==='Enter'||event.key===' '){
  event.preventDefault()
  if(event.key===' '&&index===props.modelValue.length-1&&props.modelValue[index]?.trim()&&index<(props.maximum||props.modelValue.length)-1){
   emit('update:modelValue',[...props.modelValue,'']);void nextTick(()=>focusWord(index+1));return
  }
  const next=inputAdvance(event.key,index,props.modelValue,props.minimum||props.modelValue.length)
  if(next==='check')emit('check');else if(typeof next==='number')focusWord(next)
 }else if(event.key==='Backspace'&&!props.modelValue[index]&&index>0){event.preventDefault();focusWord(index-1)}
}
async function paste(event:ClipboardEvent,index:number){const text=event.clipboardData?.getData('text')||'',words=text.trim().split(/\s+/);if(words.length<2)return;event.preventDefault();const values=[...props.modelValue];words.slice(0,(props.maximum||80)-index).forEach((word,i)=>values[index+i]=word);emit('update:modelValue',values);emit('edited');await nextTick();focusWord(Math.min(index+words.length-1,values.length-1))}
defineExpose({focusWord,focusedIndex})
</script>
<template>
 <div class="english-token-row" aria-label="英语答案输入">
  <div v-for="(word,index) in modelValue" :key="index" :class="['english-token',{incorrect:differences?.some(d=>d.index===index),focused:focusedIndex===index}]">
   <span v-if="hintTokens?.[index]&&focusedIndex===index" class="english-word-hint" role="status">{{hintTokens[index]}}</span>
   <input :ref="el=>{elements[index]=el as HTMLInputElement}" :value="word" :disabled="disabled" :style="{width:Math.min(23,Math.max(3,word.length+1))+'ch'}" :aria-label="'第 '+(index+1)+' 个单词'" :aria-invalid="differences?.some(d=>d.index===index)||undefined" autocapitalize="off" autocomplete="off" spellcheck="false" @focus="focusedIndex=index" @input="input(index,$event)" @keydown="key($event,index)" @paste="paste($event,index)"/>
   <small v-if="differences?.find(d=>d.index===index)?.actual">原输入：{{differences?.find(d=>d.index===index)?.actual}}</small>
  </div>
 </div>
</template>
