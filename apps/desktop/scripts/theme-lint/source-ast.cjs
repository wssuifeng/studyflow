// W4 源码AST门禁（主设计§8.3第2道）：真实 TS + Vue SFC 解析，检测业务层「以主题身份决定功能/结构」的分支。
//
// 数据流模型（静态可判定的部分，边界如实声明，不宣称识别任意JS动态行为）：
//   污点源   = 注册/退役主题ID字面量（builtin/*.json + controller.retiredBuiltinIds，AST解析，不硬编码两个名字）
//             + 从主题系统模块导入的身份承载绑定：activeTheme/availableThemes/themeState/
//               displayThemeId/currentDisplayTheme/DEFAULT_THEME（含命名空间导入）
//   污点传播 = const/computed 初始化引用污点 → 本地标识符污点（迭代到不动点）
//             + <污点>.find/filter/some/every/map/forEach 回调参数污点
//             + 成员链仅经 id/theme/value（ref解包）继续污点；.sound_profile/.appearance/.tokens 等
//               受控 profile 字段【不】传播（比较它们是契约允许的 profile 应用，不是主题身份分支）
//             + 模板 v-for 别名在迭代污点集合时污点（作用域内有效）
//   函数调用 = 数据流而非分支：调用表达式整体不传播污点（主题系统helper如 isThemeActive 封装身份比较
//             属既定模式；把分支包进任意函数再调用属静态分析盲区，依赖源码评审，见报告「静态解析边界」）
//   汇（违规）= if/while/switch/三元/逻辑 测试表达式含主题身份引用（THEME_ID_BRANCH）
//             + 模板 v-if/v-else-if/v-show 表达式含主题身份引用（THEME_ID_TEMPLATE_BRANCH）
//             + 模板 :class/:style 值的条件/对象值/数组项含主题身份引用（THEME_ID_TEMPLATE_CLASS）
//   非汇     = 属性绑定（如 data-theme-display）、文本插值、事件语句、资产/视图查找的实参传递
//   文件级豁免 = 仅 src/shared/themes/**（注册/校验/资产层）；其余一律精确例外（source-exceptions.json：
//             文件+行号区间+规则+理由+收口任务，行号漂移即失配→过期提示/重新违规）。
const fs = require('node:fs'), path = require('node:path')
const ts = require('typescript')
const { parse: parseSfc } = require('@vue/compiler-sfc')

// 从主题系统模块导出的、承载「主题身份」的绑定名（其余导出为受控profile/动作/消息，不承载身份）。
const IDENTITY_EXPORTS = new Set(['activeTheme', 'availableThemes', 'themeState', 'displayThemeId', 'currentDisplayTheme', 'DEFAULT_THEME'])
const THEME_MODULE_SPECIFIER = /(?:^|[/\\])themes(?:[/\\]|$)/
// 污点成员链：id=身份，theme=availableThemes 项的 Theme 包装，value=Vue ref 解包。
const TAINTED_MEMBERS = new Set(['id', 'theme', 'value'])
const ITERATOR_METHODS = new Set(['find', 'filter', 'some', 'every', 'map', 'forEach', 'flatMap', 'findLast', 'sort', 'reduce'])

function walkFiles(root, extensions, found) {
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (entry.name === 'node_modules' || entry.name === '.git') continue
    const full = path.join(root, entry.name)
    if (entry.isDirectory()) walkFiles(full, extensions, found)
    else if (extensions.some(ext => entry.name.endsWith(ext))) found.push(full)
  }
  return found
}
const relTo = (root, file) => path.relative(root, file).split(path.sep).join('/')

/** 注册/退役主题ID集合：builtin JSON 的 id + controller.ts 中 new Set([...]) 的字面量。 */
function resolveThemeIds(themesDir) {
  const ids = new Set()
  const builtinDir = path.join(themesDir, 'builtin')
  const scan = fs.existsSync(builtinDir) ? builtinDir : themesDir
  for (const name of fs.readdirSync(scan).filter(n => n.endsWith('.json'))) {
    try { const id = JSON.parse(fs.readFileSync(path.join(scan, name), 'utf8')).id; if (typeof id === 'string') ids.add(id) } catch { /* 非法JSON由配置门禁报告 */ }
  }
  const controller = path.join(themesDir, 'controller.ts')
  if (fs.existsSync(controller)) {
    const sf = ts.createSourceFile(controller, fs.readFileSync(controller, 'utf8'), ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS)
    const visit = node => {
      if (ts.isVariableDeclaration(node) && node.name.getText() === 'retiredBuiltinIds' && node.initializer && ts.isNewExpression(node.initializer)) {
        const args = node.initializer.arguments
        if (args && ts.isArrayLiteralExpression(args[0])) for (const el of args[0].elements) if (ts.isStringLiteral(el)) ids.add(el.text)
      }
      ts.forEachChild(node, visit)
    }
    visit(sf)
  }
  return ids
}

// ── 表达式身份分析 ───────────────────────────────────────────────
function isTaintedValue(node, tainted) {
  if (!node) return false
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return tainted.themeIds.has(node.text)
  if (ts.isIdentifier(node)) return tainted.names.has(node.text)
  if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression)) {
    const prop = ts.isPropertyAccessExpression(node) ? node.name.text : node.argumentExpression.text
    return TAINTED_MEMBERS.has(prop) && isTaintedValue(node.expression, tainted)
  }
  return false
}
/**
 * 表达式是否含「主题身份引用」（用于汇判定）。语义：
 *   · 调用表达式整棵跳过（数据流）；
 *   · 非传播成员（profile/token字段）且基为污点 → 整棵跳过（受控profile应用）；
 *   · 其余节点递归（对象字面量递归属性值；模板串递归span）。
 */
function containsIdentity(node, tainted) {
  if (!node) return false
  if (ts.isCallExpression(node)) return false
  if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))) {
    const prop = ts.isPropertyAccessExpression(node) ? node.name.text : (ts.isStringLiteral(node.argumentExpression) ? node.argumentExpression.text : '')
    if (prop && !TAINTED_MEMBERS.has(prop)) {
      if (isTaintedValue(node.expression, tainted)) return false
    }
  }
  if (isTaintedValue(node, tainted)) return true
  if (ts.isObjectLiteralExpression(node)) return node.properties.some(prop => ts.isPropertyAssignment(prop) && containsIdentity(prop.initializer, tainted))
  if (ts.isArrayLiteralExpression(node)) return node.elements.some(el => containsIdentity(el, tainted))
  if (ts.isTemplateExpression(node)) return node.templateSpans.some(span => containsIdentity(span.expression, tainted))
  let hit = false
  ts.forEachChild(node, child => { if (!hit && containsIdentity(child, tainted)) hit = true })
  return hit
}

// ── 脚本分析：污点集 + 汇 ────────────────────────────────────────
function collectScriptTaint(sf, tainted) {
  // 导入污点源
  const visitImports = node => {
    if (ts.isImportDeclaration(node) && node.importClause && ts.isStringLiteral(node.moduleSpecifier) && THEME_MODULE_SPECIFIER.test(node.moduleSpecifier.text)) {
      const clause = node.importClause
      if (clause.name) tainted.names.add(clause.name.text) // default 导入视为身份承载（保守）
      if (clause.namedBindings) {
        if (ts.isNamespaceImport(clause.namedBindings)) tainted.names.add(clause.namedBindings.name.text)
        else for (const el of clause.namedBindings.elements) if (IDENTITY_EXPORTS.has(el.propertyName ? el.propertyName.text : el.name.text)) tainted.names.add(el.name.text)
      }
    }
    ts.forEachChild(node, visitImports)
  }
  visitImports(sf)
  // 局部传播到不动点
  for (let round = 0; round < 4; round++) {
    let added = false
    const visit = node => {
      if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
        const init = node.initializer
        let taint = containsIdentity(init, tainted)
        if (!taint && ts.isCallExpression(init)) {
          const callee = init.expression.getText()
          if (/^(computed|ref|shallowRef|readonly|toRef)$/.test(callee) && init.arguments.length) taint = containsIdentity(init.arguments[0], tainted)
        }
        if (taint && !tainted.names.has(node.name.text)) { tainted.names.add(node.name.text); added = true }
      }
      if (ts.isCallExpression(node) && node.arguments.length && ts.isArrowFunction(node.arguments[0]) || ts.isCallExpression(node) && node.arguments.length && ts.isFunctionExpression(node.arguments[0])) {
        // <污点>.iterator(cb) → 回调参数污点
        const callee = node.expression
        if (ts.isPropertyAccessExpression(callee) && ITERATOR_METHODS.has(callee.name.text) && isTaintedValue(callee.expression, tainted)) {
          const cb = node.arguments[0]
          if (cb.parameters.length && ts.isIdentifier(cb.parameters[0].name)) {
            const name = cb.parameters[0].name.text
            if (!tainted.names.has(name)) { tainted.names.add(name); added = true }
          }
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(sf)
    if (!added) break
  }
}

function scriptSinks(sf, tainted, rel, push) {
  const checkTest = (test, getLine, snippet) => {
    if (test && containsIdentity(test, tainted)) push({ rule: 'THEME_ID_BRANCH', file: rel, line: getLine(), snippet })
  }
  const visit = node => {
    if (ts.isIfStatement(node)) checkTest(node.expression, () => sf.getLineAndCharacterOfPosition(node.expression.getStart()).line + 1, node.expression.getText())
    if (ts.isWhileStatement(node) || ts.isDoStatement(node)) checkTest(node.expression, () => sf.getLineAndCharacterOfPosition(node.expression.getStart()).line + 1, node.expression.getText())
    if (ts.isConditionalExpression(node)) checkTest(node.condition, () => sf.getLineAndCharacterOfPosition(node.condition.getStart()).line + 1, node.condition.getText())
    if (ts.isSwitchStatement(node)) for (const clause of node.caseBlock.clauses) checkTest(clause.expression, () => sf.getLineAndCharacterOfPosition(clause.getStart()).line + 1, clause.getText().slice(0, 80))
    ts.forEachChild(node, visit)
  }
  visit(sf)
}

// ── 模板分析（compiler-sfc 的原始模板AST：指令仍是 props 中的 DIRECTIVE 节点） ──
const T_ELEMENT = 1, T_DIRECTIVE = 7, T_SIMPLE_EXPRESSION = 4
function parseTemplateExpression(content) {
  // 模板表达式是JS表达式；包一层 const __v = (...) 用TS解析（v-for 专用的 "alias in list" 不走此路径）
  const sf = ts.createSourceFile('expr.ts', `const __v = (${content})`, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS)
  let found
  const visit = node => { if (ts.isVariableDeclaration(node) && node.name.getText() === '__v') found = node.initializer; ts.forEachChild(node, visit) }
  visit(sf)
  return found
}
function templateSinks(ast, tainted, rel, fullSource, push, diagnostics) {
  const baseOffset = ast?.loc?.start?.offset ?? 0
  const lineAt = offset => {
    // compiler-sfc 的模板AST定位基于整份SFC源文本；若越界按内容行号估算并记录诊断。
    let line = 1
    const limit = Math.min(offset, fullSource.length)
    for (let i = 0; i < limit; i++) if (fullSource.charCodeAt(i) === 10) line++
    return line
  }
  const expIdentity = (content, prop) => {
    const node = parseTemplateExpression(content)
    if (!node) { diagnostics.push(`模板表达式解析失败：${rel} @ ${prop}`); return false }
    return containsIdentity(node, tainted)
  }
  const checkClassStyle = (dir, tag) => {
    const content = dir.exp?.content
    if (!content) return
    const node = parseTemplateExpression(content)
    if (!node) { diagnostics.push(`:class/:style 表达式解析失败：${rel} <${tag}>`); return }
    // :class 值：对象字面量看属性值、数组看项、三元看测试；其余整体判定
    if (ts.isObjectLiteralExpression(node)) {
      for (const prop of node.properties) {
        if (ts.isPropertyAssignment(prop) && containsIdentity(prop.initializer, tainted)) push({ rule: 'THEME_ID_TEMPLATE_CLASS', file: rel, line: lineAt(baseOffset + (dir.loc?.start?.offset ?? 0)), snippet: `${tag} :class ${prop.name.getText()}` })
      }
    } else if (containsIdentity(node, tainted)) {
      push({ rule: 'THEME_ID_TEMPLATE_CLASS', file: rel, line: lineAt(baseOffset + (dir.loc?.start?.offset ?? 0)), snippet: `${tag} :${dir.arg?.content ?? ''}` })
    }
  }
  const walk = (node, scope) => {
    if (!node || typeof node !== 'object') return
    if (node.type === T_ELEMENT) {
      const nextScope = scope
      let vforAliases = null
      for (const prop of node.props || []) {
        if (prop.type !== T_DIRECTIVE) continue
        if (prop.name === 'if' || prop.name === 'else-if' || prop.name === 'show') {
          const content = prop.exp?.content
          if (content && expIdentity(content, prop.name)) push({ rule: 'THEME_ID_TEMPLATE_BRANCH', file: rel, line: lineAt(baseOffset + (prop.loc?.start?.offset ?? 0)), snippet: `v-${prop.name}="${content}"` })
        } else if (prop.name === 'bind' && (prop.arg?.content === 'class' || prop.arg?.content === 'style') && prop.exp?.content) {
          checkClassStyle(prop, node.tag)
        } else if (prop.name === 'for' && prop.exp?.content) {
          // v-for：别名作用域污点（迭代污点集合时）
          const match = /^(.*?)\s+in\s+(.*)$/s.exec(prop.exp.content)
          if (match) {
            const aliases = match[1].replace(/^\(|\)$/g, '').split(',').map(s => s.trim()).filter(Boolean)
            const iterable = parseTemplateExpression(match[2])
            if (iterable && containsIdentity(iterable, tainted)) vforAliases = aliases
          }
        }
      }
      const childScope = vforAliases ? new Map(scope) : scope
      if (vforAliases) for (const alias of vforAliases) childScope.set(alias, true)
      const saved = tainted
      if (vforAliases) {
        const merged = new Set(tainted.names)
        for (const alias of vforAliases) merged.add(alias)
        tainted = { names: merged, themeIds: tainted.themeIds }
      }
      for (const child of node.children || []) walk(child, childScope)
      if (vforAliases) tainted = saved
      return
    }
    for (const child of node.children || []) walk(child, scope)
    if (node.branches) for (const branch of node.branches) walk(branch, scope) // 已变换的 IF 节点兜底
  }
  walk(ast, new Map())
}

// ── 例外 ────────────────────────────────────────────────────────
function loadExceptions(file) {
  if (!fs.existsSync(file)) return []
  const raw = JSON.parse(fs.readFileSync(file, 'utf8'))
  if (!Array.isArray(raw)) throw new Error('source-exceptions.json 必须是数组')
  for (const item of raw) {
    for (const field of ['file', 'rule', 'lineFrom', 'lineTo', 'syntax', 'reason', 'closure']) {
      if (!(field in item)) throw new Error(`源码例外缺字段 ${field}：${JSON.stringify(item).slice(0, 120)}`)
    }
  }
  return raw
}

/**
 * @param root 仓库内 apps/desktop 根
 * @param options.files 显式文件列表（测试用）；缺省扫描 src
 */
function lintSourceAst(root, options = {}) {
  const themesDir = path.join(root, 'src/shared/themes')
  const themeIds = resolveThemeIds(themesDir)
  const exceptions = loadExceptions(path.join(__dirname, 'source-exceptions.json'))
  const files = options.files || walkFiles(path.join(root, 'src'), ['.vue', '.ts'], [])
  const violations = [], diagnostics = [], stale = []
  const used = new Set()
  for (const file of files) {
    const rel = relTo(root, file)
    if (rel.startsWith('src/shared/themes/')) continue // 注册/校验/资产层（主设计§8.1）
    const source = fs.readFileSync(file, 'utf8')
    const tainted = { names: new Set(), themeIds }
    if (rel.endsWith('.vue')) {
      let descriptor
      try { descriptor = parseSfc(source, { filename: file }).descriptor } catch (error) { diagnostics.push(`SFC解析失败 ${rel}: ${error.message}`); continue }
      for (const block of [descriptor.script, descriptor.scriptSetup]) {
        if (!block?.content) continue
        const sf = ts.createSourceFile(rel, block.content, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS)
        collectScriptTaint(sf, tainted)
      }
      for (const block of [descriptor.script, descriptor.scriptSetup]) {
        if (!block?.content) continue
        const sf = ts.createSourceFile(rel, block.content, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS)
        scriptSinks(sf, tainted, rel, violations.push.bind(violations))
      }
      if (descriptor.template?.ast) templateSinks(descriptor.template.ast, tainted, rel, source, violations.push.bind(violations), diagnostics)
    } else {
      const sf = ts.createSourceFile(rel, source, ts.ScriptTarget.ES2022, true, ts.ScriptKind.TS)
      collectScriptTaint(sf, tainted)
      scriptSinks(sf, tainted, rel, violations.push.bind(violations))
    }
  }
  // 精确例外匹配（文件+规则+行号区间）；失配的例外记为过期。
  const unmatched = violations.filter(v => {
    const index = exceptions.findIndex(e => e.file === v.file && e.rule === v.rule && v.line >= e.lineFrom && v.line <= e.lineTo)
    if (index >= 0) { used.add(index); return false }
    return true
  })
  for (let i = 0; i < exceptions.length; i++) if (!used.has(i)) stale.push({ ...exceptions[i], stale: true })
  return { themeIds: [...themeIds], violations: unmatched, staleExceptions: stale, diagnostics, checked: files.length }
}

module.exports = { lintSourceAst, resolveThemeIds }
