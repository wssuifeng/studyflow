/* W4 主题程序门禁测试套件（主设计§8.3 + 续行提示词§4.2/§4.3）。
   先红：合成 fixture 必须被门禁拒绝；后绿：合法配置映射/资产查询/共享结构/装饰槽不误报。
   反洗白：--update-debt 拒绝新增；测试固化 css-debt 债务 id 摘要，手改 JSON 加项即破坏。
   node --test scripts/test-theme-lint.cjs */
const test = require('node:test'), assert = require('node:assert/strict')
const fs = require('node:fs'), path = require('node:path'), os = require('node:os'), crypto = require('node:crypto')
const lint = require('./theme-lint.cjs')
const cssAst = require('./theme-lint/css-ast.cjs')
const ROOT = path.join(__dirname, '..')

function tempFile(ext, content) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'theme-lint-'))
  const file = path.join(dir, 'probe' + ext)
  fs.writeFileSync(file, content, 'utf8')
  return { file, dir }
}
function tempRootWithThemes(themeId) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'srcast-'))
  fs.mkdirSync(path.join(dir, 'src/shared/themes/builtin'), { recursive: true })
  if (themeId) fs.writeFileSync(path.join(dir, 'src/shared/themes/builtin', `${themeId}.json`), JSON.stringify({ id: themeId }))
  return dir
}
const matchRule = (list, rule) => list.filter(v => (v.rule || v.name) === rule || v.name === rule)

// ── 源码AST门禁：失败 fixture ──────────────────────────────────────
test('源码门禁失败：直接主题身份分支', () => {
  const f = tempFile('.vue', `<script setup lang="ts">import {displayThemeId} from "../shared/themes/display-loader"\nif (displayThemeId.value === "sequence-light") x()\n</script><template><i/></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_ID_BRANCH').length, 1)
})
test('源码门禁失败：导入常量/别名比较', () => {
  const f = tempFile('.vue', `<script setup lang="ts">import {DEFAULT_THEME as D} from "../shared/themes/contract"\nif (tid === D.id) y()\n</script><template><i/></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_ID_BRANCH').length, 1)
})
test('源码门禁失败：computed→模板 v-if 分支', () => {
  const f = tempFile('.vue', `<script setup lang="ts">import {computed} from "vue"\nimport {activeTheme} from "../shared/themes"\nconst seq = computed(() => activeTheme.value?.id === "white-violet")\n</script><template><div v-if="seq">X</div></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_ID_TEMPLATE_BRANCH').length, 1)
})
test('源码门禁失败：computed→模板 :class 条件', () => {
  const f = tempFile('.vue', `<script setup lang="ts">import {computed} from "vue"\nimport {activeTheme} from "../shared/themes"\nconst seq = computed(() => activeTheme.value?.id === "white-violet")\n</script><template><div :class="{ narrow: seq }">X</div></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_ID_TEMPLATE_CLASS').length, 1)
})
test('源码门禁失败：新增注册主题ID后的分支（动态解析 builtin/*.json）', () => {
  const dir = tempRootWithThemes('blue-test')
  const f = path.join(dir, 'biz.vue')
  fs.writeFileSync(f, `<script setup lang="ts">const isNew = tid === "blue-test"\n</script><template><span v-show="isNew">D</span></template>`)
  const r = lint.lintSourceAst(dir, { files: [f] })
  assert.ok(r.themeIds.includes('blue-test'), '主题ID应动态解析自 builtin/*.json')
  assert.equal(matchRule(r.violations, 'THEME_ID_TEMPLATE_BRANCH').length, 1)
})
test('源码门禁失败：原 SidebarNav 白名单文件加入新的功能主题分支（文件不再整文件豁免）', () => {
  // 真实 SidebarNav 已迁移为无主题ID分支；复制后注入新分支必须失败（证明整文件白名单已废除）
  const real = fs.readFileSync(path.join(ROOT, 'src/app/layout/SidebarNav.vue'), 'utf8')
  const injected = real.replace('<script setup lang="ts">', `<script setup lang="ts">\nimport {displayThemeId as tid} from '../../shared/themes/display-loader'\nif (tid.value === 'sequence-light') console.log('seq branch')`)
  const f = tempFile('.vue', injected)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.ok(matchRule(r.violations, 'THEME_ID_BRANCH').length >= 1, 'SidebarNav 注入分支应失败')
})
test('源码门禁失败：v-for 别名迭代污点集合后的子元素身份分支', () => {
  const f = tempFile('.vue', `<script setup lang="ts">import {availableThemes} from "../shared/themes"\n</script><template><ul><li v-for="item in availableThemes"><span v-if="item.theme.id === 'sequence-light'">{{ item.theme.name }}</span></li></ul></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_ID_TEMPLATE_BRANCH').length, 1)
})

// ── 源码AST门禁：合法不误报 ───────────────────────────────────────
test('源码门禁合法：资产/视图查找、profile 比较、dataset 绑定、watch 信号、主题系统helper不误报', () => {
  const f = tempFile('.vue', `<script setup lang="ts">
import {activeTheme, availableThemes, isThemeActive} from "../shared/themes"
import {displayView} from "../shared/themes/view-registry"
import {displayThemeId} from "../shared/themes/display-loader"
import {watch} from "vue"
const v = displayView(displayThemeId.value, "shell")
const muted = activeTheme.sound_profile === "muted"
const custom = availableThemes.value.find(item => item.theme.id === activeTheme.value.id)?.source === "custom"
const link = activeTheme.value.id + ".json"
watch(() => activeTheme.value.id, () => scrollRestore())
</script>
<template><button :disabled="muted" v-if="muted" :data-theme-display="displayThemeId" :aria-pressed="isThemeActive({id:'x'})">{{ link }}</button></template>`)
  const r = lint.lintSourceAst(ROOT, { files: [f.file] })
  assert.equal(r.violations.length, 0, `不应误报：${JSON.stringify(r.violations)}`)
})
test('源码门禁：真实 src 树当前零违规（业务层无主题身份分支）', () => {
  const r = lint.lintSourceAst(ROOT)
  assert.deepEqual(r.violations, [])
  assert.equal(r.staleExceptions.length, 0)
})

// ── 配置门禁 ──────────────────────────────────────────────────────
test('配置门禁：内置主题全部通过 contract.parseTheme', () => {
  const r = lint.lintConfig(path.join(ROOT, 'src/shared/themes/builtin'), path.join(ROOT, 'src/shared/themes'))
  assert.deepEqual(r.failures, [])
  assert.ok(r.validated >= 2)
})
test('配置门禁：拒绝可执行内容/越界数值/未知字段', () => {
  const builtin = JSON.parse(fs.readFileSync(path.join(ROOT, 'src/shared/themes/builtin/white-violet.json'), 'utf8'))
  const { parseThemeObject } = require('./theme-lint/config-gate.cjs')
  const hostile = JSON.parse(JSON.stringify(builtin)); hostile.tokens['text.primary'] = 'url(javascript:alert(1))'
  assert.throws(() => parseThemeObject(hostile, path.join(ROOT, 'src/shared/themes')), /不合法|必须是|url|expression|不透明|格式/)
  const outOfRange = JSON.parse(JSON.stringify(builtin))
  if (outOfRange.display) outOfRange.display.navigation_width = 999
  else outOfRange.presentation = { ...outOfRange.presentation, density: 'compact' }
  assert.throws(() => parseThemeObject(outOfRange, path.join(ROOT, 'src/shared/themes')), /导航宽度|56|280|越界|不合法|必须是/)
  const unknownField = JSON.parse(JSON.stringify(builtin)); unknownField.unsupported_field = 'x'
  assert.throws(() => parseThemeObject(unknownField, path.join(ROOT, 'src/shared/themes')), /字段|不支持|不合法/)
})

// ── 样式AST门禁：失败 fixture ─────────────────────────────────────
test('CSS门禁失败：新增CSS文件身份作用域越权', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .main{grid-template-columns:1fr 1fr;overflow:hidden;position:absolute}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.ok(matchRule(r.violations, 'THEME_CSS_GRID').length >= 1)
  assert.ok(matchRule(r.violations, 'THEME_CSS_OVERFLOW_HIDDEN').length >= 1)
  assert.ok(matchRule(r.violations, 'THEME_CSS_ABSOLUTE_UNGUARDED').length >= 1)
})
test('CSS门禁失败：Vue <style> 内身份作用域越权', () => {
  const f = tempFile('.vue', `<template><div/></template><style>:root[data-theme-id="x"] .panel{display:none;position:fixed}</style>`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.ok(matchRule(r.violations, 'THEME_CSS_DISPLAY_NONE').length >= 1)
  assert.ok(matchRule(r.violations, 'THEME_CSS_FIXED').length >= 1)
})
test('CSS门禁失败：@media 嵌套身份作用域越权', () => {
  const f = tempFile('.css', `@media(max-width:800px){:root[data-theme-id="x"] .main{overflow:hidden;grid-template-columns:1fr}}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.ok(matchRule(r.violations, 'THEME_CSS_OVERFLOW_HIDDEN').length >= 1)
  assert.ok(matchRule(r.violations, 'THEME_CSS_GRID').length >= 1)
})
test('CSS门禁失败：功能按钮/侧栏用 display:none', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .sidebar .nav-item{display:none}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_CSS_DISPLAY_NONE').length, 1)
})
test('CSS门禁失败：新增布局 !important', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .panel{display:flex !important}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_CSS_LAYOUT_IMPORTANT').length, 1)
})
test('CSS门禁失败：非装饰槽绝对定位（即便加 pointer-events:none 也不放行）', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .main-content{position:absolute;pointer-events:none}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_CSS_ABSOLUTE_UNGUARDED').length, 1)
})
test('CSS门禁失败：视口高度单位', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .shell{height:100vh}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(matchRule(r.violations, 'THEME_CSS_VIEWPORT').length, 1)
})
test('CSS门禁失败：改旧值扩大结构影响（值漂移→旧债务失配+新违规）', () => {
  // 登记债务：height:50vh；实际改为 100vh → 值漂移使旧登记失配，新违规无登记 → 失败
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'css-drift-'))
  const cssPath = path.join(dir, 'probe.css')
  fs.writeFileSync(cssPath, ':root[data-theme-id="x"] .shell{height:100vh}')
  const rel = path.relative(ROOT, cssPath).split(path.sep).join('/')
  const debtFile = path.join(dir, 'debt.json')
  fs.writeFileSync(debtFile, JSON.stringify({ meta: {}, decorative: [], debt: [{
    id: 'probe-drift', file: rel, rule: 'THEME_CSS_VIEWPORT',
    selector: ':root[data-theme-id="x"] .shell', prop: 'height', value: '50vh',
    line: 1, reason: '登记值', closure: 'probe',
  }] }))
  const r = lint.lintCssAst(ROOT, { files: [cssPath], debtFile })
  assert.equal(matchRule(r.violations, 'THEME_CSS_VIEWPORT').length, 1, '值漂移后新违规应无登记 → 失败')
  assert.equal(r.staleDebt.length, 1, '旧登记应失配为过期提示')
})

// ── 样式AST门禁：合法不误报 ───────────────────────────────────────
test('CSS门禁合法：共享层无锚点结构规则不门禁', () => {
  const f = tempFile('.css', `.main{grid-template-columns:1fr;overflow:hidden;display:none;position:absolute;position:fixed;height:100vh;display:flex !important}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(r.violations.length, 0)
  assert.equal(r.notices.length, 0)
})
test('CSS门禁合法：身份作用域配色/token 不误报', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"]{--theme-text-primary:#112234}:root[data-theme-id="x"] .panel{color:var(--theme-text-primary);background:var(--theme-surface-panel);border-radius:8px;font-size:14px}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(r.violations.length, 0)
})
test('CSS门禁合法：受控装饰槽 display:none / pointer-events:none 绝对定位放行', () => {
  const f = tempFile('.css', `:root[data-theme-id="x"] .nav-icon-glyph{display:none}:root[data-theme-id="x"] .theme-reading-artwork{position:absolute;pointer-events:none}`)
  const r = lint.lintCssAst(ROOT, { files: [f.file] })
  assert.equal(r.violations.length, 0, `装饰槽不应误报：${JSON.stringify(r.violations)}`)
})
test('CSS门禁合法：契约作用域规则在 runtime.css 不门禁', () => {
  const r = lint.lintCssAst(ROOT, { files: [path.join(ROOT, 'src/shared/themes/runtime.css')] })
  assert.equal(r.violations.length, 0, 'runtime.css 契约映射不应被门禁')
})

// ── 防洗白与债务清单固化 ──────────────────────────────────────────
test('防洗白：--update-debt 拒绝新增项（不能借迁移把新违规合法化）', () => {
  const cur = JSON.parse(fs.readFileSync(path.join(__dirname, 'theme-lint/css-debt.json'), 'utf8'))
  const dropped = { ...cur, debt: cur.debt.slice(1) } // 删一项 → 该违规变为"新增"
  const tmp = path.join(os.tmpdir(), 'debt-anti.json'); fs.writeFileSync(tmp, JSON.stringify(dropped))
  assert.throws(() => lint.migrateDebt(ROOT, { debtFile: tmp }), /拒绝|不能自动合法化/)
})
test('防洗白：债务 id 集合摘要固化（手改 JSON 加项/换项即破坏测试）', () => {
  const debt = JSON.parse(fs.readFileSync(path.join(__dirname, 'theme-lint/css-debt.json'), 'utf8'))
  for (const d of debt.debt) for (const field of ['id', 'file', 'rule', 'selector', 'prop', 'value', 'reason', 'closure']) assert.ok(field in d, `债务项缺 ${field}`)
  const ids = debt.debt.map(d => d.id).sort()
  const digest = crypto.createHash('sha256').update(ids.join('\n')).digest('hex')
  // 摘要作为评审关卡：合法清理（仅删除项）需同步更新本断言；手改 JSON 加项/换项会破坏摘要。
  assert.equal(debt.debt.length, 52, `当前债务项数应为52（实际 ${debt.debt.length}；变更需同步更新本断言与摘要）`)
  assert.equal(digest, '159914d37fd60cac85f37ee8e8844ff9a851c68af3a019b29549591bd625ee1d', `债务id摘要（合法清理时同步更新）：${digest}`)
})
test('债务清单：每项都能在实际树匹配到真实违规（无幽灵债务）', () => {
  const r = lint.lintCssAst(ROOT)
  assert.equal(r.violations.length, 0, '当前实际违规应全部被债务清单覆盖')
  assert.equal(r.staleDebt.length, 0, '不应有失配的过期债务')
})

// ── 入口集成 ──────────────────────────────────────────────────────
test('runAll：真实树三道门禁全绿', () => {
  const report = lint.runAll()
  assert.equal(report.ok, true)
  assert.equal(report.violations.length, 0)
  assert.equal(report.diagnostics.length, 0)
  assert.ok(report.checked.sourceFiles > 100)
  assert.ok(report.checked.cssFiles > 50)
  assert.equal(report.checked.builtinThemes, 2)
  assert.ok(report.checked.themeIds.includes('sequence-light'))
  assert.ok(report.checked.themeIds.includes('white-violet'))
})
