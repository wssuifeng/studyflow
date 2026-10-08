import { DEFAULT_THEME, parseTheme } from './contract'
// Discover local data-only builtins at build time, not from the network.
const sources = import.meta.glob('./builtin/*.json', { eager: true, import: 'default' })
export const builtinThemes = Object.values(sources).map(parseTheme).sort((a, b) => a.id === DEFAULT_THEME.id ? -1 : b.id === DEFAULT_THEME.id ? 1 : a.id.localeCompare(b.id))
if (new Set(builtinThemes.map(theme => theme.id)).size !== builtinThemes.length) throw new Error('内置主题ID重复。')
