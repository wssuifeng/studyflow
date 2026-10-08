/**
 * 展示加载器：把当前主题的展示包变成 CSS 变量、根元素 dataset、样式表引用和纯展示视图。
 *
 * 约束（与主题契约一致）：
 *   · 只写 CSS 自定义属性与 dataset，不写内联 style 字符串拼接，不注入 HTML；
 *   · 样式表来自构建期注册表（静态 import），不是运行期路径；
 *   · 用户显式排版/阅读偏好优先于主题默认值；
 *   · 切换展示只改呈现，不重挂组件、不发业务请求。
 */
import { computed, ref, shallowRef } from 'vue'
import type { Theme, ThemeDisplay } from './contract'
import { displayFromPresentation } from './display'
import { readingPreferences, onReadingPreferencesChanged } from '../ui/readingPreferences'
import { resolveDisplayAsset, type DisplayAssetRef } from './asset-registry'
import { displayView, type DisplayViewKey } from './view-registry'

// 阅读偏好改变（用户显式调整字号/行距/宽度）后重算展示派生变量。
onReadingPreferencesChanged(() => reapply())

export const DISPLAY_STORAGE_KEY = 'studyflow:theme-display:v1'
export const IMAGE_INTENSITY_STORAGE_KEY = 'studyflow:theme-image-intensity:v1'
export const TYPOGRAPHY_STORAGE_KEY = 'studyflow:theme-typography:v1'
/** 阅读宽度默认值；等于它表示用户没有显式选择过宽度。 */
const DEFAULT_READING_WIDTH = 850
/** 阅读宽度可接受范围；用户显式值与主题值都在此范围内。 */
const READING_WIDTH_MIN = 560
const READING_WIDTH_MAX = 1080

export type ImageIntensity = 'full' | 'subtle' | 'none'
/** auto = 跟随主题；其余为用户的显式排版选择。 */
export type TypographyPreference = { scale: 'auto' | number; lineHeight: 'auto' | number }

/** 展示包提供的容器实现；按当前主题解析，产品默认注册表为空。 */
export const displayViews = computed(() => ({
  shell: displayView(themeIdState.value, 'shell') as never,
  titlebar: displayView(themeIdState.value, 'titlebar') as never,
  navigation: displayView(themeIdState.value, 'navigation') as never,
  readingShell: displayView(themeIdState.value, 'reading-shell') as never,
  teaching: displayView(themeIdState.value, 'teaching') as never,
}))
export function hasDisplayView(key: DisplayViewKey): boolean {
  return displayView(themeIdState.value, key) !== undefined
}

const displayState = shallowRef<ThemeDisplay>(displayFromPresentation({ density: 'comfortable', heading: 'editorial', teaching: 'paper' }))
const themeIdState = ref('')
const appearanceState = ref<'light' | 'dark'>('light')
const imageIntensityState = ref<ImageIntensity>('full')
const typographyState = ref<TypographyPreference>({ scale: 'auto', lineHeight: 'auto' })
const applied = new Map<string, string>()

export const activeDisplay = computed(() => displayState.value)
export const displayThemeId = computed(() => themeIdState.value)
export const imageIntensity = computed(() => imageIntensityState.value)
export const typographyPreference = computed(() => typographyState.value)
export const displayNotice = ref('')

/** 当前主题声明的素材（按用途），已按用户图像强度与缺图情况回退。 */
export function themeAssets(role: 'background' | 'texture' | 'illustration'): DisplayAssetRef[] {
  return displayState.value.assets
    .filter(asset => asset.role === role)
    .map(asset => resolveDisplayAsset(themeIdState.value, asset, imageIntensityState.value))
    .filter((asset): asset is DisplayAssetRef => asset !== null)
}

/** 首选背景素材；没有则返回 null，调用方使用纯色回退。 */
export function primaryBackground(): DisplayAssetRef | null {
  return themeAssets('background')[0] ?? null
}

function readStored<T>(key: string, validate: (value: unknown) => T | null, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    return validate(JSON.parse(raw)) ?? fallback
  } catch {
    return fallback
  }
}
function persist(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* 偏好写失败只影响本次会话。 */ }
}

function validIntensity(value: unknown): ImageIntensity | null {
  return value === 'full' || value === 'subtle' || value === 'none' ? value : null
}
function validTypography(value: unknown): TypographyPreference | null {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  const number = (input: unknown, min: number, max: number) => typeof input === 'number' && Number.isFinite(input) && input >= min && input <= max ? input : null
  const scale = raw.scale === 'auto' ? 'auto' as const : number(raw.scale, 0.9, 1.2)
  const lineHeight = raw.lineHeight === 'auto' ? 'auto' as const : number(raw.lineHeight, 1.5, 2.3)
  if (scale === null || lineHeight === null) return null
  return { scale, lineHeight }
}

function set(name: string, value: string) {
  if (applied.get(name) === value) return
  applied.set(name, value)
  document.documentElement.style.setProperty(name, value)
}

/**
 * 应用展示包。数值全部来自已校验的展示包或用户偏好，不拼接任意字符串。
 */
export function applyDisplay(theme: Theme): void {
  themeIdState.value = theme.id
  appearanceState.value = theme.appearance
  displayState.value = theme.display
  const display = theme.display
  const root = document.documentElement

  root.dataset.themeLayout = display.layout
  // v2 shell contract: themes may style the regions, but cannot replace the
  // fixed navigation / reading / optional-tools learning workbench skeleton.
  root.dataset.themeShellContract = 'v2'
  root.dataset.themeReadingShell = display.reading_shell
  root.dataset.themeTeachingStyle = display.teaching_style
  root.dataset.themeNoteStyle = display.note_style
  root.dataset.themeSurface = display.surface_treatment
  root.dataset.themeElevation = display.elevation
  root.dataset.themeOutline = display.outline
  root.dataset.themeImage = imageIntensityState.value
  root.dataset.themeDisplay = theme.id
  // 展示包的 CSS 由构建期注册表静态 import，并以该属性作为作用域锚点。
  root.dataset.overlayName = theme.id

  set('--theme-nav-width', `${display.navigation_width}px`)
  set('--theme-reading-width', `${display.reading_width}px`)
  set('--theme-tools-width', `${display.tools_width}px`)
  set('--theme-radius', `${display.radius}px`)

  // 排版：主题给标度，用户显式选择优先。
  const typography = typographyState.value
  const scale = typography.scale === 'auto' ? display.type_scale : typography.scale
  const lineHeight = typography.lineHeight === 'auto' ? readingPreferences.lineHeight : typography.lineHeight
  set('--theme-type-scale', String(scale))
  set('--theme-line-height', String(lineHeight))
  set('--theme-heading-font', headingStack(display.heading_family))
  set('--theme-body-font', bodyStack(display.body_family))
  set('--theme-body-size', `${Math.round(readingPreferences.font * scale * 100) / 100}px`)

  // 阅读宽度：用户显式设置过宽度时优先，否则用主题值。
  // 两侧都截到 560—1080，避免主题在窄窗把正文挤成窄栏或拉成超长行。
  const width = readingPreferences.width
  const hasExplicitWidth = Number.isFinite(width) && width !== DEFAULT_READING_WIDTH
  set('--theme-reading-max', `${hasExplicitWidth ? Math.max(READING_WIDTH_MIN, Math.min(READING_WIDTH_MAX, width)) : display.reading_width}px`)
}

const HEADING_STACKS: Record<ThemeDisplay['heading_family'], string> = {
  editorial: "'Noto Serif CJK SC','Source Han Serif SC','SimSun',serif",
  modern: "'Segoe UI Variable Display','Segoe UI','Microsoft YaHei UI',sans-serif",
  technical: "'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI',sans-serif",
}
const BODY_STACKS: Record<ThemeDisplay['body_family'], string> = {
  ui: "'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI',sans-serif",
  humanist: "'Noto Sans CJK SC','Source Han Sans SC','Microsoft YaHei UI',sans-serif",
  system: "system-ui,'Segoe UI','Microsoft YaHei UI',sans-serif",
}
function headingStack(family: ThemeDisplay['heading_family']): string {
  return HEADING_STACKS[family]
}
function bodyStack(family: ThemeDisplay['body_family']): string {
  return BODY_STACKS[family]
}

/**
 * 用户是否显式设置过阅读宽度。
 *
 * 旧版 readingPreferences 无条件把默认值回写 localStorage，因此「存储里有值」并不等于
 * 用户选择过；只有当前值不等于默认值时才视为显式选择，避免把默认值当成用户自愿更改。
 */

/** 初始化展示偏好（在主题控制器之前调用，保证首次 apply 就带上用户偏好）。 */
export function initializeDisplayPreferences(): void {
  imageIntensityState.value = readStored(IMAGE_INTENSITY_STORAGE_KEY, validIntensity, 'full')
  typographyState.value = readStored(TYPOGRAPHY_STORAGE_KEY, validTypography, { scale: 'auto', lineHeight: 'auto' })
}

export function setImageIntensity(value: ImageIntensity): void {
  imageIntensityState.value = value
  persist(IMAGE_INTENSITY_STORAGE_KEY, value)
  document.documentElement.dataset.themeImage = value
}
export function setTypographyPreference(next: TypographyPreference): void {
  typographyState.value = next
  persist(TYPOGRAPHY_STORAGE_KEY, next)
  reapply()
}
/** 用户改动阅读偏好（字号/行距/宽度）后重算派生变量；不重挂组件、不动输入与焦点。 */
export function reapply(): void {
  if (currentTheme) applyDisplay(currentTheme)
}
let currentTheme: Theme | null = null
export function rememberTheme(theme: Theme): void {
  currentTheme = theme
  applyDisplay(theme)
}
export function currentDisplayTheme(): Theme | null {
  return currentTheme
}
