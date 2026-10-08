const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
const mod={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/courses/dock/state.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:mod,exports:mod.exports})
const {normalizeDock,activateTool,closeTool,splitTools,reorderTools}=mod.exports
const array=a=>Array.from(a)
test('关闭所有标签为零宽收起，重新打开不丢布局顺序',()=>{let s=normalizeDock();for(const t of ['notes','exercises'])s=closeTool(s,t);assert.equal(s.collapsed,true);assert.equal(s.open.length,0);s=activateTool(s,'notes');assert.equal(s.collapsed,false);assert.deepEqual(array(s.panes),['notes'])})
test('最多两个窗格、不能同一工具双写、宽度不足拒绝分屏',()=>{let s=normalizeDock();assert.equal(splitTools(s,'notes',559),s);s=splitTools(s,'notes',600);assert.deepEqual(array(s.panes),['exercises','notes']);s=activateTool(s,'notes',1);assert.equal(s.panes.length,2);s=activateTool(s,'exercises',1);assert.equal(s.panes.length,2);assert.equal(new Set(s.panes).size,2)})
test('损坏布局恢复有效范围且过滤未知工具',()=>{const s=normalizeDock({open:['notes','terminal','notes'],panes:['notes','notes'],order:['outline'],width:-3,split:4});assert.deepEqual(array(s.open),['notes']);assert.equal(s.width,280);assert.equal(s.split,.8);assert.equal(s.order.length,2)})
test('标签重排不修改工具内容及活动窗格',()=>{const s=normalizeDock();const next=reorderTools(s,'notes','exercises');assert.deepEqual(array(next.order),['notes','exercises']);assert.deepEqual(array(next.panes),array(s.panes));assert.deepEqual(array(s.order),['exercises','notes'])})
test('拖放到自身是 no-op，不会把工具插到末尾',()=>{const s=normalizeDock();const next=reorderTools(s,'notes','notes');assert.deepEqual(array(next.order),array(s.order))})

function bridgeFixture({creationFails=false,ready=true,listFails=false,releaseFails=false,tauri=true,listenFails=false,windows=[{tool:'notes',context:{studyId:'s1'}}],childFailures=[]}={}) {
 const handlers=new Map(),emissions=[];let key=0
 const events={listen:async(name,fn)=>{if(listenFails)throw Error('listener unavailable');handlers.set(name,fn);return()=>handlers.delete(name)},emitTo:async(label,name,payload)=>{
  emissions.push([label,name])
  if(childFailures.includes(label))throw Error('child closed')
  if(name==='studyflow-tool-probe'&&ready)handlers.get('studyflow-tool-ready')?.({payload:{tool:'notes',studyId:'s1',ok:true}})
  if(name==='studyflow-tool-prepare')handlers.get('studyflow-tool-ack')?.({payload:{requestId:payload.requestId,tool:'notes',ok:false}})
  if(name==='studyflow-tool-release'&&releaseFails)throw Error('child closed')
 }}
 const bridge={exports:{}}
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/courses/dock/toolWindows.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{
  module:bridge,exports:bridge.exports,setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,30)),clearTimeout,console,
  require:n=>n==='@tauri-apps/api/core'?{invoke:async command=>{if(command==='tool_windows'){if(listFails)throw Error('bridge offline');return windows}if(creationFails)throw Error('creation failed')}}:n==='@tauri-apps/api/event'?events:n.includes('shared/api')?{isTauri:()=>tauri}:n.includes('shared/ui')?{makeRequestKey:()=>String(++key)}:require(n)
 })
 return {api:bridge.exports,handlers,emissions}
}
test('创建命令成功不等于内容加载成功，未就绪超时不误报',async()=>{const f=bridgeFixture({ready:false});assert.equal(await f.api.openToolWindow('notes',{studyId:'s1'}),false);assert.equal(f.handlers.size,0)})
test('窗口内容确认后就绪，失败创建及时返回并清理监听',async()=>{const f=bridgeFixture();assert.equal(await f.api.openToolWindow('notes',{studyId:'s1'}),true);assert.equal(f.handlers.size,0);const bad=bridgeFixture({creationFails:true});assert.equal(await bad.api.openToolWindow('notes',{studyId:'s1'}),false);assert.equal(bad.handlers.size,0)})
test('子窗保存失败和枚举异常均明确失败，已关子窗不阻碍主窗解锁',async()=>{const f=bridgeFixture({releaseFails:true});assert.equal((await f.api.prepareTools('hold')).ok,false);await f.api.releaseTools('x');assert.equal(f.handlers.size,0);assert.equal((await bridgeFixture({listFails:true}).api.prepareTools()).ok,false)})


test('非 Tauri 环境不调用独立窗口桥接',async()=>{const f=bridgeFixture({tauri:false});assert.equal(await f.api.openToolWindow('notes',{studyId:'s1'}),false);assert.equal(await f.api.addDetachedNote('p',{id:'n',text:'x'}),false);await f.api.suspendTools();assert.deepEqual(f.emissions,[])})
test('监听器初始化失败时返回失败而不抛出',async()=>{const f=bridgeFixture({listenFails:true});assert.equal(await f.api.openToolWindow('notes',{studyId:'s1'}),false);assert.equal(await f.api.addDetachedNote('p',{id:'n',text:'x'}),false);assert.equal((await f.api.prepareTools()).ok,false)})
test('挂起一个已关闭子窗不会阻塞其他工具',async()=>{const f=bridgeFixture({windows:[{tool:'notes',context:{studyId:'s1'}},{tool:'exercises',context:{studyId:'s1'}}],childFailures:['tool-notes']});await assert.doesNotReject(f.api.suspendTools());assert.ok(f.emissions.some(([label,name])=>label==='tool-notes'&&name==='studyflow-tool-suspend'));assert.ok(f.emissions.some(([label,name])=>label==='tool-exercises'&&name==='studyflow-tool-suspend'))})

test('工具内容对未知标签使用安全分支，不把未知状态当笔记渲染',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/courses/components/CourseToolContent.vue'),'utf8')
 assert.match(source,/tool===['"]exercises['"]/) 
 assert.match(source,/tool===['"]notes['"]/)
 assert.ok(!/<PlanNotebook v-else(\s|>)/.test(source))
 assert.match(source,/工具暂不可用|未知工具|暂不可用/)
})

