// W4 主题程序门禁入口（主设计§8.3 三道静态门禁 + 主题切换不写 Core）。
//   1) 源码AST门禁  scripts/theme-lint/source-ast.cjs —— 业务层主题身份分支（TS+Vue SFC 真实解析）
//   2) 配置门禁    scripts/theme-lint/config-gate.cjs —— 内置主题 JSON 经 contract.parseTheme
//   3) 样式AST门禁  scripts/theme-lint/css-ast.cjs    —— 主题身份作用域布局越权 + 精确债务清单（防洗白）
// 运行：npm run theme:lint            发现违规退出码 1
//       npm run theme:lint -- --update-debt  仅允许"删除"债务项（新增拒绝，防洗白）
const path = require('node:path')
const { lintSourceAst } = require('./theme-lint/source-ast.cjs')
const { lintConfig } = require('./theme-lint/config-gate.cjs')
const { lintCssAst, migrateDebt } = require('./theme-lint/css-ast.cjs')

const ROOT = path.join(__dirname, '..')
const THEMES_DIR = path.join(ROOT, 'src/shared/themes')
const BUILTIN_DIR = path.join(THEMES_DIR, 'builtin')

function runAll() {
  const source = lintSourceAst(ROOT)
  const config = lintConfig(BUILTIN_DIR, THEMES_DIR)
  const css = lintCssAst(ROOT)
  const violations = [
    ...source.violations.map(v => ({ gate: 'source', ...v })),
    ...config.failures.map(v => ({ gate: 'config', ...v })),
    ...css.violations.map(v => ({ gate: 'css', ...v })),
  ]
  const stale = [
    ...source.staleExceptions.map(e => ({ gate: 'source-stale', ...e })),
    ...css.staleDebt.map(d => ({ gate: 'css-stale', ...d })),
  ]
  return {
    ok: violations.length === 0,
    violations,
    stale, // 过期例外/债务：提示清理，非失败
    notices: css.notices,
    diagnostics: [...source.diagnostics, ...css.diagnostics],
    checked: {
      sourceFiles: source.checked,
      cssFiles: css.checked,
      builtinThemes: config.validated,
      cssDebt: css.debtCount,
      cssDecorative: css.decorativeCount,
      themeIds: source.themeIds,
    },
  }
}

module.exports = { runAll, lintSourceAst, lintConfig, lintCssAst, migrateDebt, THEMES_DIR, BUILTIN_DIR }

if (require.main === module) {
  if (process.argv.includes('--update-debt')) {
    try {
      const result = migrateDebt(ROOT)
      console.log(JSON.stringify({ ok: true, ...result }, null, 2))
    } catch (error) {
      console.error(JSON.stringify({ ok: false, error: error.message, added: error.added?.length || 0 }, null, 2))
      process.exitCode = 1
    }
  } else {
    const report = runAll()
    console.log(JSON.stringify(report, null, 2))
    if (!report.ok) process.exitCode = 1
  }
}
