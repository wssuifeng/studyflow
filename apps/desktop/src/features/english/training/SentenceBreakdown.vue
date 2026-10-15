<script setup lang="ts">
import {computed} from 'vue'
import type {EnglishReference} from '../../../shared/api/contracts/english'
import type {WordMetadata} from './useWordMetadata'
const props=defineProps<{reference:EnglishReference;metadata?:Record<number,WordMetadata>}>()
const fallbackMeaning=computed(()=>props.reference.gloss?.trim()||'')
const fallbackPhonetic=computed(()=>props.reference.phonetic?.trim()||'')
const labels={subject:'主语',predicate:'谓语',object:'宾语',complement:'补语',modifier:'修饰',other:'其他'}
const emit=defineEmits<{word:[index:number]}>()
</script>
<template>
 <section class="english-breakdown" aria-label="本句解析">
  <div v-if="reference.sentence_parts?.length" class="sentence-parts">
   <div v-for="(part,index) in reference.sentence_parts" :key="index" :class="['sentence-part','role-'+part.role]">
    <span class="part-role">{{labels[part.role]}}</span>
    <button v-for="(word,n) in part.words" :key="n" type="button" class="part-word" :aria-label="'朗读单词 '+reference.tokens[part.start+n]" @click="emit('word',part.start+n)">
     <small v-if="word.phonetic||metadata?.[part.start+n]?.phonetic" :title="word.phonetic?'课程标注':'词典音标，口音未核实'">{{word.phonetic||metadata?.[part.start+n]?.phonetic}}</small><strong>{{reference.tokens[part.start+n]}}</strong><span>{{word.gloss}}</span><em v-if="word.pos">{{word.pos}}</em>
    </button>
   </div>
  </div>
  <div v-else class="breakdown-fallback">
   <div class="sentence-parts fallback-words" aria-label="英文词语">
    <button v-for="(word,index) in reference.tokens" :key="index" type="button" class="part-word" :aria-label="'朗读单词 '+word" @click="emit('word',index)"><small v-if="metadata?.[index]?.phonetic" title="词典音标，口音未核实">{{metadata?.[index]?.phonetic}}</small><strong>{{word}}</strong></button>
   </div>
   <span v-if="fallbackPhonetic" class="fallback-phonetic">{{fallbackPhonetic}}</span>
   <p v-if="fallbackMeaning" class="fallback-meaning">{{fallbackMeaning}}</p>
  </div>
  <p v-if="reference.explanation" class="breakdown-explanation">{{reference.explanation}}</p>
 </section>
</template>
