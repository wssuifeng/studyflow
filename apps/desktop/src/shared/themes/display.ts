/**
 * 主题展示包契约（v2）。
 *
 * 这里定义的是「主题能改变什么」的受控词汇表：布局组合、容器几何、排版标度、
 * 表面处理与本地素材引用。它只描述纯展示，不携带任何业务语义：
 * 没有请求、没有数据模型、没有保存/提交/批改/轮次入口，也不允许执行代码。
 *
 * v1 主题（只有色板 + presentation 预设）仍然合法：`display` 字段可缺省，
 * 缺省时由 `displayFromPresentation()` 从旧的三个预设推导出等价展示包。
 */
/**
 * 本模块刻意不 import contract.ts：主题契约反过来要调用 parseDisplay，
 * 双向 import 会在 ESM 求值顺序上形成环。对比度计算是纯函数，直接内联一份。
 */
export const DISPLAY_SCHEMA = 'studyflow.theme-display/1' as const

function contrastRatio(a: string, b: string): number {
  const luminance = (hex: string) => {
    const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(c => c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4)
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
  }
  const x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + .05) / (Math.min(x, y) + .05)
}

/** 布局组合：导航与阅读面的组织方式，不是栏宽数值。 */
export const LAYOUTS = ['rail', 'tabs', 'docked', 'page'] as const
/** 阅读面与正文的关系：连续纸面 / 紧凑工作台 / 分栏 / 单列宽读。 */
export const READING_SHELLS = ['sheet', 'workbench', 'split', 'column'] as const
/** 教学块的容器语言。 */
export const TEACHING_STYLES = ['paper', 'clean', 'outlined', 'rail', 'paired'] as const
/** 边注/提示的落位。 */
export const NOTE_STYLES = ['margin', 'inline', 'edge', 'off'] as const
/** 表面处理：实体哑光为主，明确禁止玻璃与霓虹。 */
export const SURFACE_TREATMENTS = ['matte', 'flat', 'paper', 'graphite'] as const
export const ELEVATIONS = ['none', 'subtle', 'raised'] as const
export const OUTLINES = ['hairline', 'strong', 'mixed'] as const
export const HEADING_FAMILIES = ['editorial', 'modern', 'technical'] as const
export const BODY_FAMILIES = ['ui', 'humanist', 'system'] as const
export const IMAGE_INTENSITIES = ['full', 'subtle', 'none'] as const

export type ThemeLayout = (typeof LAYOUTS)[number]
export type ReadingShell = (typeof READING_SHELLS)[number]
export type TeachingStyle = (typeof TEACHING_STYLES)[number]
export type NoteStyle = (typeof NOTE_STYLES)[number]
export type SurfaceTreatment = (typeof SURFACE_TREATMENTS)[number]
export type Elevation = (typeof ELEVATIONS)[number]
export type OutlineStyle = (typeof OUTLINES)[number]
export type HeadingFamily = (typeof HEADING_FAMILIES)[number]
export type BodyFamily = (typeof BODY_FAMILIES)[number]
export type ImageIntensity = (typeof IMAGE_INTENSITIES)[number]

export type DisplayAsset = {
  /** 主题包内声明的本地素材标识（不含路径分隔符）。 */
  key: string
  /** 在容器中的用途：背景、边缘纹理或局部插画。 */
  role: 'background' | 'texture' | 'illustration'
  /** 素材实际宽高比，形如 "16:9"。 */
  aspect_ratio: string
  /** 构图时必须保留的裁切安全区（0—1 的比例，越小越安全）。 */
  safe_area: number
  /** 缺图或不使用图片时的纯色回退。 */
  fallback: string
}

export type ThemeDisplay = {
  layout: ThemeLayout
  /** 导航区宽度（px）。窄轨到宽侧栏都由主题决定。 */
  navigation_width: number
  /** 阅读面最大宽度（px）；与用户阅读宽度偏好取较小值。 */
  reading_width: number
  /** 工具区首选宽度（px）；展开时与前两区等高并共同让宽。 */
  tools_width: number
  reading_shell: ReadingShell
  teaching_style: TeachingStyle
  note_style: NoteStyle
  /** 正文标度（0.9—1.15）；用户显式排版偏好优先于该值。 */
  type_scale: number
  heading_family: HeadingFamily
  body_family: BodyFamily
  surface_treatment: SurfaceTreatment
  radius: number
  elevation: Elevation
  outline: OutlineStyle
  assets: DisplayAsset[]
}

/** 旧 v1 预设 → 展示包。保证旧配置无需新增字段即可解析。 */
export function displayFromPresentation(presentation: {
  density: 'comfortable' | 'compact'
  heading: HeadingFamily
  teaching: 'paper' | 'clean' | 'outlined'
}): ThemeDisplay {
  const compact = presentation.density === 'compact'
  return {
    layout: compact ? 'docked' : 'rail',
    navigation_width: compact ? 72 : 184,
    reading_width: compact ? 760 : 820,
    tools_width: 420,
    reading_shell: presentation.teaching === 'clean' ? 'workbench' : 'sheet',
    teaching_style: presentation.teaching,
    note_style: 'inline',
    type_scale: 1,
    heading_family: presentation.heading,
    body_family: 'ui',
    surface_treatment: presentation.teaching === 'outlined' ? 'flat' : 'matte',
    radius: compact ? 6 : 12,
    elevation: presentation.teaching === 'clean' ? 'none' : 'subtle',
    outline: presentation.teaching === 'outlined' ? 'strong' : 'hairline',
    assets: [],
  }
}

function fail(label: string): never {
  throw new Error(`${label}不在允许的展示预设中。`)
}
function choice<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== 'string' || !allowed.includes(value as T)) fail(label)
  return value as T
}
function integer(value: unknown, min: number, max: number, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) {
    throw new Error(`${label}必须是${min}—${max}之间的整数。`)
  }
  return value as number
}
function decimal(value: unknown, min: number, max: number, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
    throw new Error(`${label}必须是${min}—${max}之间的数值。`)
  }
  // 保留两位小数，避免主题写入超长浮点噪声。
  return Math.round(value * 100) / 100
}
function color(value: unknown, label: string): string {
  if (typeof value !== 'string' || !/^#[\da-f]{6}$/i.test(value)) throw new Error(`${label}必须是完整的#RRGGBB不透明色值。`)
  return value.toLowerCase()
}
function assetKey(value: unknown, label: string): string {
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9-]{0,31}$/.test(value)) {
    throw new Error(`${label}只能使用小写字母、数字和连接符，且必须以字母或数字开头。`)
  }
  return value
}
function aspect(value: unknown, label: string): string {
  if (typeof value !== 'string' || !/^\d{1,4}:[1-9]\d{0,3}$/.test(value)) throw new Error(`${label}必须是形如16:9的比例。`)
  const [a, b] = value.split(':').map(Number)
  if (!a || !b || a / b < 0.2 || a / b > 8) throw new Error(`${label}超出可用的素材比例范围。`)
  return value
}

/**
 * 展示包只接受上表枚举与受控数值范围。
 * 之所以不用「任何字符串」：展示参数会直接进入 CSS 变量与 dataset，
 * 一旦放开就会变成事实上的脚本/选择器注入通道。
 */
export function parseDisplay(value: unknown, tokens?: Record<string, string>): ThemeDisplay {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) throw new Error('展示包必须是对象。')
  const source = value as Record<string, unknown>
  const required = [
    'layout', 'navigation_width', 'reading_width', 'tools_width', 'reading_shell', 'teaching_style',
    'note_style', 'type_scale', 'heading_family', 'body_family', 'surface_treatment', 'radius',
    'elevation', 'outline', 'assets',
  ] as const
  const unknown = Object.keys(source).filter(key => !(required as readonly string[]).includes(key))
  if (unknown.length) throw new Error(`展示包包含不支持的字段：${unknown.slice(0, 3).join('、')}。`)
  const missing = required.filter(key => !Object.hasOwn(source, key))
  if (missing.length) throw new Error(`展示包字段不完整：${missing.slice(0, 3).join('、')}。`)

  const assets = source.assets
  if (!Array.isArray(assets) || assets.length > 4) throw new Error('展示包最多声明4个本地素材。')
  const parsedAssets: DisplayAsset[] = assets.map((raw, index) => {
    if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('素材声明必须是对象。')
    const item = raw as Record<string, unknown>
    const fields = ['key', 'role', 'aspect_ratio', 'safe_area', 'fallback'] as const
    const extra = Object.keys(item).filter(key => !(fields as readonly string[]).includes(key))
    if (extra.length || fields.some(field => !Object.hasOwn(item, field))) throw new Error(`素材声明字段不完整或包含不支持的字段（第${index + 1}项）。`)
    return {
      key: assetKey(item.key, '素材标识'),
      role: choice(item.role, ['background', 'texture', 'illustration'] as const, '素材用途'),
      aspect_ratio: aspect(item.aspect_ratio, '素材比例'),
      safe_area: decimal(item.safe_area, 0, 1, '裁切安全区'),
      fallback: color(item.fallback, '素材回退色'),
    }
  })
  const keys = parsedAssets.map(asset => asset.key)
  if (new Set(keys).size !== keys.length) throw new Error('素材标识重复。')

  const display: ThemeDisplay = {
    layout: choice(source.layout, LAYOUTS, '布局组合'),
    navigation_width: integer(source.navigation_width, 56, 240, '导航宽度'),
    reading_width: integer(source.reading_width, 560, 1080, '阅读宽度'),
    tools_width: integer(source.tools_width, 300, 640, '工具区宽度'),
    reading_shell: choice(source.reading_shell, READING_SHELLS, '阅读壳'),
    teaching_style: choice(source.teaching_style, TEACHING_STYLES, '教学容器语言'),
    note_style: choice(source.note_style, NOTE_STYLES, '边注落位'),
    type_scale: decimal(source.type_scale, 0.9, 1.15, '正文标度'),
    heading_family: choice(source.heading_family, HEADING_FAMILIES, '标题字族'),
    body_family: choice(source.body_family, BODY_FAMILIES, '正文字族'),
    surface_treatment: choice(source.surface_treatment, SURFACE_TREATMENTS, '表面处理'),
    radius: integer(source.radius, 0, 24, '圆角'),
    elevation: choice(source.elevation, ELEVATIONS, '投影层级'),
    outline: choice(source.outline, OUTLINES, '描边强度'),
    assets: parsedAssets,
  }

  // 素材回退色必须能在主题表面上承担可读的装饰底，不能制造刺眼或不可见块。
  if (tokens) {
    for (const asset of parsedAssets) {
      if (contrastRatio(asset.fallback, tokens['surface.canvas']) < 1.05) {
        throw new Error(`素材回退色与画布过于接近，缺图时会不可见（${asset.key}）。`)
      }
    }
  }
  return display
}
