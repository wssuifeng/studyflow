<script setup lang="ts">
import {nextTick} from 'vue'
import type {EnglishDifference} from '../../../shared/api/contracts/english'
const props=defineProps<{modelValue:string[];differences?:EnglishDifference[];disabled?:boolean}>()
const emit=defineEmits<{'update:modelValue':[string[]];edited:[];check:[]}>()
const elements:HTMLInputElement[]=[]
function focusWord(index:number){elements[index]?.focus();elements[index]?.select()}
function input(index:number,event:Event){const values=[...props.modelValue];values[index]=(event.target as HTMLInputElement).value;emit('update:modelValue',values);emit('edited')}
function key(event:KeyboardEvent,index:number){if(event.isComposing||event.repeat||event.key==='Process')return;if(event.key==='Enter'||event.key===' '){event.preventDefault();if(!props.modelValue[index]?.trim())return;if(index<props.modelValue.length-1)focusWord(index+1);else emit('check')}else if(event.key==='Backspace'&&!props.modelValue[index]&&index>0){event.preventDefault();focusWord(index-1)}}
async function paste(event:ClipboardEvent,index:number){const text=event.clipboardData?.getData('text')||'',words=text.trim().split(/\s+/);if(words.length<2)return;event.preventDefault();const values=[...props.modelValue];words.forEach((word,i)=>values[index+i]=word);emit('update:modelValue',values);emit('edited');await nextTick();focusWord(Math.min(index+words.length-1,values.length-1))}
defineExpose({focusWord})
</script>
<template><div class="english-token-row" aria-label="英语答案输入"><div v-for="(word,index) in modelValue" :key="index" :class="['english-token',{incorrect:differences?.some(d=>d.index===index)}]"><input :ref="el=>{elements[index]=el as HTMLInputElement}" :value="word" :disabled="disabled" :style="{width:Math.min(23,Math.max(3,word.length+1))+'ch'}" :aria-label="'第 '+(index+1)+' 个单词'" :aria-invalid="differences?.some(d=>d.index===index)||undefined" autocapitalize="off" autocomplete="off" spellcheck="false" @input="input(index,$event)" @keydown="key($event,index)" @paste="paste($event,index)"/><small v-if="differences?.find(d=>d.index===index)?.actual">原输入：{{differences?.find(d=>d.index===index)?.actual}}</small></div></div></template>
