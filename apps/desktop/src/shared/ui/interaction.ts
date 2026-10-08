import {ref} from 'vue'
const key='studyflow:interaction-sound:v1'
const volumeKey='studyflow:interaction-sound-volume:v2'
function storedPreference(){try{return localStorage.getItem(key)==='on'}catch{return false}}
function storedVolume(){try{const raw=localStorage.getItem(volumeKey);if(raw===null)return 72;const value=Number(raw);return Number.isFinite(value)&&value>=0&&value<=100?value:72}catch{return 72}}
export const soundEnabled=ref(storedPreference())
export const soundVolume=ref(storedVolume())
export function setSoundEnabled(value:boolean){soundEnabled.value=value;try{localStorage.setItem(key,value?'on':'off')}catch{/* Preference can remain session-only. */}}
export function setSoundVolume(value:number){const next=Math.max(0,Math.min(100,Math.round(Number(value)||0)));soundVolume.value=next;try{localStorage.setItem(volumeKey,String(next))}catch{/* Preference can remain session-only. */}}
let context:AudioContext|undefined,last=0
export function interactionFeedback(kind:'open'|'move'|'complete'|'preview') {
 if(!soundEnabled.value||soundVolume.value<=0||document.visibilityState==='hidden'||!document.hasFocus()||document.documentElement.dataset.themeSound==='muted')return
 const now=Date.now();if(now-last<120)return;last=now
 try {
  context??=new AudioContext()
  const audio=context
  void audio.resume().then(()=>{
   if(!soundEnabled.value||soundVolume.value<=0||document.visibilityState==='hidden'||!document.hasFocus()||document.documentElement.dataset.themeSound==='muted')return
   const glass=document.documentElement.dataset.themeSound==='glass'
   const frequencies=(kind==='complete'?[523.25,659.25]:kind==='move'?[392]:kind==='open'?[440]:[440,554.37]).map(hz=>glass?hz*1.18:hz)
   const peak=Math.max(.018,.08*(soundVolume.value/100))
   frequencies.forEach((hz,i)=>{
    const oscillator=audio.createOscillator(),gain=audio.createGain(),start=audio.currentTime+i*.08
    oscillator.type=glass?'triangle':'sine';oscillator.frequency.value=hz
    gain.gain.setValueAtTime(0,start);gain.gain.linearRampToValueAtTime(peak,start+.012);gain.gain.exponentialRampToValueAtTime(.0001,start+.13)
    oscillator.connect(gain);gain.connect(audio.destination);oscillator.start(start);oscillator.stop(start+.15)
    oscillator.onended=()=>{oscillator.disconnect();gain.disconnect()}
   })
  }).catch(()=>{/* Muted or unavailable audio must never block work. */})
 }catch{/* Audio is optional; all feedback remains visible as text. */}
}
if(typeof window!=='undefined')window.addEventListener('storage',event=>{
 if(event.key===key)soundEnabled.value=event.newValue==='on'
 if(event.key===volumeKey){const value=Number(event.newValue);if(Number.isFinite(value))soundVolume.value=Math.max(0,Math.min(100,Math.round(value)))}
})
