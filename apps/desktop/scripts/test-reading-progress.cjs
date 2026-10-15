const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
const file=path.join(__dirname,'../src/features/courses/progressSaveQueue.ts')
function load(){const mod={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,{module:mod,exports:mod.exports,Promise});return mod.exports.createProgressSaveQueue()}
test('multiple saves waiting on an in-flight write remain serialized with fresh versions',async()=>{
 const run=load();let version=0,active=0,max=0;const captured=[];let release
 const gate=new Promise(resolve=>release=resolve)
 const save=()=>run(async()=>{active++;max=Math.max(max,active);const before=version;captured.push(before);if(before===0)await gate;version=before+1;active--;return true})
 const a=save(),b=save(),c=save();await Promise.resolve();release();assert.equal(await a,true);assert.equal(await b,true);assert.equal(await c,true)
 assert.equal(max,1);assert.deepEqual(captured,[0,1,2]);assert.equal(version,3)
})
test('a failed write does not poison the explicit retry lane',async()=>{const run=load();await assert.rejects(run(async()=>{throw Error('disk full')}));assert.equal(await run(async()=>true),true)})
