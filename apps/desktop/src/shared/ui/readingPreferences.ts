import {reactive} from 'vue'
const defaults={font:15,lineHeight:1.85,width:850}
export const readingPreferences=reactive({...defaults})
/**
 * 展示层钩子：阅读偏好改变后由主题展示层重算派生变量（主题标度/阅读上限）。
 * 用回调而不是 import：readingPreferences 在 main.ts 中最先被导入，
 * 直接 import 展示层会形成模块环。
 */
let presentationHook:(()=>void)|undefined
export function onReadingPreferencesChanged(hook:()=>void){presentationHook=hook}
export function applyReadingPreferences(){
 const p=readingPreferences
 p.font=Math.max(13,Math.min(22,Number(p.font)||15));p.lineHeight=Math.max(1.5,Math.min(2.3,Number(p.lineHeight)||1.85));p.width=Math.max(560,Math.min(1100,Number(p.width)||850))
 document.documentElement.style.setProperty('--reading-font',p.font+'px');document.documentElement.style.setProperty('--reading-line-height',String(p.lineHeight));document.documentElement.style.setProperty('--reading-width',p.width+'px')
 try{localStorage.setItem('studyflow-reading-preferences',JSON.stringify(p))}catch{/* Preference failures never block study. */}
 try{presentationHook?.()}catch{/* 展示派生失败不影响阅读偏好本身。 */}
}
export function resetReadingPreferences(){Object.assign(readingPreferences,defaults);applyReadingPreferences()}
try{Object.assign(readingPreferences,JSON.parse(localStorage.getItem('studyflow-reading-preferences')||'{}'))}catch{/* defaults */}
applyReadingPreferences()
