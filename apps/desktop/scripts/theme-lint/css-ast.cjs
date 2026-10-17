// W4 样式AST门禁（主设计§8.3第3道）：postcss 解析全部 CSS + Vue <style>，
// 对【主题身份作用域】规则（[data-theme-id="X"]/[data-theme-display="X"]/[data-overlay-name="X"]）
// 逐 selector+property 判定布局越权，并以精确债务清单收口既有违规。
//
// 作用域区分（主设计§8.2 token与布局的权限）：
//   身份作用域  = 选取器含带值主题身份锚 → 逐属性判定越权（主题不应重定义结构）
//   契约作用域  = [data-theme-layout='docked'] 等带值 profile 锚 → 受控契约映射，
//                  仅允许出现在登记的契约实现文件 runtime.css；他处出现视为越权
//   通用锚点    = 无值 [data-theme-id]/[data-theme-display]/[data-overlay-name]（全主题统一，
//                  等价共享层）→ 非违规，记为 notice 提示“结构属性建议移入共享层”
//   共享层      = 无主题锚点 → 不门禁（结构由共享层定义）
//
// 越权类别（AST 级，与 2026-10-16 计数基线语义对齐，迁移依据见 css-debt.json meta）：
//   THEME_CSS_GRID              grid-template-columns/rows/areas
//   THEME_CSS_FIXED             position: fixed
//   THEME_CSS_ABSOLUTE_UNGUARDED position:absolute 且非(装饰槽 & pointer-events:none)
//   THEME_CSS_VIEWPORT          100vh/100dvh 字面量（值文本）
//   THEME_CSS_OVERFLOW_HIDDEN   overflow: hidden（旧语义：prop=overflow 精确）
//   THEME_CSS_DISPLAY_NONE      display: none（非装饰槽）
//   THEME_CSS_LAYOUT_IMPORTANT  prop∈{grid,position,overflow,display,height,width,flex,margin,padding} 且含 !important
//
// 装饰槽（DECORATIVE_SLOTS，css-debt.json 登记）：display:none / overflow:hidden / 受 pointer-events:none 保护
// 的 position:absolute 在装饰槽内放行；其余选择器一律按违规/债务处理。
// 防洗白：lint 实际违规不在债务清单→失败；清单项无对应实际违规→过期提示；
//         --update-debt 仅允许“删除”项（新增拒绝）；test:themes 固化清单 id 集合（手改 JSON 加项即破坏测试）。
const fs = require('node:fs'), path = require('node:path')
const postcss = require('postcss')
const { parse: parseSfc } = require('@vue/compiler-sfc')

const IDENTITY_ANCHOR = /\[(?:data-theme-id|data-theme-display|data-overlay-name)="[^"]+"\]/
const IDENTITY_ANCHOR_UNVALUED = /\[(?:data-theme-id|data-theme-display|data-overlay-name)\]/
const CONTRACT_ANCHOR = /\[data-theme-(?:layout|reading-shell|teaching|teaching-style|note-style|surface|elevation|outline|image|density|heading|motion|sound|shell-contract)(?:='[^']+'|[^\]]*)?\]/
const CONTRACT_FILE = 'src/shared/themes/runtime.css'
const LAYOUT_IMPORTANT_PROPS = new Set(['grid', 'position', 'overflow', 'display', 'height', 'width', 'flex', 'margin', 'padding'])
const VIEWPORT_RE = /100(?:vh|dvh|svh|lvh)/
const ABSOLUTE_RE = /\babsolute\b/
const FIXED_RE = /\bfixed\b/
const NONE_RE = /\bnone\b/
const HIDDEN_RE = /\bhidden\b/

const relTo = (root, file) => path.relative(root, file).split(path.sep).join('/')

function walkSourceFiles(root) {
  const out = []
  const walk = dir => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === '.git' || entry.name === 'dist') continue
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.name.endsWith('.css')) out.push(full)
      else if (entry.name.endsWith('.vue')) out.push(full)
    }
  }
  walk(path.join(root, 'src'))
  return out
}

function normalizeSelector(sel) {
  return sel.replace(/\s+/g, ' ').replace(/\s*([>+~,])\s*/g, '$1').trim()
}
function selectorSignature(sel) {
  // 取最右复合选择器的类/伪元素集合，用于装饰槽匹配
  const last = sel.split(/\s*[ >+~]\s*/).pop() || sel
  const classes = [...last.matchAll(/\.([A-Za-z0-9_-]+)/g)].map(m => m[1])
  const pseudos = [...last.matchAll(/::?([A-Za-z-]+)/g)].map(m => m[1])
  return { classes: new Set(classes), pseudos: new Set(pseudos), raw: sel }
}
function isDecorative(sel, decorative) {
  if (!decorative.length) return false
  const sig = selectorSignature(sel)
  return decorative.some(slot => {
    const cls = slot.selectorClasses?.length ? slot.selectorClasses.every(c => sig.classes.has(c)) : true
    const psd = slot.selectorPseudos?.length ? slot.selectorPseudos.every(p => sig.pseudos.has(p)) : true
    return cls && psd
  })
}

function classifyRule(rule, file, rel, decorative, contractFiles, sink, notices) {
  const selectors = rule.selectors
  const identity = selectors.filter(s => IDENTITY_ANCHOR.test(s))
  const universal = selectors.filter(s => IDENTITY_ANCHOR_UNVALUED.test(s) && !IDENTITY_ANCHOR.test(s))
  const contract = selectors.filter(s => CONTRACT_ANCHOR.test(s) && !IDENTITY_ANCHOR.test(s))
  const inContractFile = contractFiles.has(rel)
  // 契约作用域：仅允许出现在登记的契约实现文件；他处契约锚点+结构属性 → 越权（同样按类别计）
  const contractElsewhere = contract.length && !inContractFile
  if (!identity.length && !contractElsewhere) {
    if (universal.length) {
      // 通用锚点：结构属性出现 → 非违规 notice（等价共享层，建议下沉）
      for (const decl of rule.nodes.filter(n => n.type === 'decl')) {
        if (/^(grid-template-(?:columns|rows|areas)|position|overflow|display|height|width|flex|grid)$/.test(decl.prop)) {
          notices.push({ kind: 'UNIVERSAL_ANCHOR_STRUCTURE', file: rel, selector: normalizeSelector(rule.selector), prop: decl.prop, line: decl.source?.start?.line })
        }
      }
    }
    return
  }
  const scopeSelectors = identity.length ? identity : contract
  const scopeKind = identity.length ? 'identity' : 'contract-elsewhere'
  const hasAbsolute = rule.nodes.some(n => n.type === 'decl' && n.prop === 'position' && ABSOLUTE_RE.test(n.value))
  const hasPointerNone = rule.nodes.some(n => n.type === 'decl' && n.prop === 'pointer-events' && NONE_RE.test(n.value))
  const allDecorative = scopeSelectors.length > 0 && scopeSelectors.every(s => isDecorative(s, decorative))
  // ABSOLUTE_UNGUARDED：rule 级，按选取器归一化登记（身份作用域）
  if (scopeKind === 'identity' && hasAbsolute && !(allDecorative && hasPointerNone)) {
    sink.push({ rule: 'THEME_CSS_ABSOLUTE_UNGUARDED', file: rel, selector: normalizeSelector(rule.selector), prop: 'position', value: 'absolute', line: rule.source?.start?.line })
  }
  if (scopeKind === 'contract-elsewhere' && hasAbsolute) {
    sink.push({ rule: 'THEME_CSS_ABSOLUTE_UNGUARDED', file: rel, selector: normalizeSelector(rule.selector), prop: 'position', value: 'absolute', line: rule.source?.start?.line })
  }
  for (const decl of rule.nodes.filter(n => n.type === 'decl')) {
    const value = decl.value, prop = decl.prop
    const selDecorative = allDecorative
    const add = (ruleName) => sink.push({ rule: ruleName, file: rel, selector: normalizeSelector(rule.selector), prop, value: value.trim(), line: decl.source?.start?.line })
    if (/^grid-template-(?:columns|rows|areas)$/.test(prop)) add('THEME_CSS_GRID')
    else if (prop === 'position' && FIXED_RE.test(value)) add('THEME_CSS_FIXED')
    else if (VIEWPORT_RE.test(value)) add('THEME_CSS_VIEWPORT')
    else if (prop === 'overflow' && HIDDEN_RE.test(value)) { if (!selDecorative) add('THEME_CSS_OVERFLOW_HIDDEN') }
    else if (prop === 'display' && NONE_RE.test(value)) { if (!selDecorative) add('THEME_CSS_DISPLAY_NONE') }
    else if (LAYOUT_IMPORTANT_PROPS.has(prop) && decl.important) add('THEME_CSS_LAYOUT_IMPORTANT')
  }
}

function lintCssAst(root, options = {}) {
  const debtFile = options.debtFile || path.join(__dirname, 'css-debt.json')
  const registry = fs.existsSync(debtFile) ? JSON.parse(fs.readFileSync(debtFile, 'utf8')) : { meta: {}, decorative: [], debt: [] }
  if (!Array.isArray(registry.debt)) throw new Error('css-debt.json.debt 必须是数组')
  const decorative = options.decorative || (Array.isArray(registry.decorative) ? registry.decorative : [])
  const contractFiles = new Set([CONTRACT_FILE])
  const files = options.files || walkSourceFiles(root)
  const violations = [], notices = [], diagnostics = []
  for (const file of files) {
    const rel = relTo(root, file)
    let source, styles = []
    if (rel.endsWith('.vue')) {
      let descriptor
      try { descriptor = parseSfc(fs.readFileSync(file, 'utf8'), { filename: file }).descriptor } catch (error) { diagnostics.push(`SFC解析失败 ${rel}: ${error.message}`); continue }
      // <style> 块内行号相对块内容；补上块在 SFC 中的起始行偏移。
      styles = (descriptor.styles || []).map(s => ({ content: s.content, lang: s.lang, lineOffset: (s.loc?.start?.line ?? 1) - 1 }))
    } else if (rel.endsWith('.css')) {
      styles = [{ content: fs.readFileSync(file, 'utf8'), lang: 'css', lineOffset: 0 }]
    } else continue
    for (const { content, lang, lineOffset } of styles) {
      if (lang && lang !== 'css') continue // 仅处理 CSS（SCSS/PostCSS等暂不在范围内）
      let root2
      try { root2 = postcss.parse(content) } catch (error) { diagnostics.push(`CSS解析失败 ${rel}: ${error.message}`); continue }
      const push = (entry) => { violations.push({ ...entry, line: (entry.line || 0) + lineOffset, lineOffset }) }
      root2.walkRules(rule => classifyRule(rule, file, rel, decorative, contractFiles, { push }, notices))
    }
  }
  // 债务匹配：按 (file, rule, normalized selector, prop, value-trim) 匹配；失配违规→失败，失配债务→过期
  const used = new Set()
  const unmatched = violations.filter(v => {
    const idx = registry.debt.findIndex(d => d.file === v.file && d.rule === v.rule && d.selector === v.selector && d.prop === v.prop && (d.value || '').trim() === (v.value || '').trim())
    if (idx >= 0) { used.add(idx); return false }
    return true
  })
  const stale = registry.debt.map((d, i) => used.has(i) ? null : { ...d, stale: true }).filter(Boolean)
  return { violations: unmatched, staleDebt: stale, notices, diagnostics, checked: files.length, decorativeCount: decorative.length, debtCount: registry.debt.length }
}

function migrateDebt(root, options = {}) {
  const debtFile = options.debtFile || path.join(__dirname, 'css-debt.json')
  const existing = fs.existsSync(debtFile) ? JSON.parse(fs.readFileSync(debtFile, 'utf8')) : null
  const decorative = existing?.decorative || []
  const existingDebt = existing?.debt || []
  // 原始违规：装饰槽取自当前提交清单，债务匹配指向不存在的文件 → .violations 即全部实际违规
  const all = lintCssAst(root, { files: options.files, decorative, debtFile: path.join(__dirname, '__nonexistent_debt__.json') })
  const actualSet = all.violations
  // 新增项 = 实际中存在但既有清单无对应 → 拒绝（防洗白：不能借迁移把新违规顺手合法化）
  const matches = v => existingDebt.some(d => d.file === v.file && d.rule === v.rule && d.selector === v.selector && d.prop === v.prop && (d.value || '').trim() === (v.value || '').trim())
  const added = actualSet.filter(v => !matches(v))
  if (added.length) {
    const err = new Error('迁移/更新拒绝：以下违规为新增（不在既有债务清单），不能自动合法化：\n' + added.slice(0, 10).map(v => `  ${v.file} ${v.rule} ${v.selector} ${v.prop}:${v.value}`).join('\n'))
    err.added = added
    throw err
  }
  // 删除项 = 既有清单中实际已不存在的 → 写回精简清单
  const kept = existingDebt.filter(d => actualSet.some(v => v.file === d.file && v.rule === v.rule && v.selector === d.selector && v.prop === d.prop && (d.value || '').trim() === (v.value || '').trim()))
  const out = { meta: { ...(existing?.meta || {}), lastUpdated: new Date().toISOString().slice(0, 10) }, decorative, debt: kept }
  fs.writeFileSync(debtFile, JSON.stringify(out, null, 2) + '\n', 'utf8')
  return { kept: kept.length, removed: existingDebt.length - kept.length }
}

module.exports = { lintCssAst, migrateDebt, IDENTITY_ANCHOR, CONTRACT_FILE, normalizeSelector, isDecorative }
