import {ref} from 'vue'
import {engineCall} from '../api'
import type {DictionaryInfo} from '../api/contracts/english'
const preferenceKey='studyflow:english-speech:v1'
function preferences(){try{return JSON.parse(localStorage.getItem(preferenceKey)||'{}')}catch{return {}}}
const saved=preferences()
export const speechVolume=ref(typeof saved.volume==='number'?Math.max(0,Math.min(100,saved.volume)):80)
export const speechMuted=ref(saved.muted===true)
export const speechAuto=ref(saved.auto!==false)
export const speechAccent=ref<'en-US'|'en-GB'>(saved.accent==='en-GB'?'en-GB':'en-US')
let metadataFlight:Promise<DictionaryInfo>|null=null
let generation=0,player:HTMLAudioElement|null=null,cancelPlayback:(()=>void)|null=null
export function saveSpeechPreferences(){try{localStorage.setItem(preferenceKey,JSON.stringify({volume:speechVolume.value,muted:speechMuted.value,auto:speechAuto.value,accent:speechAccent.value}))}catch{/* Optional preferences. */}}
export function stopSpeech(){generation++;cancelPlayback?.();cancelPlayback=null;if(player){player.pause();player.src='';player=null}}
export async function playDictionary(studyId:string,exerciseId:string,wordIndex?:number){
 stopSpeech();const token=generation
 if(metadataFlight)await metadataFlight.catch(()=>null)
 if(token!==generation)return null
 const request=engineCall<DictionaryInfo>('audio.dictionary.lookup',{study_session_id:studyId,exercise_id:exerciseId,word_index:wordIndex??null,accent:speechAccent.value});metadataFlight=request
 let result:DictionaryInfo
 try{result=await request}catch(error){if(token!==generation)return null;throw error}finally{if(metadataFlight===request)metadataFlight=null}
 if(token!==generation)return null
 if(!speechMuted.value&&speechVolume.value>0){
  const url=new URL(result.pronunciation_url)
  if(url.protocol!=='https:'||url.hostname!=='dict.youdao.com')throw new Error('词典音频来源不受支持。')
  player=new Audio(url.href);player.volume=speechVolume.value/100
  try {
   await new Promise<void>((resolve,reject)=>{
    const audio=player!;let done=false
    const cleanup=()=>{if(done)return;done=true;clearTimeout(deadline);audio.oncanplay=null;audio.onerror=null;cancelPlayback=null}
    const deadline=setTimeout(()=>{cleanup();audio.pause();reject(new Error('词典发音未及时加载，可稍后重试。'))},6500)
    cancelPlayback=()=>{cleanup();resolve()}
    audio.oncanplay=()=>{void audio.play().then(()=>{cleanup();resolve()},error=>{cleanup();reject(error)})}
    audio.onerror=()=>{cleanup();reject(new Error('词典发音暂不可用，可继续文字训练。'))}
    audio.load()
   })
  }catch(error){if(token!==generation)return null;throw error}
  if(token!==generation)return null
 }
 return result
}
