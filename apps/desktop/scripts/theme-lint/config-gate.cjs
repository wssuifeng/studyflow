// W4 配置门禁（主设计§8.3第1道）：内置主题 JSON 必须全部通过 contract.parseTheme。
// 拒绝未知字段、可执行内容（url()/javascript:/expression()）、越界数值与对比度不足；
// 旧 v1 配置兼容（缺 display 字段时由 displayFromPresentation 推导）。主题切换不写 Core 业务数据。
//
// contract.ts 经 ts.transpileModule + vm 沙箱加载（仅允许同目录互引），不引第三份校验实现。
const fs = require('node:fs'), path = require('node:path'), vm = require('node:vm'), ts = require('typescript')

function loadContractModule(name, themesDir, cache = new Map()) {
  if (cache.has(name)) return cache.get(name)
  const source = fs.readFileSync(path.join(themesDir, name + '.ts'), 'utf8')
  const module = { exports: {} }
  const localRequire = id => {
    const dep = id.replace(/^\.\//, '')
    if (!/^[a-z0-9-]+$/i.test(dep)) throw new Error('契约只允许引用同目录模块')
    return loadContractModule(dep, themesDir, cache)
  }
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module, exports: module.exports, require: localRequire })
  cache.set(name, module.exports)
  return module.exports
}

function parseThemeObject(theme, themesDir) {
  return loadContractModule('contract', themesDir).parseTheme(theme)
}

function lintConfig(builtinDir, themesDir) {
  const failures = []
  let validated = 0
  for (const name of fs.readdirSync(builtinDir).filter(n => n.endsWith('.json'))) {
    try { parseThemeObject(JSON.parse(fs.readFileSync(path.join(builtinDir, name), 'utf8')), themesDir); validated++ }
    catch (error) { failures.push({ rule: 'THEME_CONFIG_INVALID', where: `builtin/${name}`, detail: error.message }) }
  }
  return { validated, failures }
}

module.exports = { lintConfig, parseThemeObject, loadContractModule }
