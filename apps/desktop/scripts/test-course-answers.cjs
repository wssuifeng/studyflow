/* State-only regression, no browser/installation access. node --test scripts/test-course-answers.cjs */
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm')
const ts=require('typescript'),vue=require('vue')
const source=fs.readFileSync(path.join(__dirname,'../src/features/learning/composables/useCourseAnswers.ts'),'utf8')
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
class EngineError extends Error {constructor(code){super(code);this.code=code}}
function fixture(seedStorage) {
  const state={answers:[{exercise_id:'e1',action:'FIRST',draft:null,submission:null},{exercise_id:'e2',action:'FIRST',draft:null,submission:null}]}
  const store=seedStorage||new Map(),cleanup=[],calls=[],errors=[];let hold=null,reject=null
  const clone=x=>JSON.parse(JSON.stringify(x))
  const api={courseAnswers:async()=>clone(state),saveCourseAnswers:async params=>{
    calls.push(clone(params));if(reject){const code=reject;reject=null;throw new EngineError(code)}
    if(hold){const pending=hold;hold=null;await pending}
    const subs=params.answers.map(entry=>{const row=state.answers.find(s=>s.exercise_id===entry.exercise_id)
      row.draft={id:'d-'+entry.exercise_id,version:(row.draft?.version||0)+1,answer_text:entry.answer_text,status:'DRAFT'};return row.draft})
    return {submissions:clone(subs)}
  },submitCourseAnswers:async params=>{
    calls.push(clone(params));params.answers.forEach(entry=>{const row=state.answers.find(s=>s.exercise_id===entry.exercise_id)
      row.submission={id:'s-'+entry.exercise_id,status:'WAITING_REVIEW',answer_text:entry.answer_text,reviews:[]};row.draft=null;row.action='LOCKED'})
    return {submissions:state.answers.map(r=>r.submission)}
  }}
  const mod={exports:{}}
  vm.runInNewContext(compiled,{exports:mod.exports,module:mod,console,setTimeout,clearTimeout,
    window:{addEventListener(){},removeEventListener(){}},
    localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
    require:name=>name==='vue'?{...vue,onBeforeUnmount:fn=>cleanup.push(fn)}:name.includes('shared/api')?{EngineError,studyApi:api,isTauri:()=>false}:name.includes('shared/ui')?{
      makeRequestKey:op=>op+':'+Math.random(),notify(){},reportError(cause){errors.push(cause)},storageKey:k=>'test:'+k,windowStorageKey:k=>'test:'+k}:require(name)})
  const course=vue.ref({course:{id:'c'},study:{id:'round-1'},lessons:[{id:'l',title:'合成知识点',exercises:[{id:'e1',title:'合成题1',prompt:'题面1',requirements:''},{id:'e2',title:'合成题2',prompt:'题面2',requirements:''}]}]})
  return {model:mod.exports.useCourseAnswers(course),store,state,calls,errors,hold(p){hold=p},reject(code){reject=code},dispose(){cleanup.forEach(f=>f())}}
}
test('空题可保留草稿，正式提交校验完整性',async()=>{
 const f=fixture();try{await f.model.load();assert.equal(f.model.missing.value.length,2)
 assert.equal(await f.model.write('save'),true);assert.equal(await f.model.write('submit'),false);assert.equal(f.calls.length,0)
 f.model.rows.value[0].answer='只答一题';assert.equal(await f.model.write('save'),true)
 assert.equal(f.state.answers[0].draft.answer_text,'只答一题');assert.equal(f.state.answers[1].draft,null)}finally{f.dispose()}
})
test('防抖自动保存，保存中继续输入不被旧结果覆盖',async()=>{
 const f=fixture();try{await f.model.load();let release;f.hold(new Promise(resolve=>release=resolve))
 f.model.rows.value[0].answer='旧内容';await pause(1000);assert.equal(f.calls.length,1)
 f.model.rows.value[0].answer='继续输入的新内容';release();await pause(50)
 assert.equal(f.model.rows.value[0].answer,'继续输入的新内容');assert.equal(f.model.dirty.value,true)
 assert.equal(await f.model.write('save'),true);assert.equal(f.state.answers[0].draft.answer_text,'继续输入的新内容')}finally{f.dispose()}
})
test('保存中清空输入，不能被旧响应填回',async()=>{
 const f=fixture();try{await f.model.load();let release;f.hold(new Promise(resolve=>release=resolve))
 f.model.rows.value[0].answer='稍后删除';const saving=f.model.write('save');await pause(5)
 f.model.rows.value[0].answer='';release();await saving
 assert.equal(f.model.rows.value[0].answer,'');assert.equal(f.model.dirty.value,true)
 await f.model.write('save');assert.equal(f.state.answers[0].draft.answer_text,'')}finally{f.dispose()}
})
test('断线后原请求重试，幂等键不变',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].answer='断线合成内容';f.reject('CONNECTION_FAILED')
 assert.equal(await f.model.write('save'),false);assert.equal(await f.model.write('save'),false)
 const key=f.calls[0].idempotency_key;assert.equal(await f.model.retry(),true)
 assert.equal(f.calls[1].idempotency_key,key);assert.equal(f.state.answers[0].draft.answer_text,'断线合成内容');assert.equal(f.model.pending.value,null)}finally{f.dispose()}
})
test('重开恢复未确认请求，不用旧工作区答案覆盖确认后的草稿',async()=>{
 const f=fixture();await f.model.load();f.model.rows.value[0].answer='关闭前输入';f.reject('CONNECTION_FAILED');await f.model.write('save');f.dispose()
 const recovered=fixture(f.store);try{await recovered.model.load();assert(recovered.model.pending.value);assert(recovered.model.recovery.value)
 assert.equal(await recovered.model.retry(),true);assert.equal(recovered.model.rows.value[0].answer,'关闭前输入')
 assert.equal(recovered.model.dirty.value,false);assert.equal(recovered.model.recovery.value,null)}finally{recovered.dispose()}
})
test('版本冲突保留本机答案，由用户确认恢复，不盲重试',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].answer='我的未保存版本';f.reject('VERSION_CONFLICT')
 assert.equal(await f.model.write('save'),false);assert.equal(f.model.pending.value,null);assert.equal(await f.model.retry(),true)
 assert.equal(f.model.recovery.value.e1,'我的未保存版本');f.model.restoreCache();assert.equal(f.model.rows.value[0].answer,'我的未保存版本')
 assert.equal(await f.model.write('save'),true)}finally{f.dispose()}
})
test('整课一次提交，多题转为只读等待批改',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value.forEach((r,i)=>r.answer='合成答案'+i)
 assert.equal(await f.model.write('submit'),true);assert.equal(f.calls.length,1);assert.equal(f.calls[0].answers.length,2)
 assert.equal(f.calls[0].study_session_id,'round-1');assert.equal(f.model.editable.value.length,0);assert.equal(f.model.dirty.value,false)}finally{f.dispose()}
})

for (const code of ['DATABASE_CONSTRAINT_ERROR','DATABASE_LOCKED','DATABASE_DISK_FULL','WORKSPACE_DISK_FULL','DATABASE_READ_ONLY','WORKSPACE_READ_ONLY']) {
 test(code+' 保留原请求和输入，修复后可幂等重试',async()=>{
  const f=fixture();try {await f.model.load();f.model.rows.value[0].answer='故障时保留的合成答案';f.reject(code)
  assert.equal(await f.model.write('save'),false);assert.ok(f.model.pending.value)
  const key=f.calls[0].idempotency_key;assert.equal(await f.model.retry(),true)
  assert.equal(f.calls[1].idempotency_key,key);assert.equal(f.model.rows.value[0].answer,'故障时保留的合成答案')
  }finally{f.dispose()}
 })
}

test('不保存离开后，迟到的答案请求失败不在新页面弹错误',async()=>{
 const f=fixture();try{await f.model.load();let failFlight;f.hold(new Promise((_,reject)=>failFlight=reject))
 f.model.rows.value[0].answer='明确选择不保存';const saving=f.model.write('save');await pause(5)
 f.model.suspendAutosave();failFlight(new EngineError('CONNECTION_FAILED'));assert.equal(await saving,false)
 assert.equal(f.errors.length,0);assert.ok(f.model.pending.value);assert.equal(await f.model.retry(),false)
 assert.equal(f.calls.length,1);assert.equal(f.model.rows.value[0].answer,'明确选择不保存')}finally{f.dispose()}
})

for(const code of ['ENGINE_TIMEOUT','ENGINE_UNCONFIRMED','ENGINE_BUSY','INVALID_RESPONSE']){
 test(code+'保持原幂等请求，不改键自动重发',async()=>{
  const f=fixture();try{await f.model.load();f.model.rows.value[0].answer='结果未确认的答案';f.reject(code);assert.equal(await f.model.write('save'),false);assert.ok(f.model.pending.value);const key=f.calls[0].idempotency_key;assert.equal(await f.model.retry(),true);assert.equal(f.calls[1].idempotency_key,key)}finally{f.dispose()}
 })
}
test('缓存配额不足不阻止工作区写入且释放忙态',async()=>{
 const store=new Map();store.set=()=>{throw new Error('synthetic quota')};const f=fixture(store)
 try{await f.model.load();f.model.rows.value[0].answer='缓存不可用仍应写入工作区';assert.equal(await f.model.write('save'),true);assert.equal(f.model.busy.value,'');assert.equal(f.model.cacheUnavailable.value,true);assert.equal(f.calls.length,1)}finally{f.dispose()}
})
