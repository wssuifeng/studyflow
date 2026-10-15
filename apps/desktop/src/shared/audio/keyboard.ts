import {ref} from 'vue'
const preferenceKey = 'studyflow:english-keyboard:v1'
type Preferences = {enabled?: boolean; volume?: number; asset?: string; name?: string}
function stored(): Preferences {try {const value=JSON.parse(localStorage.getItem(preferenceKey) || '{}');return value && typeof value==='object' && !Array.isArray(value) ? value : {}} catch {return {}}}
const saved = stored()
export const keyboardEnabled = ref(saved.enabled !== false)
export const keyboardVolume = ref(Number.isFinite(saved.volume) ? Math.max(0, Math.min(100, saved.volume!)) : 38)
export const keyboardAudioName = ref(typeof saved.name==='string' ? saved.name.slice(0,80) : '内置轻键音')
let asset = typeof saved.asset === 'string' && /^data:audio\/(mpeg|wav|ogg);base64,/.test(saved.asset) && saved.asset.length < 750000 ? saved.asset : ''
let context: AudioContext|undefined, buffer: AudioBuffer|undefined, builtin: AudioBuffer|undefined, decoding: Promise<void>|null = null, generation = 0, last = -Infinity
export function saveKeyboardPreferences() {
  try {localStorage.setItem(preferenceKey, JSON.stringify({enabled: keyboardEnabled.value, volume: keyboardVolume.value, asset, name: keyboardAudioName.value}))} catch {/* Optional, bounded local preferences. */}
}
function getContext() {
  context ??= new AudioContext()
  if (!builtin) {
    builtin = context.createBuffer(1, Math.ceil(context.sampleRate * .032), context.sampleRate)
    const samples = builtin.getChannelData(0)
    let random = 31, previous = 0
    for (let index=0; index<samples.length; index++) {
      random = (Math.imul(random, 1664525) + 1013904223) | 0
      const noise = ((random >>> 0) / 2147483648 - 1)
      previous = previous * .45 + noise * .55
      samples[index] = (previous * .38 + Math.sin(index * 2 * Math.PI * 1350 / context.sampleRate) * .25) * Math.exp(-index / (context.sampleRate * .006))
    }
  }
  return context
}
function decodeStored() {
  if (!asset || buffer || decoding) return
  const current = generation
  try {
    const bytes = Uint8Array.from(atob(asset.split(',')[1]), letter => letter.charCodeAt(0))
    decoding = getContext().decodeAudioData(bytes.buffer).then(decoded => {if (generation === current) buffer = decoded}).catch(() => {/* Built-in sound remains usable. */}).finally(() => {decoding = null})
  } catch {/* Invalid local asset cannot interrupt typing. */}
}
export function keyboardEventHasSound(event: Pick<KeyboardEvent,'key'|'altKey'|'ctrlKey'|'metaKey'|'isComposing'>) {
  return !event.isComposing && !event.altKey && !event.ctrlKey && !event.metaKey && (/^[a-zA-Z0-9'.,;-]$/.test(event.key) || ['Backspace',' '].includes(event.key))
}
export function playKeyboardSound(event: KeyboardEvent) {
  if (!keyboardEnabled.value || keyboardVolume.value <= 0 || !keyboardEventHasSound(event) || document.visibilityState === 'hidden') return
  const now = performance.now(); if (now - last < 60) return; last = now
  try {
    const audio = getContext(); decodeStored()
    const play = () => {
      if (!keyboardEnabled.value || keyboardVolume.value <= 0) return
      const source = audio.createBufferSource(), gain = audio.createGain()
      source.buffer = buffer || builtin!; gain.gain.value = Math.max(0, Math.min(100, keyboardVolume.value)) / 100
      source.connect(gain); gain.connect(audio.destination); source.start()
      source.onended = () => {source.disconnect(); gain.disconnect()}
    }
    if (audio.state === 'suspended') void audio.resume().then(play).catch(() => {})
    else play()
  } catch {/* Audio never holds a save, check, or keyboard event. */}
}
export async function importKeyboardAudio(file: File) {
  if (!/\.(mp3|wav|ogg)$/i.test(file.name) || file.size <= 0 || file.size > 512 * 1024) throw new Error('请选择512KB以内的MP3、WAV或OGG键音文件。')
  const bytes = await file.arrayBuffer()
  let decoded: AudioBuffer
  try {decoded = await getContext().decodeAudioData(bytes.slice(0))} catch {throw new Error('此音频无法解码，原键音设置未改变。')}
  if (decoded.duration > 2) throw new Error('键音需为2秒以内的短音效，原设置未改变。')
  const encoded = await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = () => reject(new Error('本地音频读取失败。')); reader.readAsDataURL(new Blob([bytes], {type: /\.wav$/i.test(file.name) ? 'audio/wav' : /\.ogg$/i.test(file.name) ? 'audio/ogg' : 'audio/mpeg'}))})
  generation++; asset = encoded; buffer = decoded; keyboardAudioName.value = file.name; saveKeyboardPreferences()
}
export function resetKeyboardAudio() {generation++; asset = ''; buffer = undefined; keyboardAudioName.value = '内置轻键音'; saveKeyboardPreferences()}
