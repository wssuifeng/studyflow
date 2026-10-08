import { computed, shallowRef, ref } from 'vue'
import { emit, listen, type UnlistenFn } from '@tauri-apps/api/event'
import { builtinThemes } from './catalog'
import { DEFAULT_THEME, TOKEN_PROPERTIES, type Theme, type ThemeToken } from './contract'
import { createThemeController, type ThemeSnapshot, type DisplaySnapshot, type ThemeResult } from './controller'
import {
  DISPLAY_STORAGE_KEY, initializeDisplayPreferences, rememberTheme, setImageIntensity, setTypographyPreference,
  reapply, activeDisplay, imageIntensity, typographyPreference, displayNotice, type ImageIntensity, type TypographyPreference,
} from './display-loader'

export const THEME_STORAGE_KEY = 'studyflow:theme-preference:v1'
const updatedEvent = 'studyflow-theme-updated', requestEvent = 'studyflow-theme-request'
const displayUpdatedEvent = 'studyflow-theme-display-updated', displayRequestEvent = 'studyflow-theme-display-request'
const origin = crypto.randomUUID()
const native = '__TAURI_INTERNALS__' in window
const transportNotice = ref('')
let started = false, channel: BroadcastChannel | undefined
let nativeReady = false, unlisteners: UnlistenFn[] = []
function apply(theme: Theme) {
  const root = document.documentElement
  root.dataset.theme = theme.appearance
  root.dataset.themeId = theme.id
  root.dataset.themeDensity = theme.presentation.density
  root.dataset.themeHeading = theme.presentation.heading
  root.dataset.themeTeaching = theme.presentation.teaching
  root.dataset.themeMotion = theme.motion_profile
  root.dataset.themeSound = theme.sound_profile
  root.style.colorScheme = theme.appearance
  for (const token of Object.keys(TOKEN_PROPERTIES) as ThemeToken[]) root.style.setProperty(TOKEN_PROPERTIES[token], theme.tokens[token])
  // 展示包（布局/几何/排版/素材）在同一入口应用；只改呈现，不重挂组件。
  rememberTheme(theme)
}
function publish(snapshot: ThemeSnapshot) {
  try { channel?.postMessage({ type: 'updated', snapshot }) } catch { /* Native/storage sync may remain available. */ }
  if (nativeReady) void emit(updatedEvent, snapshot).catch(() => { transportNotice.value = '主题已生效；原生窗口同步暂不可用，可关闭后重新打开工具窗。' })
}
function publishDisplay(snapshot: DisplaySnapshot) {
  try { channel?.postMessage({ type: 'display', snapshot }) } catch { /* Native/storage sync may remain available. */ }
  if (nativeReady) void emit(displayUpdatedEvent, snapshot).catch(() => { /* 展示同步失败只影响其他窗口。 */ })
}
function applyDisplayPreferences(snapshot: DisplaySnapshot) {
  setImageIntensity(snapshot.image_intensity)
  setTypographyPreference(snapshot.typography)
}
initializeDisplayPreferences()
const controller = createThemeController(builtinThemes, {
  origin, now: Date.now,
  read: () => localStorage.getItem(THEME_STORAGE_KEY),
  write: text => localStorage.setItem(THEME_STORAGE_KEY, text),
  readDisplay: () => localStorage.getItem(DISPLAY_STORAGE_KEY),
  writeDisplay: text => localStorage.setItem(DISPLAY_STORAGE_KEY, text),
  apply, publish, publishDisplay, applyDisplayPreferences,
})
export const themeState = shallowRef(controller.view())
export const availableThemes = computed(() => themeState.value.themes)
export const activeTheme = computed(() => themeState.value.theme)
export const themeNotice = computed(() => themeState.value.notice || displayNotice.value || transportNotice.value)
export { activeDisplay, imageIntensity, typographyPreference }
function refresh() { themeState.value = controller.view() }
function receive(payload: unknown) { if (controller.receive(payload)) refresh() }
function receiveDisplay(payload: unknown) { if (controller.receiveDisplay(payload)) refresh() }
function storageUpdated(event: StorageEvent) {
  if (event.key === DISPLAY_STORAGE_KEY && event.newValue) {
    try { receiveDisplay(JSON.parse(event.newValue)) } catch { /* 坏的展示偏好不能替换已校验的展示。 */ }
    return
  }
  if (event.key !== THEME_STORAGE_KEY || !event.newValue) return
  try { receive(JSON.parse(event.newValue)) } catch { /* A bad remote preference cannot replace a validated theme. */ }
}
function syncStored() {
  try {
    const display = localStorage.getItem(DISPLAY_STORAGE_KEY)
    if (display) receiveDisplay(JSON.parse(display))
    const text = localStorage.getItem(THEME_STORAGE_KEY)
    if (text) receive(JSON.parse(text))
  } catch { /* Session-only preferences still work. */ }
}
export function initializeThemes() {
  if (started) return
  started = true
  window.addEventListener('storage', storageUpdated)
  window.addEventListener('focus', syncStored)
  // Browser previews also sync when preference storage is blocked. No server is involved.
  if (!native && typeof BroadcastChannel !== 'undefined') {
    try {
      channel = new BroadcastChannel(THEME_STORAGE_KEY)
      channel.onmessage = event => {
        if (event.data?.type === 'updated') receive(event.data.snapshot)
        else if (event.data?.type === 'display') receiveDisplay(event.data.snapshot)
        else if (event.data?.type === 'request' && event.data.origin !== origin) {
          channel?.postMessage({ type: 'updated', snapshot: controller.snapshot() })
          channel?.postMessage({ type: 'display', snapshot: controller.displaySnapshot() })
        }
      }
      channel.postMessage({ type: 'request', origin })
    } catch { channel = undefined; transportNotice.value = '实时窗口同步暂不可用，主题仍可在本窗口使用。' }
  }
  if (native) void (async () => {
    try {
      unlisteners.push(await listen<ThemeSnapshot>(updatedEvent, event => receive(event.payload)))
      unlisteners.push(await listen<DisplaySnapshot>(displayUpdatedEvent, event => receiveDisplay(event.payload)))
      unlisteners.push(await listen<string>(requestEvent, event => {
        if (event.payload !== origin) void emit(updatedEvent, controller.snapshot()).catch(() => {})
      }))
      unlisteners.push(await listen<string>(displayRequestEvent, event => {
        if (event.payload !== origin) void emit(displayUpdatedEvent, controller.displaySnapshot()).catch(() => {})
      }))
      if (!started) { unlisteners.splice(0).forEach(unlisten => unlisten()); return }
      nativeReady = true
      // A new tool window asks live peers too, not just potentially unavailable storage.
      await emit(requestEvent, origin)
      await emit(displayRequestEvent, origin)
      await emit(updatedEvent, controller.snapshot())
      await emit(displayUpdatedEvent, controller.displaySnapshot())
    } catch {
      unlisteners.splice(0).forEach(unlisten => unlisten())
      nativeReady = false
      transportNotice.value = '原生窗口同步暂不可用；本窗口仍可切换主题。'
    }
  })()
}
function action(result: ThemeResult) { refresh(); return result }
export function selectTheme(id: string) { return action(controller.select(id)) }
export function importTheme(text: string) { return action(controller.importTheme(text)) }
export function exportTheme() { return controller.exportTheme() }
export function removeTheme(id: string) { return action(controller.removeTheme(id)) }
export function resetTheme() { return selectTheme(DEFAULT_THEME.id) }
/** 展示偏好（排版标度/行距/图像强度）：与主题偏好分开保存，切换主题不会重置。 */
export function setDisplayOptions(next: { typography?: TypographyPreference; image_intensity?: ImageIntensity }) {
  return action(controller.setDisplayPreferences(next))
}
export function exportDisplayPreference() { return JSON.stringify(controller.displaySnapshot(), null, 2) + '\n' }
/** 阅读偏好（字号/行距/宽度）改变后重算派生变量；不重挂组件、不动输入焦点。 */
export function refreshReadingPresentation() { reapply() }
function dispose() {
  started = false; nativeReady = false
  window.removeEventListener('beforeunload', dispose)
  window.removeEventListener('storage', storageUpdated)
  window.removeEventListener('focus', syncStored)
  channel?.close(); channel = undefined
  unlisteners.splice(0).forEach(unlisten => unlisten())
}
window.addEventListener('beforeunload', dispose, { once: true })
if (import.meta.hot) import.meta.hot.dispose(dispose)
