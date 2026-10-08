/**
 * Imported themes are data, never executable CSS, templates or scripts.
 *
 * v1（色板 + 三个展示预设）与 v2（额外可选 display 展示包）共用同一个 schema 字符串：
 * 旧配置不需要增加任何字段即可继续解析，新配置只是多了一个受控的展示维度。
 * 展示包本身由 display.ts 校验，它同样只描述纯展示。
 */
import { displayFromPresentation, parseDisplay, type ThemeDisplay } from './display'
export type { ThemeDisplay } from './display'
export const THEME_SCHEMA = 'studyflow.theme/1' as const
export const DEFAULT_THEME = { id: 'white-violet' } as const
export const MAX_THEME_BYTES = 32_768
export const MAX_CUSTOM_THEMES = 20
export const TOKEN_PROPERTIES = {
  'surface.canvas': '--theme-surface-canvas', 'surface.panel': '--theme-surface-panel',
  'surface.raised': '--theme-surface-raised', 'surface.input': '--theme-surface-input',
  'surface.hover': '--theme-surface-hover', 'surface.active': '--theme-surface-active',
  'border.subtle': '--theme-border-subtle', 'border.strong': '--theme-border-strong',
  'text.primary': '--theme-text-primary', 'text.secondary': '--theme-text-secondary',
  'text.muted': '--theme-text-muted', 'text.inverse': '--theme-text-inverse',
  'accent.primary': '--theme-accent-primary', 'accent.strong': '--theme-accent-strong',
  'accent.soft': '--theme-accent-soft', 'status.success': '--theme-status-success',
  'status.success-soft': '--theme-status-success-soft', 'status.info': '--theme-status-info',
  'status.info-soft': '--theme-status-info-soft', 'status.warning': '--theme-status-warning',
  'status.warning-soft': '--theme-status-warning-soft', 'status.danger': '--theme-status-danger',
  'status.danger-soft': '--theme-status-danger-soft', 'focus.ring': '--theme-focus-ring',
  'code.background': '--theme-code-background', 'code.text': '--theme-code-text',
  'shadow.ink': '--theme-shadow-ink', 'overlay.ink': '--theme-overlay-ink',
} as const
export type ThemeToken = keyof typeof TOKEN_PROPERTIES
export type Theme = {
  schema_version: typeof THEME_SCHEMA; id: string; name: string; description: string
  appearance: 'light' | 'dark'; tokens: Record<ThemeToken, string>
  presentation: { density: 'comfortable' | 'compact'; heading: 'editorial' | 'modern' | 'technical'; teaching: 'paper' | 'clean' | 'outlined' }
  motion_profile: 'gentle' | 'minimal' | 'none'; sound_profile: 'soft-tap' | 'glass' | 'muted'
  /** v2 可选展示包；v1 配置缺省时按 presentation 推导，字段永远存在。 */
  display: ThemeDisplay
}
export function jsonBytes(text: string): number {
  let bytes = 0
  for (const char of text) { const code = char.codePointAt(0)!; bytes += code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4 }
  return bytes
}
function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}必须是对象。`)
  return value as Record<string, unknown>
}
function keys(value: Record<string, unknown>, expected: readonly string[], label: string) {
  if (Object.keys(value).length !== expected.length || expected.some(key => !Object.hasOwn(value, key))) throw new Error(`${label}字段不完整或包含不支持的字段。`)
}
/** 复制一份不含可选 display 的主题对象，用于「必填字段恰好齐全」的严格校验。 */
function withoutDisplay(source: Record<string, unknown>): Record<string, unknown> {
  const copy: Record<string, unknown> = {}
  for (const key of Object.keys(source)) if (key !== 'display') copy[key] = source[key]
  return copy
}
function text(value: unknown, max: number, label: string): string {
  if (typeof value !== 'string' || !value.trim() || value.length > max || /[<>\x00-\x1f]|url\s*\(|javascript\s*:|expression\s*\(/i.test(value)) throw new Error(`${label}格式不合法。`)
  return value.trim()
}
function choice<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) throw new Error(`${label}不在允许的预设中。`)
  return value as T
}
export function contrastRatio(a: string, b: string): number {
  const luminance = (hex: string) => {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
  }
  const x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05)
}
export function parseTheme(value: unknown): Theme {
  const source = record(value, '主题')
  if (jsonBytes(JSON.stringify(source)) > MAX_THEME_BYTES) throw new Error('主题配置过大（最多32KB）。')
  // v1 必填字段 + 唯一可选字段 display；其余未知字段整体拒绝。
  const allowed = ['schema_version', 'id', 'name', 'description', 'appearance', 'tokens', 'presentation', 'motion_profile', 'sound_profile', 'display']
  if (Object.keys(source).some(key => !allowed.includes(key))) throw new Error('主题字段不完整或包含不支持的字段。')
  keys(withoutDisplay(source), ['schema_version', 'id', 'name', 'description', 'appearance', 'tokens', 'presentation', 'motion_profile', 'sound_profile'], '主题')
  if (source.schema_version !== THEME_SCHEMA) throw new Error('不支持的主题配置版本。')
  const id = text(source.id, 64, '主题ID')
  if (!/^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$/.test(id)) throw new Error('主题ID只能使用小写字母、数字和连接符。')
  const rawTokens = record(source.tokens, '色板'); keys(rawTokens, Object.keys(TOKEN_PROPERTIES), '色板')
  const tokens = {} as Theme['tokens']
  for (const key of Object.keys(TOKEN_PROPERTIES) as ThemeToken[]) {
    const color = rawTokens[key]
    if (typeof color !== 'string' || !/^#[\da-f]{6}$/i.test(color)) throw new Error(`${key}必须是完整的#RRGGBB不透明色值。`)
    tokens[key] = color.toLowerCase()
  }
  const p = record(source.presentation, '展示预设'); keys(p, ['density', 'heading', 'teaching'], '展示预设')
  const presentation = { density: choice(p.density, ['comfortable', 'compact'], '密度'), heading: choice(p.heading, ['editorial', 'modern', 'technical'], '标题预设'), teaching: choice(p.teaching, ['paper', 'clean', 'outlined'], '教学预设') }
  const theme: Theme = {
    schema_version: THEME_SCHEMA, id, name: text(source.name, 40, '主题名称'), description: text(source.description, 180, '主题说明'),
    appearance: choice(source.appearance, ['light', 'dark'], '明暗模式'), tokens,
    presentation,
    motion_profile: choice(source.motion_profile, ['gentle', 'minimal', 'none'], '动态预设'), sound_profile: choice(source.sound_profile, ['soft-tap', 'glass', 'muted'], '音色预设'),
    display: source.display === undefined ? displayFromPresentation(presentation) : parseDisplay(source.display, tokens),
  }
  for (const fg of ['text.primary', 'text.secondary', 'text.muted'] as ThemeToken[]) {
    for (const bg of ['surface.canvas', 'surface.panel', 'surface.raised', 'surface.input', 'surface.hover', 'surface.active', 'accent.soft', 'status.success-soft', 'status.info-soft', 'status.warning-soft', 'status.danger-soft'] as ThemeToken[]) {
      if (contrastRatio(tokens[fg], tokens[bg]) < 4.5) throw new Error(`${fg}与${bg}的文字对比度不足4.5:1。`)
    }
  }
  const pairs: [ThemeToken, ThemeToken][] = [['accent.primary', 'accent.soft'], ['accent.primary', 'surface.panel'], ['text.inverse', 'accent.primary'], ['text.inverse', 'accent.strong'], ['status.success', 'status.success-soft'], ['status.info', 'status.info-soft'], ['status.warning', 'status.warning-soft'], ['status.danger', 'status.danger-soft'], ['code.text', 'code.background']]
  for (const status of ['status.success', 'status.info', 'status.warning', 'status.danger'] as ThemeToken[]) {
    pairs.push([status, 'surface.panel'], [status, 'surface.canvas'])
  }
  for (const [fg, bg] of pairs) if (contrastRatio(tokens[fg], tokens[bg]) < 4.5) throw new Error(`${fg}与${bg}的文字对比度不足4.5:1。`)
  if (contrastRatio(tokens['focus.ring'], tokens['surface.panel']) < 3) throw new Error('焦点标记对比度不足3:1。')
  return theme
}
