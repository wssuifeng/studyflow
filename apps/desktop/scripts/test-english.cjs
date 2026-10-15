const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const ts=require('typescript'),vue=require('vue')
const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/english/training/useEnglishTraining.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function fixture(initial={}){
 const calls=[],store=new Map();let serial=0,fail=false,failCheck=false,saveGate=null
 const study={course:{id:'c',title:'Synthetic',plan_line_id:'p'},study_session_id:'s',revision:1,position:0,state_version:0,completed:false,items:['e1','e2'].map(exercise_id=>({exercise_id,token_count:3,answer_text:'',answer_version:0,status:'NOT_STARTED',matched:false,differences:[],assisted:false}))}
 Object.assign(study,initial)
 async function engineCall(method,params){calls.push({method,params:JSON.parse(JSON.stringify(params||{}))});if(method==='course.english.get')return JSON.parse(JSON.stringify(study));if(method==='course.english.save'){if(saveGate){const gate=saveGate;saveGate=null;await gate.promise}if(fail){fail=false;throw new Error('save failed')}const row=study.items.find(i=>i.exercise_id===params.exercise_id);row.answer_version++;row.answer_text=params.answer_text;return {answer_version:row.answer_version,state_version:++study.state_version}}if(method==='course.english.check'){const row=study.items.find(i=>i.exercise_id===params.exercise_id);row.matched=true;row.skipped=false;if(failCheck){failCheck=false;throw new Error('check reply lost')}return {matched:true,differences:[],state_version:++study.state_version}};if(method==='course.english.reveal')return {target:'I like tea.',tokens:['I','like','tea'],phonetic:'',gloss:'喜欢茶',explanation:'',state_version:++study.state_version};if(method==='course.english.answer')return {target:'I like tea.',tokens:['I','like','tea'],phonetic:'',gloss:'',explanation:''};if(method==='course.english.navigate'){study.position=params.position;return {state_version:++study.state_version}};if(method==='course.english.submit')return {completed:true,state_version:++study.state_version};throw Error(method)}
 const context={exports:{},require:id=>id==='vue'?{...vue,onBeforeUnmount:()=>{}}:id.endsWith('/api')?{engineCall}:{makeRequestKey:op=>op+':'+(++serial),windowStorageKey:k=>'synthetic:'+k},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},setTimeout,clearTimeout,console,Blob,URL,document:{createElement:()=>({click(){}})}}
 vm.runInNewContext(code,context)
 return {api:context.exports.useEnglishTraining('s'),calls,failNext:()=>fail=true,failNextCheck:()=>failCheck=true,delayNextSave:()=>{let release;const promise=new Promise(r=>release=r);saveGate={promise};return release}}
}
test('saved baseline is reactive: checking and navigation do not invalidate a valid answer with duplicate saves',async()=>{const f=fixture();await f.api.load();f.api.tokens.value=['I','like','tea'];assert.equal(f.api.dirty.value,true);await f.api.save();assert.equal(f.api.dirty.value,false);await f.api.check();await f.api.move(1);assert.equal(f.calls.filter(x=>x.method==='course.english.save').length,1)})
test('failed saving keeps input and reuses the exact idempotency request',async()=>{const f=fixture();await f.api.load();f.api.tokens.value=['I','lik','tea'];f.failNext();assert.equal(await f.api.save(),false);const pending=JSON.stringify(f.api.pending.value);assert.equal(f.api.tokens.value[1],'lik');assert.equal(await f.api.retryPending(),true);const writes=f.calls.filter(x=>x.method==='course.english.save');assert.deepEqual(writes[0].params,writes[1].params);assert.ok(pending.includes('english-save'));assert.equal(f.api.dirty.value,false)})
test('navigation waits for the current draft instead of dropping skipped input',async()=>{const f=fixture();await f.api.load();f.api.tokens.value=['I','like',''];await f.api.move(1);const write=f.calls.findIndex(x=>x.method==='course.english.save'),move=f.calls.findIndex(x=>x.method==='course.english.navigate');assert.ok(write>=0&&move>write);assert.equal(f.api.position.value,1)})

test('double checking shares one in-flight action instead of issuing two attempts', async()=>{const f=fixture();await f.api.load();f.api.tokens.value=['I','like','tea'];await Promise.all([f.api.check(),f.api.check()]);assert.equal(f.calls.filter(x=>x.method==='course.english.check').length,1)})
test('a lost check reply retains its key and never creates a fresh attempt on retry', async()=>{const f=fixture();await f.api.load();f.api.tokens.value=['I','like','tea'];f.failNextCheck();assert.equal(await f.api.check(),null);assert.equal(f.api.pending.value.method,'course.english.check');await f.api.check();const attempts=f.calls.filter(x=>x.method==='course.english.check');assert.equal(attempts.length,2);assert.deepEqual(attempts[0].params,attempts[1].params);assert.equal(f.api.item.value.matched,true)})

const retestCode=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/english/training/useEnglishRetest.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function retestFixture(){
 const calls=[],store=new Map();let fail=false,serial=0
 const task={task_id:'t',title:'Synthetic',prompt:'Tea',token_count:3,status:'READY',answer_text:'',answer_version:0,result:null}
 async function engineCall(method,params){calls.push({method,params:JSON.parse(JSON.stringify(params||{}))});if(method==='course.english.retest-get')return {...task};if(fail){fail=false;throw Error('save failed')}if(method==='course.english.retest-save'){task.answer_version++;task.answer_text=params.answer_text;task.status='IN_PROGRESS';return {answer_version:task.answer_version,status:task.status}}if(method==='course.english.retest-check'){task.result={matched:true,status:'PASSED',differences:[],answer_version:++task.answer_version};return task.result}throw Error(method)}
 const context={exports:{},require:id=>id==='vue'?{...vue,onBeforeUnmount:()=>{}}:id.endsWith('/api')?{engineCall}:{makeRequestKey:op=>op+':'+(++serial),windowStorageKey:k=>'synthetic:'+k},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},setTimeout,clearTimeout,console,Blob,URL,document:{createElement:()=>({click(){}})}}
 vm.runInNewContext(retestCode,context)
 return {api:context.exports.useEnglishRetest('t'),calls,failNext:()=>fail=true,store}
}
test('retest draft saving keeps input, retries original key, then confirms at the returned CAS version',async()=>{const f=retestFixture();await f.api.load();f.api.tokens.value=['I','like','tea'];f.failNext();assert.equal(await f.api.save(),false);assert.equal(f.api.tokens.value[1],'like');assert.equal(await f.api.retryPending(),true);const saves=f.calls.filter(x=>x.method==='course.english.retest-save');assert.deepEqual(saves[0].params,saves[1].params);assert.equal(f.api.dirty.value,false);await Promise.all([f.api.check(),f.api.check()]);const checks=f.calls.filter(x=>x.method==='course.english.retest-check');assert.equal(checks.length,1);assert.equal(checks[0].params.expected_version,1);assert.equal(f.api.result.value.matched,true)})
test('retest suspend stops all later saving and leaves a best-effort recovery cache',async()=>{const f=retestFixture();await f.api.load();f.api.tokens.value=['I','like',''];f.api.suspend();assert.equal(await f.api.save(),false);assert.equal(f.calls.filter(x=>x.method==='course.english.retest-save').length,0);assert.ok([...f.store.values()][0].includes('I like'))})

const audioCode=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/shared/audio/dictionary.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function audioFixture(options={}){
 const requests=[],players=[],utterances=[];let active=0,maxActive=0,cancels=0
 function engineCall(method,params){let resolve;active++;maxActive=Math.max(active,maxActive);const promise=new Promise(r=>resolve=r);requests.push({method,params,resolve:value=>{active--;resolve(value)}});return promise}
 class Audio{constructor(src){this.src=src;this.oncanplay=null;this.onerror=null;this.paused=false;players.push(this)}load(){}pause(){this.paused=true}play(){return Promise.resolve()}}
 const context={exports:{},require:id=>id==='vue'?vue:{engineCall},localStorage:{getItem:()=>null,setItem(){}},Audio,URL,setTimeout,clearTimeout,console};if(options.system){context.SpeechSynthesisUtterance=class{constructor(text){this.text=text}};context.speechSynthesis={getVoices:()=>[{lang:'en-US',name:'Local English'}],speak:u=>{utterances.push(u);queueMicrotask(()=>u.onstart?.())},cancel:()=>cancels++,addEventListener(){},removeEventListener(){}}}vm.runInNewContext(audioCode,context)
 return {api:context.exports,requests,players,utterances,cancels:()=>cancels,maxActive:()=>maxActive}
}
const dictionary={target:'I like tea',pronunciation_url:'https://dict.youdao.com/dictvoice?audio=I+like+tea',requested_accent:'en-US',accent_verified:false,phonetic:'',definitions:[],course_gloss:'',from_cache:false}
test('speech keeps only the newest queued request with one metadata lookup in flight',async()=>{const f=audioFixture();f.api.speechMuted.value=true;const first=f.api.playDictionary('s','e1'),second=f.api.playDictionary('s','e2'),third=f.api.playDictionary('s','e3');assert.equal(f.requests.length,1);f.requests[0].resolve(dictionary);await new Promise(r=>setImmediate(r));assert.equal(f.requests.length,2);assert.equal(f.requests[1].params.exercise_id,'e3');f.requests[1].resolve(dictionary);const results=await Promise.all([first,second,third]);assert.equal(results[0],null);assert.equal(results[1],null);assert.equal(results[2].target,'I like tea');assert.equal(f.maxActive(),1)})
test('stopping unloaded speech settles the old play without late error or unwanted audio',async()=>{const f=audioFixture();const play=f.api.playDictionary('s','e');f.requests[0].resolve(dictionary);await new Promise(r=>setImmediate(r));assert.equal(f.players.length,1);f.api.stopSpeech();assert.equal(await play,null);assert.ok(f.players[0].paused);assert.equal(f.players[0].onerror,null)})


test('English work surface exposes only notes as a drawer and keeps directory in a native dialog',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/training/EnglishTrainingPage.vue'),'utf8')
 assert.ok(source.includes("ref<'notes'|null>"));assert.ok(source.includes('<dialog'));assert.ok(source.includes('showModal()'))
 assert.ok(source.includes('SentenceBreakdown'));assert.ok(!source.includes("drawer==='lesson'"));assert.ok(!source.includes("drawer==='directory'"))
 assert.ok(source.includes('stageLabels[item.progression.stage]'))
})
test('supplement courses use an independent grouping and keep source/transfer results visible',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/remediation/SupplementCourses.vue'),'utf8')
 assert.ok(source.includes('course.remediation.list'));assert.ok(source.includes('course.remediation.get'))
 assert.ok(source.includes('UNASSISTED_PASS'));assert.ok(source.includes('原题复测'))
 const plan=fs.readFileSync(path.join(__dirname,'../src/features/plans/components/PlanDetail.vue'),'utf8');assert.ok(plan.includes("view==='supplement'"))
;const supplement=fs.readFileSync(path.join(__dirname,'../src/features/english/remediation/SupplementCourses.vue'),'utf8');assert.match(supplement,/function closeDetail\(\)\{detailGeneration\+\+;detail\.value=null\}/);assert.match(supplement,/@click="closeDetail"/)})
test('English notebook locks the parent before native child loading and retains lock for an unready child',async()=>{
 const script=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/english/training/useEnglishNotesWindow.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const detached=vue.ref(false),events=[],context=vue.computed(()=>({courseId:'c',studyId:'s',planId:'p',planTitle:'Synthetic'}))
 const dock={listToolWindows:async()=>[{tool:'notes',context:context.value}],openToolWindow:async()=>{assert.equal(detached.value,true);events.push('open');return false},prepareTools:async()=>({ok:true,requestId:'test'}),releaseTools:async()=>{},addDetachedNote:async()=>true,toolsEvent:{closed:'closed',docking:'docking'}}
 const sandbox={exports:{},require:id=>id==='vue'?{...vue,onMounted:()=>{},onBeforeUnmount:()=>{}}:id==='@tauri-apps/api/core'?{invoke:async()=>{}}:id==='@tauri-apps/api/event'?{listen:async()=>()=>{},emitTo:async()=>{}}:id.endsWith('/api')?{isTauri:()=>true}:id.endsWith('/ui')?{notify:()=>{},reportError:()=>{}}:dock,console}
 vm.runInNewContext(script,sandbox);const api=sandbox.exports.useEnglishNotesWindow(context,detached,{save:async()=>true,load:async()=>true})
 await Promise.all([api.detach(),api.detach()]);assert.equal(events.length,1);assert.equal(detached.value,true);assert.match(api.notice.value,/尚未就绪/)
})


test('navigation joins the in-flight autosave and saves newer input before moving',async()=>{
 const f=fixture();await f.api.load();f.api.tokens.value=['I','like','tea'];const release=f.delayNextSave();const first=f.api.save();await new Promise(r=>setImmediate(r));
 assert.equal(f.api.busy.value,true);f.api.tokens.value=['I','love','tea'];f.api.edited();const move=f.api.move(1);await new Promise(r=>setImmediate(r));assert.equal(f.api.position.value,0);
 release();assert.equal(await first,true);assert.equal(await move,true);assert.equal(f.api.position.value,1);
 const saves=f.calls.filter(x=>x.method==='course.english.save');assert.deepEqual(saves.map(x=>x.params.answer_text),['I like tea','I love tea']);assert.equal(saves[1].params.expected_version,1);
})

test('word hints keep the input phase and user answer while recording assistance',async()=>{
 const f=fixture();await f.api.load();f.api.tokens.value=['I','lik',''];await f.api.reveal('hint');assert.equal(f.api.phase.value,'input');assert.equal(f.api.hintMode.value,'word');assert.equal(f.api.tokens.value[1],'lik');assert.equal(f.api.item.value.assisted,true);assert.equal(f.api.reference.value.target,'I like tea.');
 f.api.tokens.value=['I','like',''];f.api.edited();assert.equal(f.api.reference.value.target,'I like tea.');f.api.hideHint();assert.equal(f.api.hintMode.value,null);
})


function compileModule(relative,extras={}) {
 const output=ts.transpileModule(fs.readFileSync(path.join(__dirname,relative),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const context={exports:{},require:id=>id==='vue'?vue:{},console,...extras};vm.runInNewContext(output,context);return context.exports
}
test('training shortcut keys are predictable and ignore IME, repeats and unrelated chords',()=>{
 const {englishShortcut}=compileModule('../src/features/english/training/shortcuts.ts')
 const base={key:"'",code:'Quote',ctrlKey:true,metaKey:false,altKey:false,shiftKey:false,isComposing:false,repeat:false}
 assert.equal(englishShortcut(base),'sentence-audio');assert.equal(englishShortcut({...base,key:';',code:'Semicolon'}),'explanation');assert.equal(englishShortcut({...base,key:'.',code:'Period'}),'skip');assert.equal(englishShortcut({...base,key:',',code:'Comma'}),'previous')
 for(const prop of ['isComposing','repeat','altKey'])assert.equal(englishShortcut({...base,[prop]:true}),null)
 assert.equal(englishShortcut({...base,shiftKey:true}),'word-audio');assert.equal(englishShortcut({...base,ctrlKey:false}),null)
})
test('typing audio is throttled, respects its volume and never sounds for modifier shortcuts or IME',()=>{
 let now=0,starts=0,lastGain=0
 const sound=compileModule('../src/shared/audio/keyboard.ts',{localStorage:{getItem:()=>null,setItem(){}},document:{visibilityState:'visible'},performance:{now:()=>now},AudioContext:class{sampleRate=48000;state='running';createBuffer(_,length){return {getChannelData:()=>new Float32Array(length)}};createBufferSource(){return {connect(){},disconnect(){},start(){starts++}}};createGain(){const gain={value:0};return {gain,connect(){lastGain=gain.value},disconnect(){}}}}})
 const event={key:'f',altKey:false,ctrlKey:false,metaKey:false,isComposing:false};sound.playKeyboardSound(event);assert.equal(starts,1);assert.equal(lastGain,.38)
 now=20;sound.playKeyboardSound(event);assert.equal(starts,1);now=70;sound.playKeyboardSound(event);assert.equal(starts,2)
 now=140;sound.playKeyboardSound({...event,ctrlKey:true});sound.playKeyboardSound({...event,isComposing:true});assert.equal(starts,2)
 sound.keyboardEnabled.value=false;sound.playKeyboardSound(event);assert.equal(starts,2)
})
test('autosave does not disable typing, and sentence assistance does not remove the input editor',()=>{
 const page=fs.readFileSync(path.join(__dirname,'../src/features/english/training/EnglishTrainingPage.vue'),'utf8')
 assert.ok(page.includes(':disabled="training.inputLocked.value||locked"'));assert.ok(!page.includes(':disabled="busy||locked"'));assert.ok(page.includes('analysisOpen&&reference'));assert.ok(page.includes('@keydown="keydown"'))
})


test('editing during a save schedules the latest draft even without navigation',async()=>{
 const f=fixture();await f.api.load();f.api.tokens.value=['I','like','tea'];const release=f.delayNextSave();const first=f.api.save();await new Promise(r=>setImmediate(r));f.api.tokens.value=['I','love','tea'];f.api.edited();release();await first;await new Promise(r=>setTimeout(r,900));
 assert.equal(f.api.dirty.value,false);assert.equal(f.calls.filter(x=>x.method==='course.english.save').at(-1).params.answer_text,'I love tea');assert.equal(f.api.pending.value,null)
})

test('Enter from a repaired earlier word checks once all required input is present',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/training/shortcuts.ts'),'utf8'),context={exports:{}}
 vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,context)
 assert.equal(context.exports.inputAdvance('Enter',1,['I','like','the','food']),'check')
 assert.equal(context.exports.inputAdvance(' ',1,['I','like','the','food']),2)
 assert.equal(context.exports.inputAdvance('Enter',0,['I','','the','food']),1)
 assert.equal(context.exports.inputAdvance('Enter',4,['He',"doesn't",'have','a','plan',''],5),'check')
})
test('whole-course completion navigates the first missing item instead of opening a save error',async()=>{
 const f=fixture();await f.api.load();await f.api.move(1);f.api.tokens.value=['I','like','tea'];await f.api.check();await f.api.submit()
 assert.equal(f.api.position.value,0);assert.match(f.api.navigationNotice.value,/第 1 项/)
 assert.equal(f.calls.filter(x=>x.method==='course.english.submit').length,0);assert.equal(f.api.failed.value,'')
 f.api.tokens.value=['I','like','tea'];await f.api.check();await f.api.move(1);await f.api.submit();assert.equal(f.api.phase.value,'result')
})

test('failed dictionary sentence falls back to one local English utterance and cancels on leave',async()=>{
 const f=audioFixture({system:true});const play=f.api.playDictionary('s','e')
 f.requests[0].resolve(dictionary);await new Promise(r=>setImmediate(r));f.players[0].onerror();await new Promise(r=>setImmediate(r));f.players[1].onerror()
 const result=await play;assert.equal(result.playback_provider,'system');assert.equal(f.utterances.length,1);assert.equal(f.utterances[0].text,'I like tea')
 f.api.stopSpeech();assert.equal(f.cancels(),1)
})
test('training analysis and shortcuts are conditional and contain no Agent review route',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/training/EnglishTrainingPage.vue'),'utf8')
 assert.ok(source.includes("error_count||0)>=2"));assert.ok(source.includes("analysisOpen&&reference&&phase!=='answer'"));assert.ok(source.includes('english-shortcuts'))
 assert.ok(!source.includes('交给Agent审核'));assert.ok(!source.includes('提交本项审核'));assert.ok(!source.includes('<AnswerReference'))
})


test('one unavailable dictionary accent retries the same full sentence in the other accent without changing preference',async()=>{
 const f=audioFixture();const play=f.api.playDictionary('s','e').catch(error=>({failure:error.message}));f.requests[0].resolve(dictionary)
 await new Promise(r=>setImmediate(r));f.players[0].onerror();await new Promise(r=>setImmediate(r))
 assert.equal(f.players.length,2);assert.equal(new URL(f.players[1].src).searchParams.get('type'),'1')
 f.players[1].oncanplay();const result=await play
 assert.equal(result.target,'I like tea');assert.equal(result.playback_accent,'en-GB');assert.match(result.notice,/口音/)
 assert.equal(f.api.speechAccent.value,'en-US');assert.equal(f.requests.length,1)
})


test('leaving while alternate dictionary voice loads cancels it and never speaks the old sentence',async()=>{
 const f=audioFixture({system:true});const play=f.api.playDictionary('s','e');f.requests[0].resolve(dictionary)
 await new Promise(r=>setImmediate(r));f.players[0].onerror();await new Promise(r=>setImmediate(r));f.api.stopSpeech()
 assert.equal(await play,null);assert.ok(f.players[1].paused);assert.equal(f.utterances.length,0)
})


test('both themes share a bounded training focus viewport rather than reader padding and a second viewport',()=>{
 const css=fs.readFileSync(path.join(__dirname,'../src/features/english/training/english.css'),'utf8')
 assert.ok(css.includes('.app-shell.focus-shell:has(.english-learning){height:100dvh;min-height:0;overflow:hidden}'))
 assert.ok(css.includes('.app-shell.focus-shell.desktop-shell:has(.english-learning){height:calc(100dvh - 44px)}'))
 assert.ok(css.includes('>main.main-content{height:100%;min-height:0;max-width:none;margin:0;padding:0;overflow:hidden}'))
 assert.ok(css.includes('.app-shell.focus-shell .english-learning{height:100%;min-height:0}'))
})


test('legacy 74-item round completes with its last answer already queued, without overwriting or fabricating a pass',async()=>{
 const items=Array.from({length:74},(_,i)=>({exercise_id:'legacy-'+i,token_count:3,answer_text:'I like tea',answer_version:2,status:'DRAFT',matched:true,differences:[],assisted:false,skipped:false,evaluation_mode:'local_exact'}))
 Object.assign(items[73],{status:'WAITING_REVIEW',matched:false,evaluation_mode:'agent',answer_version:8})
 const f=fixture({items,position:73,state_version:742});await f.api.load();await f.api.submit()
 assert.equal(f.api.phase.value,'result','finish must not navigate back to queued item 74')
 assert.equal(f.api.item.value.status,'WAITING_REVIEW');assert.equal(f.api.item.value.matched,false)
 assert.equal(f.api.item.value.answer_text,'I like tea');assert.equal(f.api.item.value.answer_version,8)
 assert.equal(f.calls.filter(x=>x.method==='course.english.submit').length,1)
 assert.equal(f.calls.filter(x=>['course.english.navigate','course.english.save','course.english.check','course.english.request-review'].includes(x.method)).length,0)
 const versions=f.calls.find(x=>x.method==='course.english.submit').params.expected_versions;assert.equal(Object.keys(versions).length,74);assert.equal(versions['legacy-73'],8)
 assert.equal(f.api.navigationNotice.value,'');assert.equal(f.api.failed.value,'')
})


test('legacy queued answers stay visible as pending, not a local pass, and remain navigable without another save',()=>{
 const page=fs.readFileSync(path.join(__dirname,'../src/features/english/training/EnglishTrainingPage.vue'),'utf8')
 assert.ok(page.includes("status==='WAITING_REVIEW'"));assert.ok(page.includes('待审核不计为检查通过'))
 assert.ok(page.includes('原审核状态未改变，不代表全部通过'))
 assert.ok(page.includes("if(phase.value==='answer'||locked.value)void move(position.value+1)"))
 const banner=fs.readFileSync(path.join(__dirname,'../src/shared/components/StatusBanner.vue'),'utf8')
 assert.ok(banner.includes("notice.tone === 'success' ? '✓'"));assert.ok(banner.includes("notice.tone === 'error' ? '!' : 'i'"))
})


function overviewFixture(values={}){
 const page=fs.readFileSync(path.join(__dirname,'../src/features/english/course/EnglishCourseOverview.vue'),'utf8')
 const script=page.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1]
 const calls=[],visits=[],data={course:{id:'c',can_start_new_round:true,source_changed:false,...values},lessons:[]}
 const source=ts.transpileModule(script+'\nexports.start=start;', {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const context={exports:{},defineProps:()=>({data}),require:id=>id==='vue'?vue:id.endsWith('/api')?{engineCall:async(method,params)=>{calls.push({method,params});return {study:{id:'opened'}}}}:id.endsWith('/ui')?{navigate:async url=>visits.push(url),makeRequestKey:()=> 'synthetic-open',reportError:error=>{throw error},notify(){}}:{},console}
 vm.runInNewContext(source,context);return {start:context.exports.start,calls,visits,page}
}
test('English overview distinguishes explicit revised-material start, same-version review and frozen resume',async()=>{
 const updated=overviewFixture({source_changed:true});await updated.start(true);assert.equal(updated.calls[0].params.new_version,true);assert.equal(updated.calls[0].params.review_round,false)
 const resume=overviewFixture({source_changed:true});await resume.start();assert.equal(resume.calls[0].params.new_version,false);assert.equal(resume.calls[0].params.review_round,false)
 const review=overviewFixture();await review.start(true);assert.equal(review.calls[0].params.review_round,true);assert.equal(review.calls[0].params.new_version,false)
 const blocked=overviewFixture({can_start_new_round:false});await blocked.start(true);assert.equal(blocked.calls.length,0);await blocked.start();assert.equal(blocked.calls.length,1)
 assert.ok(updated.page.includes('学习修订后的课程'));assert.ok(updated.page.includes('旧记录待审核'));assert.ok(updated.page.includes('new_round_blocker'))
})

// Compile and render the actual SFC, not a duplicate of its fallback logic.
async function renderBreakdown(overrides={}){
 const {parse,compileScript}=require('@vue/compiler-sfc')
 const {renderToString}=require('@vue/server-renderer')
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/training/SentenceBreakdown.vue'),'utf8')
 const {descriptor}=parse(source)
 const compiled=compileScript(descriptor,{id:'breakdown-test',inlineTemplate:true})
 const js=ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const module={exports:{}},context={module,exports:module.exports,require:id=>id==='vue'?vue:require(id)}
 vm.runInNewContext(js,context)
 const reference={target:'This program',tokens:['This','program'],phonetic:'',gloss:'这个程序',explanation:'完整词组说明。',sentence_parts:[],...overrides}
 return renderToString(vue.createSSRApp({render:()=>vue.h(module.exports.default,{reference})}))
}
test('unannotated fragment renders its real meaning with accessible word audio, without inventing grammar',async()=>{
 const html=await renderBreakdown()
 assert.match(html,/class="breakdown-fallback"/)
 assert.match(html,/class="fallback-meaning"[^>]*>这个程序</)
 assert.match(html,/aria-label="朗读单词 This"/)
 assert.match(html,/aria-label="朗读单词 program"/)
 assert.ok(!html.includes('part-role'),'missing roles must not be inferred')
 assert.match(html,/完整词组说明。/)
})
test('fallback uses supplied pronunciation only and omits empty auxiliary rows',async()=>{
 const word=await renderBreakdown({target:'program',tokens:['program'],phonetic:'/ˈprəʊɡræm/',gloss:'程序',explanation:''})
 assert.match(word,/class="fallback-phonetic"[^>]*>\/ˈprəʊɡræm\/<\/span>/)
 const empty=await renderBreakdown({phonetic:'  ',gloss:'  ',explanation:''})
 assert.ok(!empty.includes('fallback-meaning'));assert.ok(!empty.includes('fallback-phonetic'))
})
test('annotated chunks retain author-provided grouping, word definitions and parts of speech',async()=>{
 const html=await renderBreakdown({sentence_parts:[{role:'subject',start:0,end:2,words:[{gloss:'这个',pos:'限定词'},{gloss:'程序',pos:'名词'}]}]})
 assert.match(html,/class="sentence-part role-subject"/);assert.match(html,/主语/)
 assert.match(html,/>限定词<\/em>/);assert.match(html,/>程序<\/span>/)
 assert.ok(!html.includes('breakdown-fallback'))
})
test('fallback explanations remain escaped text rather than arbitrary course HTML',async()=>{
 const html=await renderBreakdown({explanation:'<img src=x onerror=alert(1)>',gloss:'<b>程序</b>'})
 assert.ok(!html.includes('<img'));assert.ok(!html.includes('<b>程序</b>'))
 assert.match(html,/&lt;img/);assert.match(html,/&lt;b&gt;程序/)
})
