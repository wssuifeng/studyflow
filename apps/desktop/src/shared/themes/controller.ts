import { DEFAULT_THEME, MAX_CUSTOM_THEMES, MAX_THEME_BYTES, jsonBytes, parseTheme, type Theme } from './contract'
export const PREFERENCE_SCHEMA = 'studyflow.theme-preference/1' as const
export const DISPLAY_PREFERENCE_SCHEMA = 'studyflow.theme-display-preference/1' as const
export type ThemeSnapshot = { schema_version: typeof PREFERENCE_SCHEMA; selected_theme_id: string; custom_themes: Theme[]; revision: { clock: number; source: string } }
/**
 * 展示偏好与主题偏好分开存储：切换/导入主题不会重置用户的排版与图像强度选择，
 * 反之亦然。两者都用同一套 revision 规则做跨窗合并。
 */
export type DisplaySnapshot = {
  schema_version: typeof DISPLAY_PREFERENCE_SCHEMA
  typography: { scale: 'auto' | number; lineHeight: 'auto' | number }
  image_intensity: 'full' | 'subtle' | 'none'
  revision: { clock: number; source: string }
}
export type ThemeView = { theme: Theme; themes: { theme: Theme; source: 'builtin' | 'custom' }[]; notice: string; persistent: boolean }
export type ThemeResult = { ok: true } | { ok: false; error: string }
export type ThemeOptions = {
  origin: string
  now: () => number
  read: () => string | null
  write: (text: string) => void
  apply: (theme: Theme) => void
  publish: (snapshot: ThemeSnapshot) => void
  /** 展示偏好（可选）：旧宿主不传时保持会话内可用，不影响主题选择。 */
  readDisplay?: () => string | null
  writeDisplay?: (text: string) => void
  publishDisplay?: (snapshot: DisplaySnapshot) => void
  applyDisplayPreferences?: (snapshot: DisplaySnapshot) => void
}
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const sourcePattern = /^[a-zA-Z0-9_-]{1,100}$/
// Upgrade compatibility only: these IDs are no longer bundled theme choices.
const retiredBuiltinIds = new Set(['paper-warm', 'graphite-dark', 'sea-glass'])
export function createThemeController(builtins: readonly Theme[], options: ThemeOptions) {
  const themes = builtins.map(parseTheme)
  if (!sourcePattern.test(options.origin)) throw new Error('无效的主题窗口标识。')
  const ids = new Set(themes.map(theme => theme.id))
  if (ids.size !== themes.length || !ids.has(DEFAULT_THEME.id)) throw new Error('内置主题重复或缺少默认主题。')
  let state: ThemeSnapshot = { schema_version: PREFERENCE_SCHEMA, selected_theme_id: DEFAULT_THEME.id, custom_themes: [], revision: { clock: 0, source: options.origin } }
  let notice = '', persistent = true
  const active = () => [...themes, ...state.custom_themes].find(theme => theme.id === state.selected_theme_id)!
  function parseSnapshot(value: unknown): ThemeSnapshot {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('主题偏好损坏。')
    const raw = value as Record<string, unknown>, expected = ['schema_version', 'selected_theme_id', 'custom_themes', 'revision']
    if (raw.schema_version !== PREFERENCE_SCHEMA || Object.keys(raw).length !== expected.length || expected.some(key => !Object.hasOwn(raw, key))) throw new Error('主题偏好版本或字段不合法。')
    if (!Array.isArray(raw.custom_themes) || raw.custom_themes.length > MAX_CUSTOM_THEMES) throw new Error('自定义主题数量超出限制。')
    const custom = raw.custom_themes.map(parseTheme), combinedIds = new Set(ids)
    for (const theme of custom) { if (combinedIds.has(theme.id)) throw new Error('主题ID重复。'); combinedIds.add(theme.id) }
    if (typeof raw.selected_theme_id !== 'string') throw new Error('选中的主题不存在。')
    let selected = raw.selected_theme_id
    if (!combinedIds.has(selected)) {
      if (!retiredBuiltinIds.has(selected)) throw new Error('选中的主题不存在。')
      selected = DEFAULT_THEME.id
    }
    const rev = raw.revision as Record<string, unknown> | null
    if (!rev || typeof rev !== 'object' || Array.isArray(rev) || Object.keys(rev).length !== 2 || !Number.isSafeInteger(rev.clock) || (rev.clock as number) < 0 || typeof rev.source !== 'string' || !sourcePattern.test(rev.source)) throw new Error('主题偏好版本号不合法。')
    return { schema_version: PREFERENCE_SCHEMA, selected_theme_id: selected, custom_themes: custom, revision: { clock: rev.clock as number, source: rev.source } }
  }
  const readSnapshot = (text: string) => {
    if (jsonBytes(text) > MAX_THEME_BYTES * (MAX_CUSTOM_THEMES + 1)) throw new Error('主题偏好数据过大。')
    const raw = JSON.parse(text), snapshot = parseSnapshot(raw)
    return { snapshot, selectionReset: raw.selected_theme_id !== snapshot.selected_theme_id }
  }
  function parseDisplaySnapshot(value: unknown): DisplaySnapshot {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('展示偏好损坏。')
    const raw = value as Record<string, unknown>, expected = ['schema_version', 'typography', 'image_intensity', 'revision']
    if (raw.schema_version !== DISPLAY_PREFERENCE_SCHEMA || Object.keys(raw).length !== expected.length || expected.some(key => !Object.hasOwn(raw, key))) throw new Error('展示偏好版本或字段不合法。')
    const typography = raw.typography as Record<string, unknown> | null
    if (!typography || typeof typography !== 'object' || Array.isArray(typography) || Object.keys(typography).length !== 2 || !Object.hasOwn(typography, 'scale') || !Object.hasOwn(typography, 'lineHeight')) throw new Error('排版偏好字段不合法。')
    const bounded = (input: unknown, min: number, max: number) => typeof input === 'number' && Number.isFinite(input) && input >= min && input <= max ? Math.round(input * 100) / 100 : null
    const scale = typography.scale === 'auto' ? 'auto' as const : bounded(typography.scale, 0.9, 1.2)
    const lineHeight = typography.lineHeight === 'auto' ? 'auto' as const : bounded(typography.lineHeight, 1.5, 2.3)
    if (scale === null || lineHeight === null) throw new Error('排版偏好超出允许范围。')
    if (raw.image_intensity !== 'full' && raw.image_intensity !== 'subtle' && raw.image_intensity !== 'none') throw new Error('图像强度不在允许的预设中。')
    const rev = raw.revision as Record<string, unknown> | null
    if (!rev || typeof rev !== 'object' || Array.isArray(rev) || Object.keys(rev).length !== 2 || !Number.isSafeInteger(rev.clock) || (rev.clock as number) < 0 || typeof rev.source !== 'string' || !sourcePattern.test(rev.source)) throw new Error('展示偏好版本号不合法。')
    return { schema_version: DISPLAY_PREFERENCE_SCHEMA, typography: { scale, lineHeight }, image_intensity: raw.image_intensity, revision: { clock: rev.clock as number, source: rev.source } }
  }
  let display: DisplaySnapshot = { schema_version: DISPLAY_PREFERENCE_SCHEMA, typography: { scale: 'auto', lineHeight: 'auto' }, image_intensity: 'full', revision: { clock: 0, source: options.origin } }
  try {
    const stored = options.readDisplay?.()
    if (stored !== null && stored !== undefined) display = parseDisplaySnapshot(JSON.parse(stored))
  } catch {
    // 展示偏好损坏只回退展示，不影响主题选择与学习记录。
    persistent = false; notice = '无法读取原展示偏好，已使用主题默认排版；学习记录不受影响。'
  }
  try {
    const stored = options.read()
    if (stored !== null) {
      const restored = readSnapshot(stored)
      state = restored.snapshot
      if (restored.selectionReset) {
        const now = options.now()
        state.revision = { clock: Math.max(state.revision.clock + 1, Number.isSafeInteger(now) && now >= 0 ? now : 0), source: options.origin }
        persist()
        notice = persistent
          ? '原内置主题已移除，已切换为白紫；自定义主题与学习记录已保留。'
          : '原内置主题已移除，本次会话使用白紫；无法保存外观偏好，自定义主题与学习记录已保留。'
      }
    }
  }
  catch { persistent = false; notice = '无法读取原主题偏好，已使用默认主题；学习记录不受影响。' }
  // 先让宿主接管展示偏好（排版/图像强度），再应用主题，保证首次渲染就带上用户偏好。
  try { options.applyDisplayPreferences?.(clone(display)) } catch { /* 展示偏好失败不阻塞主题应用。 */ }
  options.apply(clone(active()))
  function persist() {
    try { options.write(JSON.stringify(state)); persistent = true; notice = '' }
    catch { persistent = false; notice = '当前主题仅在本次会话生效：无法保存外观偏好。学习记录不受影响。' }
  }
  function persistDisplay() {
    try { options.writeDisplay?.(JSON.stringify(display)) }
    catch { notice = '排版与图像偏好仅在本次会话生效：无法保存外观偏好。学习记录不受影响。' }
  }
  function commit(next: ThemeSnapshot): ThemeResult {
    const now = options.now()
    next.revision = { clock: Math.max(state.revision.clock + 1, Number.isSafeInteger(now) && now >= 0 ? now : 0), source: options.origin }
    state = next; persist(); options.apply(clone(active()))
    try { options.publish(clone(state)) } catch { notice = '主题已切换，跨窗口同步暂不可用。' }
    return { ok: true }
  }
  function commitDisplay(next: DisplaySnapshot): ThemeResult {
    const now = options.now()
    next.revision = { clock: Math.max(display.revision.clock + 1, Number.isSafeInteger(now) && now >= 0 ? now : 0), source: options.origin }
    display = next; persistDisplay()
    try { options.applyDisplayPreferences?.(clone(display)) } catch { /* 展示偏好失败不阻塞主题。 */ }
    options.apply(clone(active()))
    try { options.publishDisplay?.(clone(display)) } catch { notice = '主题已切换，跨窗口同步暂不可用。' }
    return { ok: true }
  }
  return {
    view(): ThemeView { return clone({ theme: active(), themes: [...themes.map(theme => ({ theme, source: 'builtin' as const })), ...state.custom_themes.map(theme => ({ theme, source: 'custom' as const }))], notice, persistent }) },
    snapshot(): ThemeSnapshot { return clone(state) },
    select(id: string): ThemeResult {
      if (![...themes, ...state.custom_themes].some(theme => theme.id === id)) return { ok: false, error: '主题不存在，请选择可用的主题。' }
      if (state.selected_theme_id === id && persistent) return { ok: true }
      return commit({ ...clone(state), selected_theme_id: id })
    },
    importTheme(text: string): ThemeResult {
      try {
        if (jsonBytes(text) > MAX_THEME_BYTES) throw new Error('主题配置过大（最多32KB）。')
        const theme = parseTheme(JSON.parse(text))
        if (ids.has(theme.id)) throw new Error('此ID属于内置主题；请使用不同的自定义主题ID。')
        const next = clone(state), index = next.custom_themes.findIndex(item => item.id === theme.id)
        if (index >= 0) next.custom_themes[index] = theme
        else { if (next.custom_themes.length >= MAX_CUSTOM_THEMES) throw new Error(`最多保存${MAX_CUSTOM_THEMES}个自定义主题，请先移除不用的主题。`); next.custom_themes.push(theme) }
        next.selected_theme_id = theme.id
        return commit(next)
      } catch (cause) { return { ok: false, error: cause instanceof Error ? cause.message : '主题配置无法读取。' } }
    },
    exportTheme(): string { return JSON.stringify(active(), null, 2) + '\n' },
    removeTheme(id: string): ThemeResult {
      if (!state.custom_themes.some(theme => theme.id === id)) return { ok: false, error: '只能移除已导入的自定义主题。' }
      return commit({ ...clone(state), custom_themes: state.custom_themes.filter(theme => theme.id !== id), selected_theme_id: state.selected_theme_id === id ? DEFAULT_THEME.id : state.selected_theme_id })
    },
    receive(value: unknown): boolean {
      try {
        if (jsonBytes(JSON.stringify(value)) > MAX_THEME_BYTES * (MAX_CUSTOM_THEMES + 1)) return false
        const incoming = parseSnapshot(value), a = incoming.revision, b = state.revision
        if (a.clock < b.clock || (a.clock === b.clock && a.source <= b.source)) return false
        state = incoming; persist(); options.apply(clone(active()))
        return true // No rebroadcast: storage + app events may deliver a snapshot twice.
      } catch { return false }
    },
    displaySnapshot(): DisplaySnapshot { return clone(display) },
    setDisplayPreferences(next: { typography?: DisplaySnapshot['typography']; image_intensity?: DisplaySnapshot['image_intensity'] }): ThemeResult {
      try {
        const merged = clone(display)
        if (next.typography) merged.typography = next.typography
        if (next.image_intensity) merged.image_intensity = next.image_intensity
        const validated = parseDisplaySnapshot({ ...merged, schema_version: DISPLAY_PREFERENCE_SCHEMA, revision: { clock: 0, source: options.origin } })
        return commitDisplay(validated)
      } catch (cause) { return { ok: false, error: cause instanceof Error ? cause.message : '展示偏好无法保存。' } }
    },
    receiveDisplay(value: unknown): boolean {
      try {
        const incoming = parseDisplaySnapshot(value), a = incoming.revision, b = display.revision
        if (a.clock < b.clock || (a.clock === b.clock && a.source <= b.source)) return false
        display = incoming
        try { options.applyDisplayPreferences?.(clone(display)) } catch { /* 展示偏好失败不阻塞主题。 */ }
        persistDisplay(); options.apply(clone(active()))
        return true
      } catch { return false }
    },
  }
}
