const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const ts=require('typescript'),vue=require('vue')
const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/features/english/training/useEnglishTraining.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
function fixture(){
 const calls=[],store=new Map();let serial=0,fail=false,failCheck=false
 const study={course:{id:'c',title:'Synthetic',plan_line_id:'p'},study_session_id:'s',revision:1,position:0,state_version:0,completed:false,items:['e1','e2'].map(exercise_id=>({exercise_id,token_count:3,answer_text:'',answer_version:0,status:'NOT_STARTED',matched:false,differences:[],assisted:false}))}
 async function engineCall(method,params){calls.push({method,params:JSON.parse(JSON.stringify(params||{}))});if(method==='course.english.get')return JSON.parse(JSON.stringify(study));if(method==='course.english.save'){if(fail){fail=false;throw new Error('save failed')}const row=study.items.find(i=>i.exercise_id===params.exercise_id);row.answer_version++;row.answer_text=params.answer_text;return {answer_version:row.answer_version,state_version:++study.state_version}}if(method==='course.english.check'){if(failCheck){failCheck=false;throw new Error('check reply lost')}return {matched:true,differences:[],state_version:++study.state_version}};if(method==='course.english.answer')return {target:'I like tea.',tokens:['I','like','tea'],phonetic:'',gloss:'',explanation:''};if(method==='course.english.navigate')return {state_version:++study.state_version};throw Error(method)}
 const context={exports:{},require:id=>id==='vue'?{...vue,onBeforeUnmount:()=>{}}:id.endsWith('/api')?{engineCall}:{makeRequestKey:op=>op+':'+(++serial),windowStorageKey:k=>'synthetic:'+k},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},setTimeout,clearTimeout,console,Blob,URL,document:{createElement:()=>({click(){}})}}
 vm.runInNewContext(code,context)
 return {api:context.exports.useEnglishTraining('s'),calls,failNext:()=>fail=true,failNextCheck:()=>failCheck=true}
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
function audioFixture(){
 const requests=[],players=[];let active=0,maxActive=0
 function engineCall(method,params){let resolve;active++;maxActive=Math.max(active,maxActive);const promise=new Promise(r=>resolve=r);requests.push({method,params,resolve:value=>{active--;resolve(value)}});return promise}
 class Audio{constructor(src){this.src=src;this.oncanplay=null;this.onerror=null;this.paused=false;players.push(this)}load(){}pause(){this.paused=true}play(){return Promise.resolve()}}
 const context={exports:{},require:id=>id==='vue'?vue:{engineCall},localStorage:{getItem:()=>null,setItem(){}},Audio,URL,setTimeout,clearTimeout,console};vm.runInNewContext(audioCode,context)
 return {api:context.exports,requests,players,maxActive:()=>maxActive}
}
const dictionary={target:'I like tea',pronunciation_url:'https://dict.youdao.com/dictvoice?audio=I+like+tea',requested_accent:'en-US',accent_verified:false,phonetic:'',definitions:[],course_gloss:'',from_cache:false}
test('speech keeps only the newest queued request with one metadata lookup in flight',async()=>{const f=audioFixture();f.api.speechMuted.value=true;const first=f.api.playDictionary('s','e1'),second=f.api.playDictionary('s','e2'),third=f.api.playDictionary('s','e3');assert.equal(f.requests.length,1);f.requests[0].resolve(dictionary);await new Promise(r=>setImmediate(r));assert.equal(f.requests.length,2);assert.equal(f.requests[1].params.exercise_id,'e3');f.requests[1].resolve(dictionary);const results=await Promise.all([first,second,third]);assert.equal(results[0],null);assert.equal(results[1],null);assert.equal(results[2].target,'I like tea');assert.equal(f.maxActive(),1)})
test('stopping unloaded speech settles the old play without late error or unwanted audio',async()=>{const f=audioFixture();const play=f.api.playDictionary('s','e');f.requests[0].resolve(dictionary);await new Promise(r=>setImmediate(r));assert.equal(f.players.length,1);f.api.stopSpeech();assert.equal(await play,null);assert.ok(f.players[0].paused);assert.equal(f.players[0].onerror,null)})


test('English work surface exposes only notes as a drawer and keeps directory in a native dialog',()=>{
 const source=fs.readFileSync(path.join(__dirname,'../src/features/english/training/EnglishTrainingPage.vue'),'utf8')
 assert.ok(source.includes("ref<'notes'|null>"));assert.ok(source.includes('<dialog'));assert.ok(source.includes('showModal()'))
 assert.ok(source.includes('english-inline-teaching'));assert.ok(!source.includes("drawer==='lesson'"));assert.ok(!source.includes("drawer==='directory'"))
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
