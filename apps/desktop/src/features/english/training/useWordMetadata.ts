import {computed,ref,watch,onBeforeUnmount,type Ref} from 'vue'
import {engineCall} from '../../../shared/api'
import {speechAccent} from '../../../shared/audio/dictionary'
import type {EnglishReference} from '../../../shared/api/contracts/english'
export type WordMetadata={word_index:number;word:string;phonetic?:string;metadata_status?:string;definitions?:{part_of_speech:string;definition:string}[];accent_verified?:boolean}
export function useWordMetadata(scope:Ref<string>,study:Ref<string>,exercise:Ref<string>,reference:Ref<EnglishReference|null>,enabled:Ref<boolean>){
 const words=ref<Record<number,WordMetadata>>({}),status=ref(''),retry=ref(0)
 let generation=0,timer:ReturnType<typeof setTimeout>|undefined,disposed=false
 const cancel=()=>{generation++;clearTimeout(timer)}
 watch([scope,study,exercise,()=>reference.value?.target,speechAccent,enabled,retry],()=>{
  cancel();words.value={};status.value=''
  if(!enabled.value||!reference.value||!exercise.value)return
  const token=generation,target=reference.value.target,id=exercise.value,sid=study.value,accent=speechAccent.value
  const fetch=async(round:number)=>{
   if(token!==generation||disposed)return
   status.value='loading'
   try{
    const data=await engineCall<{target:string;words:WordMetadata[];requested_accent:string}>('audio.dictionary.metadata',{study_session_id:sid,exercise_id:id,accent})
    if(token!==generation||disposed)return
    if(data.target!==target||data.requested_accent!==accent){status.value='unavailable';return}
    words.value=Object.fromEntries(data.words.filter(w=>reference.value?.tokens[w.word_index]===w.word).map(w=>[w.word_index,w]))
    const pending=data.words.some(w=>['loading','deferred'].includes(w.metadata_status||''))
    status.value=pending?'loading':data.words.some(w=>w.phonetic)?'ready':'unavailable'
    if(pending&&round<3)timer=setTimeout(()=>void fetch(round+1),[400,900,1800][round])
    else if(pending)status.value='deferred'
   }catch{if(token===generation&&!disposed)status.value='unavailable'}
  };void fetch(0)
 },{immediate:true})
 onBeforeUnmount(()=>{disposed=true;cancel()})
 return {words,status,refresh:()=>retry.value++,notice:computed(()=>status.value==='loading'?'词典音标后台读取中…':status.value==='deferred'?'部分词语尚未返回，可稍后重试。':status.value==='unavailable'?'词典辅助暂不可用；课程标注仍保留。':status.value==='ready'?'词典为单词级音标，未核实口音；不代表整句连读。':'')}
}
