// Read-only candidate validation. Only our reviewed TS contract is compiled;
// the user-supplied file is parsed as JSON data and is never executed.
//
// 说明：契约现在依赖 display.ts（受控展示包）。这里给沙箱注入一个**只解析本目录契约模块**
// 的最小 require 外壳：既不暴露 Node 模块系统，也不让候选 JSON 有机会执行任何代码。
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
const THEMES_DIR=path.join(__dirname,'../src/shared/themes')
function loadContractModule(name){
  const source=fs.readFileSync(path.join(THEMES_DIR,name+'.ts'),'utf8')
  const module={exports:{}}
  const localRequire=id=>{
    const dep=id.replace(/^\.\//,'')
    if(!/^[a-z0-9-]+$/i.test(dep))throw new Error('契约只允许引用同目录模块')
    return loadContractModule(dep)
  }
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module,exports:module.exports,require:localRequire})
  return module.exports
}
const filename=process.argv[2]
if(!filename){console.error('Usage: node scripts/check-theme.cjs <theme.json>');process.exitCode=2}
else try {
  const contract=loadContractModule('contract'),absolute=path.resolve(filename)
  if(fs.statSync(absolute).size>contract.MAX_THEME_BYTES)throw Error('主题配置最多32KB。')
  const theme=contract.parseTheme(JSON.parse(fs.readFileSync(absolute,'utf8')))
  console.log(JSON.stringify({ok:true,schema_version:theme.schema_version,id:theme.id,name:theme.name,appearance:theme.appearance,token_count:Object.keys(theme.tokens).length}))
} catch(error) {console.error(JSON.stringify({ok:false,error:error.message}));process.exitCode=1}
