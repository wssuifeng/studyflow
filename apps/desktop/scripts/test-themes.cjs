const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
const src=path.join(__dirname,'../src/shared/themes')
function load(file,dependency={}) {const mod={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(src,file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:mod,exports:mod.exports,require:n=>dependency[n]||require(n),Date,JSON,Math,Object,Array,Number,Set,Map,Error,String});return mod.exports}
const contract=load('contract.ts',{'./display':load('display.ts')}),{createThemeController}=load('controller.ts',{'./contract':contract})
const clone=x=>JSON.parse(JSON.stringify(x))
const builtin=fs.readdirSync(path.join(src,'builtin')).filter(n=>n.endsWith('.json')).map(n=>contract.parseTheme(JSON.parse(fs.readFileSync(path.join(src,'builtin',n),'utf8'))))
const sequence=builtin.find(x=>x.id==='sequence-light'),white=builtin.find(x=>x.id==='white-violet')
const legacyTheme=()=>{const raw=clone(white);delete raw.display;return raw}
function fixture(origin='window-a',initial=null,failWrite=false,failRead=false){let saved=initial,time=1000,applied=[],sent=[];const api=createThemeController(builtin,{origin,now:()=>++time,read:()=>{if(failRead)throw Error('unavailable');return saved},write:text=>{if(failWrite)throw Error('read only');saved=text},apply:t=>applied.push(t.id),publish:x=>sent.push(clone(x))});return {api,applied,sent,saved:()=>saved}}
/** 带展示偏好的控制器夹具：验证排版/图像强度与主题选择互不干扰。 */
function displayFixture(origin='window-a',initialDisplay=null){let saved=null,savedDisplay=initialDisplay,time=2000,applied=[],sent=[],sentDisplay=[];const api=createThemeController(builtin,{origin,now:()=>++time,read:()=>saved,write:text=>{saved=text},readDisplay:()=>savedDisplay,writeDisplay:text=>{savedDisplay=text},apply:t=>applied.push(t.id),publish:x=>sent.push(clone(x)),publishDisplay:x=>sentDisplay.push(clone(x))});return {api,applied,sent,sentDisplay,saved:()=>saved,savedDisplay:()=>savedDisplay}}

test('内置主题仅包含用户采纳的序光与白紫，默认白紫',()=>{assert.deepEqual(builtin.map(t=>t.id).sort(),['sequence-light','white-violet']);assert.equal(sequence.name,'序光');assert.equal(white.name,'白紫轻学');assert.equal(contract.DEFAULT_THEME.id,white.id);for(const t of builtin){assert.equal(t.appearance,'light');assert.equal(t.schema_version,'studyflow.theme/1');assert.equal(Object.keys(t.tokens).length,Object.keys(contract.TOKEN_PROPERTIES).length)}})
test('已移除主题偏好只回退选择，保留自定义主题并持久化迁移',()=>{
 for(const id of ['paper-warm','graphite-dark','sea-glass']){
  const custom={...clone(white),id:'user-theme',name:'自定义'}
  const snapshot={...fixture().api.snapshot(),selected_theme_id:id,custom_themes:[custom],revision:{clock:5000,source:'old-window'}}
  const f=fixture('new-window',JSON.stringify(snapshot))
  assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id);assert.ok(f.api.view().notice)
  assert.equal(f.api.view().themes.find(x=>x.theme.id===custom.id).source,'custom')
  const saved=JSON.parse(f.saved());assert.equal(saved.selected_theme_id,contract.DEFAULT_THEME.id);assert.equal(saved.custom_themes.length,1);assert.ok(saved.revision.clock>5000)
  assert.equal(f.api.receive(snapshot),false);assert.equal(fixture('reload',f.saved()).api.view().notice,'')
  assert.equal(f.api.select(custom.id).ok,true)
 }
})
test('已移除主题遇到只读存储仍保留自定义主题并允许会话内切换',()=>{
 const custom={...clone(white),id:'user-theme',name:'自定义'}
 const snapshot={...fixture().api.snapshot(),selected_theme_id:'paper-warm',custom_themes:[custom]}
 const f=fixture('read-only',JSON.stringify(snapshot),true)
 assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id);assert.equal(f.api.view().persistent,false)
 assert.equal(f.api.select(custom.id).ok,true);assert.equal(f.api.view().theme.id,custom.id)
})
test('旧窗口同步退役选择时保留自定义主题，重复消息不回声',()=>{
 const f=fixture(),custom={...clone(white),id:'user-theme',name:'自定义'}
 const snapshot={...f.api.snapshot(),selected_theme_id:'sea-glass',custom_themes:[custom],revision:{clock:5000,source:'old-window'}}
 assert.equal(f.api.receive(snapshot),true);assert.equal(f.api.view().theme.id,white.id)
 assert.equal(f.api.view().themes.filter(x=>x.source==='custom').length,1)
 assert.equal(f.api.receive(snapshot),false);assert.equal(f.sent.length,0)
})
test('用户主动导入同名旧主题不会被升级逻辑强制移除',()=>{
 const f=fixture(),custom={...clone(white),id:'paper-warm',name:'用户导入配置'}
 assert.equal(f.api.importTheme(JSON.stringify(custom)).ok,true)
 const next=fixture('reload',f.saved());assert.equal(next.api.view().theme.id,custom.id)
 assert.equal(next.api.view().themes.find(x=>x.theme.id===custom.id).source,'custom')
})
test('配置拒绝版本、字段、非法色值、可执行值和低对比文本',()=>{for(const change of [t=>t.schema_version='bad',t=>delete t.tokens['text.primary'],t=>t.tokens['text.primary']='url(https://invalid.test/a)',t=>t.script='alert(1)',t=>t.tokens['text.primary']=t.tokens['surface.panel'],t=>t.presentation.heading='javascript']){const t=clone(builtin[0]);change(t);assert.throws(()=>contract.parseTheme(t))}})
test('正常切换只更新呈现，持久化选择；同主题不重复写/广播',()=>{const f=fixture();assert.equal(f.api.select(sequence.id).ok,true);assert.equal(f.api.view().theme.id,sequence.id);const count=f.sent.length;assert.equal(f.api.select(sequence.id).ok,true);assert.equal(f.sent.length,count);const next=fixture('window-b',f.saved());assert.equal(next.api.view().theme.id,sequence.id)})
test('未知主题、损坏偏好和不可读存储不会白屏',()=>{for(const f of [fixture('a','{'),fixture('a',JSON.stringify({theme_id:'unknown'})),fixture('a',null,false,true)]){assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id);assert.equal(f.api.select('unknown').ok,false);assert.ok(f.api.view().notice)}})
test('偏好写失败仍会话可用，并传播完整快照',()=>{const f=fixture('a',null,true);assert.equal(f.api.select(sequence.id).ok,true);assert.equal(f.api.view().theme.id,sequence.id);assert.equal(f.api.view().persistent,false);assert.ok(f.api.view().notice);assert.equal(f.sent.at(-1).selected_theme_id,sequence.id)})
test('导入/导出受控JSON，保留固定标识和元数据',()=>{const f=fixture();const t=clone(white);t.id='custom-study';t.name='我的主题';assert.equal(f.api.importTheme(JSON.stringify(t)).ok,true);assert.equal(f.api.view().theme.id,'custom-study');assert.equal(JSON.parse(f.api.exportTheme()).id,'custom-study');assert.equal(f.api.view().themes.find(x=>x.theme.id==='custom-study').source,'custom');assert.equal(f.api.removeTheme('custom-study').ok,true);assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id)})
test('坏导入、超大JSON、内置ID冲突不覆盖当前主题',()=>{const f=fixture();f.api.select(sequence.id);for(const text of ['{',' '.repeat(contract.MAX_THEME_BYTES+1),JSON.stringify(builtin[0])]){assert.equal(f.api.importTheme(text).ok,false);assert.equal(f.api.view().theme.id,sequence.id)}})
test('主题数量有界，更新已有自定义ID不占第二名额',()=>{const f=fixture();for(let i=0;i<contract.MAX_CUSTOM_THEMES;i++){const t=clone(white);t.id='custom-'+i;assert.equal(f.api.importTheme(JSON.stringify(t)).ok,true)}const extra=clone(white);extra.id='overflow-theme';assert.equal(f.api.importTheme(JSON.stringify(extra)).ok,false);extra.id='custom-0';extra.name='新版';assert.equal(f.api.importTheme(JSON.stringify(extra)).ok,true);assert.equal(f.api.view().themes.filter(x=>x.source==='custom').length,contract.MAX_CUSTOM_THEMES)})
test('跨窗同步和重复/过期消息处理，不形成广播回声',()=>{const a=fixture('a'),b=fixture('b');a.api.select(sequence.id);const old=clone(a.sent.at(-1));assert.equal(b.api.receive(old),true);assert.equal(b.api.view().theme.id,sequence.id);assert.equal(b.sent.length,0);const n=b.applied.length;assert.equal(b.api.receive(old),false);assert.equal(b.applied.length,n);a.api.select(white.id);assert.equal(b.api.receive(a.sent.at(-1)),true);assert.equal(b.api.receive(old),false);assert.equal(b.api.view().theme.id,white.id)})
test('新窗接收导入主题及完整配置；同revision冲突按origin确定性合并',()=>{const a=fixture('a'),b=fixture('b');const t=clone(white);t.id='my-style';a.api.importTheme(JSON.stringify(t));assert.equal(b.api.receive(a.sent.at(-1)),true);assert.equal(b.api.view().theme.id,'my-style');const x=clone(b.api.snapshot());x.revision.source='z';x.selected_theme_id=sequence.id;assert.equal(b.api.receive(x),true);assert.equal(b.api.view().theme.id,sequence.id)})
test('恶意/损坏同步不能注入主题或破坏现有选择',()=>{const f=fixture();f.api.select(sequence.id);for(const raw of [null,{}, {...clone(f.api.snapshot()),revision:{clock:Infinity,source:'bad'}}, {...clone(f.api.snapshot()),custom_themes:[{tokens:{bad:'url(test)'}}]}]){assert.equal(f.api.receive(raw),false);assert.equal(f.api.view().theme.id,sequence.id)}})
test('输入/阅读/静音偏好不属于主题快照；切换不调用Engine或reload',()=>{const f=fixture();f.api.select(sequence.id);const snap=JSON.stringify(f.api.snapshot());for(const key of ['answer_text','study_session_id','reading-font','interaction-sound'])assert.ok(!snap.includes(key));const runtime=fs.readFileSync(path.join(src,'index.ts'),'utf8');assert.ok(!/engineCall|location\.reload|innerHTML/.test(runtime))})
test('所有正文、状态及按钮配对达到契约中的对比度',()=>{for(const t of builtin){for(const bg of ['surface.canvas','surface.panel','surface.raised','surface.input','surface.hover','surface.active'])for(const fg of ['text.primary','text.secondary','text.muted'])assert.ok(contract.contrastRatio(t.tokens[fg],t.tokens[bg])>=4.5,`${t.id}: ${fg}/${bg}`)}})
test('导入严格限制未知字段与URL式资源，解析失败保留原状态',()=>{const f=fixture();const original=JSON.stringify(f.api.snapshot());for(const change of [t=>t.remote_font='https://invalid.test/font',t=>t.tokens['extra']='red',t=>t.presentation.layout='<script>',t=>t.tokens['text.primary']='#fff',t=>t.name='<script>alert(1)</script>',t=>t.motion_profile='animation-script']){const t=clone(white);t.id='custom-invalid';change(t);assert.equal(f.api.importTheme(JSON.stringify(t)).ok,false);assert.equal(JSON.stringify(f.api.snapshot()),original)}})
test('控制器返回值隔离，外部调用不能通过修改快照污染色板',()=>{const f=fixture();const view=f.api.view(),snapshot=f.api.snapshot();view.theme.tokens['text.primary']='bad';snapshot.selected_theme_id='missing';assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id);assert.notEqual(f.api.view().theme.tokens['text.primary'],'bad')})
test('未知存储schema、重复内置ID及损坏自定义主题回退',()=>{const original=fixture().api.snapshot();for(const change of [s=>s.schema_version='legacy',s=>s.custom_themes=[clone(white)],s=>s.custom_themes=[{}],s=>s.revision.source='<script>']){const s=clone(original);change(s);const f=fixture('b',JSON.stringify(s));assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id);assert.ok(f.api.view().notice)}})
test('正文色彩都使用语义变量，不保留旧CSS字面调色板',()=>{const base=path.join(src,'../..');const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(path.join(dir,x.name)):path.join(dir,x.name));for(const file of walk(base).filter(f=>f.endsWith('.css')))assert.ok(!/#[0-9a-f]{3,8}\b|\brgba?\(/i.test(fs.readFileSync(file,'utf8')),file)})
test('主题入口不会挂载第二个应用，设置支持切换和JSON配置',()=>{const main=fs.readFileSync(path.join(src,'../../main.ts'),'utf8');assert.equal((main.match(/createApp\(/g)||[]).length,1);assert.ok(main.includes('initializeThemes()'));const settings=fs.readFileSync(path.join(src,'../../features/workspace/components/ThemeSettings.vue'),'utf8');for(const operation of ['selectTheme','importTheme','exportTheme','removeTheme','resetTheme'])assert.ok(settings.includes(operation));assert.ok(settings.includes('aria-pressed'))})

// ---------------- B01：展示包契约、旧配置兼容与受控范围 ----------------
const display=load('display.ts')
const validDisplay=()=>({layout:'page',navigation_width:150,reading_width:780,tools_width:420,reading_shell:'sheet',teaching_style:'paper',note_style:'margin',type_scale:1.05,heading_family:'editorial',body_family:'humanist',surface_treatment:'paper',radius:10,elevation:'subtle',outline:'hairline',assets:[]})

test('B01 旧v1主题无需新增字段即可解析，并推导出等价展示包',()=>{const raw=legacyTheme();assert.equal(raw.display,undefined);const theme=contract.parseTheme(raw);assert.equal(theme.display.layout,'rail');assert.equal(theme.display.heading_family,raw.presentation.heading);assert.equal(theme.display.teaching_style,raw.presentation.teaching);assert.ok(theme.display.assets.length===0)})
test('B01 展示包只在受控枚举与数值范围内取值',()=>{const theme=contract.parseTheme({...clone(legacyTheme()),display:validDisplay()});assert.equal(theme.display.layout,'page');assert.equal(theme.display.type_scale,1.05)
 for(const change of [d=>d.layout='<script>',d=>d.navigation_width=40,d=>d.navigation_width=9999,d=>d.reading_width='780',d=>d.type_scale=3,d=>d.type_scale=0.1,d=>d.radius=-1,d=>d.radius=99,d=>d.teaching_style='glass',d=>d.note_style='neon',d=>d.elevation='glass',d=>d.outline='glow',d=>d.heading_family='x',d=>d.body_family='x',d=>d.surface_treatment='blackglass',d=>d.reading_shell='web',d=>d.extra='x',d=>delete d.radius]){
  const raw=legacyTheme();const d=validDisplay();change(d);raw.display=d;assert.throws(()=>contract.parseTheme(raw))}})
test('B01 展示包素材只允许标识与回退，不含路径或网络引用',()=>{const base=legacyTheme()
 const good=validDisplay();good.assets=[{key:'edge-grain',role:'texture',aspect_ratio:'16:9',safe_area:0.1,fallback:'#efe7d8'}];assert.equal(contract.parseTheme({...clone(base),display:good}).display.assets[0].key,'edge-grain')
 for(const asset of [{key:'../escape',role:'texture',aspect_ratio:'16:9',safe_area:0.1,fallback:'#ffffff'},{key:'a',role:'texture',aspect_ratio:'16:9',safe_area:0.1,fallback:'url(https://x.test/a.png)'},{key:'a',role:'background',aspect_ratio:'0:2',safe_area:0.1,fallback:'#ffffff'},{key:'a',role:'video',aspect_ratio:'16:9',safe_area:0.1,fallback:'#ffffff'},{key:'a',role:'texture',aspect_ratio:'16:9',safe_area:2,fallback:'#ffffff'}]){const d=validDisplay();d.assets=[asset];assert.throws(()=>contract.parseTheme({...clone(base),display:d}))}})
test('B01 展示偏好与主题偏好分开保存，且不进入主题快照',()=>{const f=require('node:fs').readFileSync;const loader=f(path.join(src,'display-loader.ts'),'utf8');assert.ok(loader.includes("studyflow:theme-display:v1"));assert.ok(!/answer_text|study_session_id/.test(loader));const snap=JSON.stringify(fixture().api.snapshot());assert.ok(!snap.includes('image_intensity'));assert.ok(!snap.includes('type_scale'))})
test('B01 展示偏好非法值被拒绝，且不改变当前主题',()=>{const f=displayFixture();assert.equal(f.api.setDisplayPreferences({image_intensity:'full'}).ok,true);assert.equal(f.api.displaySnapshot().image_intensity,'full');for(const bad of [{image_intensity:'glass'},{typography:{scale:5,lineHeight:'auto'}},{typography:{scale:'auto',lineHeight:9}}])assert.equal(f.api.setDisplayPreferences(bad).ok,false);assert.equal(f.api.displaySnapshot().image_intensity,'full');assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id)})
test('B01 展示偏好跨窗按revision合并，过期消息不覆盖',()=>{const a=displayFixture('a'),b=displayFixture('b');a.api.setDisplayPreferences({image_intensity:'none'});const msg=clone(a.sentDisplay.at(-1));assert.equal(b.api.receiveDisplay(msg),true);assert.equal(b.api.displaySnapshot().image_intensity,'none');assert.equal(b.api.receiveDisplay(msg),false);const older=clone(msg);older.revision.clock=0;older.image_intensity='full';assert.equal(b.api.receiveDisplay(older),false);assert.equal(b.api.displaySnapshot().image_intensity,'none')})
test('B01 展示偏好损坏回退为默认，(不白屏)也不影响主题选择',()=>{const f=displayFixture('a','{');assert.equal(f.api.displaySnapshot().image_intensity,'full');assert.equal(f.api.displaySnapshot().typography.scale,'auto');assert.equal(f.api.view().theme.id,contract.DEFAULT_THEME.id)})

test('theme shell contract fixes navigation and scroll ownership for course and normal pages',()=>{
 const runtime=fs.readFileSync(path.join(src,'runtime.css'),'utf8')
 const shell=fs.readFileSync(path.join(src,'../../app/layout/AppShell.vue'),'utf8')
 assert.match(runtime,/theme-shell-contract[^}]+position:fixed!important/)
 assert.ok(runtime.includes('.desktop-shell.learning-shell:not(.focus-shell)>.sidebar'))
 assert.ok(runtime.includes('.workspace-shell:not(.focus-shell)>.sidebar'))
 assert.ok(runtime.includes('.workspace-shell:not(.focus-shell)>.main-content'))
 assert.ok(!/theme-shell-contract[^}]+position:sticky!important/.test(runtime))
 assert.match(runtime,/theme-shell-contract[^}]+grid-column:2!important/)
 assert.match(shell,/['\"]workspace-shell['\"]:\s*!props\.focus/)
})
