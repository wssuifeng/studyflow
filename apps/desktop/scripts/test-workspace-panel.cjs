const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
function load(file,requireFn=require){const mod={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:mod,exports:mod.exports,require:requireFn,Symbol});return mod.exports}
const state=load('features/courses/dock/state.ts'),{restoreDockLayout}=load('features/courses/dock/restore.ts',n=>n==='./state'?state:require(n))
const {panelGeometry}=load('shared/layout/workspacePanel.ts')
test('新课程默认关闭，旧缓存宽度顺序保留但不擅自展开',()=>{assert.equal(state.normalizeDock().collapsed,true);const x=restoreDockLayout(JSON.stringify({collapsed:false,full:true,width:620,order:['notes','outline','exercises']}));assert.equal(x.collapsed,true);assert.equal(x.full,false);assert.equal(x.width,620);assert.equal(x.order[0],'notes');assert.equal(restoreDockLayout('{').collapsed,true)})
test('打开工具显式取消收起，不因默认策略阻止用户操作',()=>{const s=state.activateTool(restoreDockLayout(null),'notes');assert.equal(s.collapsed,false);assert.equal(s.panes[0],'notes')})
test('桌面三栏同时让出空间，阅读区保留最小宽度',()=>{for(const width of [900,1024,1279,1280,1440,1920]){const g=panelGeometry(width,820);assert.ok(width-g.navigation-g.width>=360);assert.ok(g.width>=280);assert.ok(g.width<=g.maxWidth)}})
test('窄屏工具占内容区域，专注模式不虚留导航宽度',()=>{const narrow=panelGeometry(730,420);assert.equal(narrow.compact,true);assert.equal(narrow.width,658);assert.equal(panelGeometry(730,420,false,true).width,730);assert.equal(panelGeometry(1440,420,true).width,1256)})

function soundFixture(initial='off',hidden=false,unavailable=false,focused=true,themeSound='soft-tap'){
 let stored=initial,volume=72,created=0,tones=0,now=1000;const events={}
 const mod={exports:{}}
 class Audio {constructor(){created++;if(unavailable)throw Error('no audio');this.currentTime=0;this.destination={}}resume(){return Promise.resolve()}createOscillator(){tones++;return{frequency:{value:0},connect(){},start(){},stop(){},disconnect(){}}}createGain(){return{gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){},disconnect(){}}}}
 vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/shared/ui/interaction.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:mod,exports:mod.exports,require:()=>({ref:value=>({value})}),localStorage:{getItem:k=>k.includes('volume')?String(volume):stored,setItem:(k,v)=>{if(k.includes('volume'))volume=Number(v);else stored=v}},document:{visibilityState:hidden?'hidden':'visible',hasFocus:()=>focused,documentElement:{dataset:{themeSound}}},window:{addEventListener:(n,f)=>events[n]=f},AudioContext:Audio,Date:{now:()=>now}})
 return{api:mod.exports,counts:()=>({created,tones}),volume:()=>volume,tick:()=>now+=200,events}
}
test('音效默认关闭且后台窗口不发声',async()=>{for(const f of [soundFixture(),soundFixture('on',true)]){f.api.interactionFeedback('complete');await Promise.resolve();assert.equal(f.counts().created,0)}})
test('显式启用后轻量合成，关闭立即阻断，音频不可用不阻碍操作',async()=>{const f=soundFixture();f.api.setSoundEnabled(true);f.api.interactionFeedback('complete');await Promise.resolve();assert.equal(f.counts().tones,2);f.tick();f.api.setSoundEnabled(false);f.api.interactionFeedback('move');assert.equal(f.counts().tones,2);assert.doesNotThrow(()=>soundFixture('on',false,true).api.interactionFeedback('preview'))})
test('音频异步恢复期间用户关闭声音也不得迟到播放',async()=>{const f=soundFixture('on');f.api.interactionFeedback('complete');f.api.setSoundEnabled(false);await Promise.resolve();assert.equal(f.counts().tones,0)})

test('主题音色尊重全局开关；静音主题和失焦窗口不创建音频对象',async()=>{for(const f of [soundFixture('on',false,false,false),soundFixture('on',false,false,true,'muted'),soundFixture('off',false,false,true,'glass')]){f.api.interactionFeedback('preview');await Promise.resolve();assert.equal(f.counts().created,0)}const f=soundFixture('on',false,false,true,'glass');f.api.interactionFeedback('complete');await Promise.resolve();assert.equal(f.counts().tones,2)})
test('音量偏好迁移、跨窗口存储和零音量阻断播放',async()=>{const f=soundFixture('on');assert.equal(f.api.soundVolume.value,72);f.api.setSoundVolume(35);assert.equal(f.api.soundVolume.value,35);assert.equal(f.volume(),35);f.api.interactionFeedback('preview');await Promise.resolve();assert.equal(f.counts().tones,2);f.tick();f.api.setSoundVolume(0);f.api.interactionFeedback('complete');await Promise.resolve();assert.equal(f.counts().tones,2)})
test('主题 shell contract 不得覆盖打开工具后的三栏几何',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../src/shared/themes/runtime.css'),'utf8')
 assert.match(css,/\.learning-shell:not\(\.focus-shell\):not\(\.panel-open\)/)
 assert.match(css,/grid-template-columns:var\(--panel-nav-width,184px\) minmax\(0,1fr\) var\(--panel-width,420px\)!important/)
 assert.match(css,/grid-template-columns:minmax\(0,1fr\) var\(--panel-width,420px\)!important/)
 assert.match(css,/\.learning-shell\.focus-shell:not\(\.panel-open\)[\s\S]*grid-template-columns:minmax\(0,1fr\)!important/)
 assert.match(css,/\.app-shell\.focus-shell:not\(\.panel-open\)[\s\S]*grid-template-columns:minmax\(0,1fr\)!important/)
})

