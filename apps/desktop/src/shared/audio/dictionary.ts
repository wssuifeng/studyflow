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
let generation=0,player:HTMLAudioElement|null=null,cancelPlayback:(()=>void)|null=null,systemPlaying=false
export function saveSpeechPreferences(){try{localStorage.setItem(preferenceKey,JSON.stringify({volume:speechVolume.value,muted:speechMuted.value,auto:speechAuto.value,accent:speechAccent.value}))}catch{/* Optional preferences. */}}
export function stopSpeech(){generation++;cancelPlayback?.();cancelPlayback=null;if(player){player.pause();player.src='';player=null}if(systemPlaying){globalThis.speechSynthesis?.cancel();systemPlaying=false}}
async function playSystem(result:DictionaryInfo,token:number) {
 const synth=globalThis.speechSynthesis
 if(!synth||typeof SpeechSynthesisUtterance==='undefined')throw new Error('整句发音暂不可用；本机没有可用英文声音，文字训练可继续。')
 let voices=synth.getVoices().filter(v=>/^en[-_]/i.test(v.lang))
 if(!voices.length){await new Promise<void>(resolve=>{const done=()=>{clearTimeout(timer);synth.removeEventListener('voiceschanged',done);resolve()};const timer=setTimeout(done,500);synth.addEventListener('voiceschanged',done)});voices=synth.getVoices().filter(v=>/^en[-_]/i.test(v.lang))}
 if(token!==generation)return null
 const voice=voices.find(v=>v.lang.toLowerCase()===speechAccent.value.toLowerCase())||voices[0]
 if(!voice)throw new Error('词典整句发音暂不可用，本机未安装英文声音。可继续文字训练或稍后重试。')
 const utterance=new SpeechSynthesisUtterance(result.target);utterance.voice=voice;utterance.lang=voice.lang;utterance.volume=speechVolume.value/100;utterance.rate=.9
 await new Promise<void>((resolve,reject)=>{
  let done=false
  const finish=(error?:Error)=>{if(done)return;done=true;clearTimeout(timer);cancelPlayback=null;utterance.onstart=null;utterance.onerror=null;error?reject(error):resolve()}
  const timer=setTimeout(()=>{synth.cancel();systemPlaying=false;finish(new Error('本机朗读未启动，可用快捷键重试。'))},4000)
  cancelPlayback=()=>{synth.cancel();systemPlaying=false;finish()}
  utterance.onstart=()=>finish();utterance.onerror=()=>{systemPlaying=false;finish(new Error('本机朗读不可用，可继续文字训练。'))};utterance.onend=()=>{if(token===generation)systemPlaying=false}
  systemPlaying=true;synth.speak(utterance)
 })
 if(token!==generation)return null
 return {...result,playback_provider:'system' as const,accent_verified:false,notice:'已使用本机英文声音朗读。'}
}
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
  const fallbackAccent:'en-US'|'en-GB'=result.requested_accent==='en-US'?'en-GB':'en-US'
  const alternate=new URL(url.href);alternate.searchParams.set('type',fallbackAccent==='en-US'?'2':'1')
  // A phrase can exist for one dictionary voice but not the other. Retry once
  // at the same allowlisted provider, without changing the user's preference.
  for(const [index,candidate] of [url,alternate].entries()){
   if(token!==generation)return null
   player=new Audio(candidate.href);player.volume=speechVolume.value/100
   try {
    await new Promise<void>((resolve,reject)=>{
     const audio=player!;let done=false
     const cleanup=()=>{if(done)return;done=true;clearTimeout(deadline);audio.oncanplay=null;audio.onerror=null;cancelPlayback=null}
     const deadline=setTimeout(()=>{cleanup();audio.pause();reject(new Error('词典发音未及时加载，可稍后重试。'))},3000)
     cancelPlayback=()=>{cleanup();resolve()}
     audio.oncanplay=()=>{void audio.play().then(()=>{cleanup();resolve()},error=>{cleanup();reject(error)})}
     audio.onerror=()=>{cleanup();reject(new Error('词典发音暂不可用，可继续文字训练。'))}
     audio.load()
    })
    if(token!==generation)return null
    if(index===1)return {...result,playback_provider:'dictionary' as const,playback_accent:fallbackAccent,accent_verified:false,notice:`所选口音暂不可用，已用${fallbackAccent==='en-US'?'美音':'英音'}朗读。`}
    return result
   }catch(error){
    if(token!==generation)return null
    if(player){player.pause();player.src='';player=null}
    if(index===1)return playSystem(result,token)
   }
  }

  if(token!==generation)return null
 }
 return result
}
