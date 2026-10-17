<script setup lang="ts">
import {computed} from 'vue'
import type {EnglishReference} from '../../../shared/api/contracts/english'
const props=withDefaults(defineProps<{reference:EnglishReference;showRoles?:boolean}>(),{showRoles:true})
const fallbackMeaning=computed(()=>props.reference.gloss?.trim()||'')
const fallbackPhonetic=computed(()=>props.reference.phonetic?.trim()||'')
const parts=computed(()=>{
 const authored=props.reference.sentence_parts||[]
 if(props.showRoles||!authored.length)return authored
 // Phrase scaffolding retains authored word metadata, not its future clause roles.
 return [{role:'other' as const,start:0,end:props.reference.tokens.length,words:authored.flatMap(part=>part.words)}]
})
const hasWordPhonetics=computed(()=>parts.value.some(part=>part.words.some(word=>word.phonetic?.trim())))
const hasWordGloss=computed(()=>parts.value.some(part=>part.words.some(word=>word.gloss?.trim())))
const labels={subject:'主语',predicate:'谓语',object:'宾语',complement:'补语',modifier:'修饰',other:'其他'}
const emit=defineEmits<{word:[index:number]}>()
</script>
<template>
 <section :class="['english-breakdown',{'has-word-phonetics':hasWordPhonetics,'has-word-gloss':hasWordGloss}]" :aria-label="showRoles?'本句解析':'词语解析'">
  <p v-if="parts.length&&fallbackPhonetic&&!hasWordPhonetics" class="authored-pronunciation">{{fallbackPhonetic}}</p>
  <div v-if="parts.length" class="sentence-parts">
   <div v-for="(part,index) in parts" :key="index" :class="['sentence-part',showRoles?'role-'+part.role:'part-neutral']">
    <span v-if="showRoles" class="part-role">{{labels[part.role]}}</span>
    <button v-for="(word,n) in part.words" :key="n" type="button" class="part-word" :aria-label="'朗读单词 '+reference.tokens[part.start+n]" @click="emit('word',part.start+n)">
     <small v-if="hasWordPhonetics" :aria-hidden="!word.phonetic" :title="word.phonetic||undefined">{{word.phonetic}}</small>
     <strong>{{reference.tokens[part.start+n]}}</strong>
     <span :title="word.gloss||undefined">{{word.gloss}}</span>
     <em v-if="word.pos">{{word.pos}}</em>
    </button>
   </div>
  </div>
  <div v-else class="breakdown-fallback">
   <div class="sentence-parts fallback-words" aria-label="英文词语">
    <button v-for="(word,index) in reference.tokens" :key="index" type="button" class="part-word" :aria-label="'朗读单词 '+word" @click="emit('word',index)"><strong>{{word}}</strong></button>
   </div>
   <span v-if="fallbackPhonetic" class="fallback-phonetic">{{fallbackPhonetic}}</span>
   <p v-if="fallbackMeaning" class="fallback-meaning">{{fallbackMeaning}}</p>
  </div>
  <p v-if="reference.explanation" class="breakdown-explanation">{{reference.explanation}}</p>
 </section>
</template>
