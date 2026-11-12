// 内置主题「国风朱红」（cinnabar-paper）专项守卫。
// 用户授权由候选提升为内置（2026-11-12）：本测试证明它通过真实契约、
// 作为内置主题可直接选择且不可被导入覆盖/移除、样式全部身份作用域且不新增门禁债务。
const test = require('node:test'), assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), ts = require('typescript')
const postcss = require('postcss')
const src = path.join(__dirname, '../src/shared/themes')
const themeFile = path.join(src, 'builtin/cinnabar-paper.json')
const cssFile = path.join(__dirname, '../src/features/courses/styles/cinnabar-paper.css')
function load(file, dependency = {}) { const mod = { exports: {} }; vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(src, file), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: mod, exports: mod.exports, require: n => dependency[n] || require(n), Date, JSON, Math, Object, Array, Number, Set, Map, Error, String }); return mod.exports }
const contract = load('contract.ts', { './display': load('display.ts') })
const { createThemeController } = load('controller.ts', { './contract': contract })
const raw = JSON.parse(fs.readFileSync(themeFile, 'utf8'))
const candidate = contract.parseTheme(raw)
const builtin = fs.readdirSync(path.join(src, 'builtin')).filter(n => n.endsWith('.json')).map(n => contract.parseTheme(JSON.parse(fs.readFileSync(path.join(src, 'builtin', n), 'utf8'))))
const formal = builtin.filter(t => t.id !== 'cinnabar-paper')
const clone = x => JSON.parse(JSON.stringify(x))

test('国风朱红通过真实主题契约：28 token、对比度、展示包与素材回退', () => {
  assert.equal(candidate.id, 'cinnabar-paper')
  assert.equal(candidate.appearance, 'light')
  assert.equal(Object.keys(candidate.tokens).length, Object.keys(contract.TOKEN_PROPERTIES).length)
  assert.ok(contract.jsonBytes(JSON.stringify(raw)) <= contract.MAX_THEME_BYTES)
  let tightest = Infinity, pair = ''
  for (const fg of ['text.primary', 'text.secondary', 'text.muted']) for (const bg of ['surface.canvas', 'surface.panel', 'surface.raised', 'surface.input', 'surface.hover', 'surface.active', 'accent.soft', 'status.success-soft', 'status.info-soft', 'status.warning-soft', 'status.danger-soft']) {
    const ratio = contract.contrastRatio(candidate.tokens[fg], candidate.tokens[bg])
    assert.ok(ratio >= 4.5, `${fg}/${bg}=${ratio}`)
    if (ratio < tightest) { tightest = ratio; pair = `${fg}/${bg}` }
  }
  assert.ok(tightest >= 4.5, pair)
  for (const asset of candidate.display.assets) assert.ok(contract.contrastRatio(asset.fallback, candidate.tokens['surface.canvas']) >= 1.05, asset.key)
})

test('内置目录包含国风朱红且默认仍白紫，三套均为浅色', () => {
  assert.deepEqual(builtin.map(t => t.id).sort(), ['cinnabar-paper', 'sequence-light', 'white-violet'])
  assert.equal(contract.DEFAULT_THEME.id, 'white-violet')
  for (const t of builtin) assert.equal(t.appearance, 'light')
  assert.ok(builtin.some(t => t.id === candidate.id))
})

test('国风朱红作为内置主题可直接选择/导出/重载，内置ID不可导入或移除', () => {
  let saved = null
  const api = createThemeController(builtin, { origin: 'builtin-test', now: () => 1000, read: () => saved, write: text => { saved = text }, apply: () => {}, publish: () => {} })
  assert.equal(api.view().themes.find(x => x.theme.id === 'cinnabar-paper').source, 'builtin')
  assert.equal(api.select('cinnabar-paper').ok, true)
  assert.equal(api.view().theme.id, 'cinnabar-paper')
  assert.equal(JSON.parse(api.exportTheme()).id, 'cinnabar-paper')
  const reloaded = createThemeController(builtin, { origin: 'reload', now: () => 2000, read: () => saved, write: text => { saved = text }, apply: () => {}, publish: () => {} })
  assert.equal(reloaded.view().theme.id, 'cinnabar-paper')
  for (const id of ['cinnabar-paper', 'sequence-light', 'white-violet']) assert.equal(api.importTheme(JSON.stringify({ ...clone(raw), id })).ok, false)
  assert.equal(api.removeTheme('cinnabar-paper').ok, false)
  assert.equal(api.view().theme.id, 'cinnabar-paper')
})

test('国风朱红样式全部身份作用域、无字面色值，且不新增门禁违规或债务', () => {
  const css = fs.readFileSync(cssFile, 'utf8')
  assert.ok(!/#[0-9a-f]{3,8}\b|\brgba?\(/i.test(css), '主题CSS不得保留字面调色板')
  const root = postcss.parse(css)
  let rules = 0
  root.walkRules(rule => {
    rules++
    for (const selector of rule.selectors) assert.match(selector, /\[data-theme-id="cinnabar-paper"\]/, selector)
  })
  assert.ok(rules > 80, `规则数=${rules}`)
  const { lintCssAst } = require('./theme-lint/css-ast.cjs')
  const report = lintCssAst(path.join(__dirname, '..'))
  const rel = 'src/features/courses/styles/cinnabar-paper.css'
  assert.deepEqual(report.violations.filter(v => v.file === rel), [])
  const debt = JSON.parse(fs.readFileSync(path.join(__dirname, 'theme-lint/css-debt.json'), 'utf8'))
  assert.deepEqual(debt.debt.filter(d => d.file === rel), [])
})

test('国风朱红声明的本地素材全部注册且文件真实存在', () => {
  const registry = fs.readFileSync(path.join(src, 'builtin-assets.ts'), 'utf8')
  for (const asset of candidate.display.assets) assert.ok(registry.includes(`'cinnabar-paper::${asset.key}'`), asset.key)
  for (const name of ['cinnabar-paper-grain.svg', 'cinnabar-paper-meander.svg', 'cinnabar-paper-seal.svg']) {
    assert.ok(fs.existsSync(path.join(src, 'assets', name)), name)
    assert.ok(registry.includes(`./assets/${name}`), name)
  }
})

test('字体回退只新增本机已装族名：序光/白紫字族栈保持原样', () => {
  const loader = fs.readFileSync(path.join(src, 'display-loader.ts'), 'utf8')
  assert.match(loader, /editorial: "'Noto Serif CJK SC','Source Han Serif SC','Noto Serif SC','SimSun',serif"/)
  assert.match(loader, /humanist: "'Noto Sans CJK SC','Source Han Sans SC','Noto Sans SC','Microsoft YaHei UI',sans-serif"/)
  assert.match(loader, /modern: "'Segoe UI Variable Display','Segoe UI','Microsoft YaHei UI',sans-serif"/)
  assert.match(loader, /ui: "'Segoe UI Variable Text','Segoe UI','Microsoft YaHei UI',sans-serif"/)
  assert.equal(candidate.display.heading_family, 'editorial')
  assert.equal(candidate.display.body_family, 'humanist')
  for (const t of formal) { assert.notEqual(t.display.heading_family, 'editorial'); assert.notEqual(t.display.body_family, 'humanist') }
})

test('样式层叠顺序：国风朱红在两套正式主题之后、共享文档结构之前', () => {
  const index = fs.readFileSync(path.join(__dirname, '../src/shared/styles/index.css'), 'utf8')
  const sequence = index.indexOf('sequence-light.css'), candidatePos = index.indexOf('cinnabar-paper.css'), documentTemplate = index.indexOf('document-template.css')
  assert.ok(sequence > 0 && candidatePos > sequence && documentTemplate > candidatePos)
})

test('国风朱红与序光/白紫存在至少三项非颜色差异', () => {
  for (const t of formal) {
    const diffs = Object.keys(candidate.display).filter(key => !['assets'].includes(key) && JSON.stringify(candidate.display[key]) !== JSON.stringify(t.display[key]))
    assert.ok(diffs.length >= 3, `${t.id}: ${diffs.join(',')}`)
    assert.notEqual(candidate.presentation.heading, t.presentation.heading)
  }
})