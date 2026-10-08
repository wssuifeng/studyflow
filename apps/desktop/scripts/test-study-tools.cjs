/* Personal notes and knowledge states: state-only tests, never access installed data. */
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm')
const ts=require('typescript'), vue=require('vue')
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms))
function compile(file) {return ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src',file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText}
class EngineError extends Error {constructor(code){super(code);this.code=code}}
function fixture(storage) {
 const store=storage||new Map(),cleanup=[],calls=[],errors=[],state={notes:[]},receipts=new Map();let reject=null,hold=null
 const clone=x=>JSON.parse(JSON.stringify(x))
 const api={studyNotes:async()=>clone(state),saveStudyNote:async params=>{
  calls.push(clone(params));if(reject){const code=reject;reject=null;throw new EngineError(code)}
  if(hold){const next=hold;hold=null;await next}
  if(receipts.has(params.idempotency_key)) return clone(receipts.get(params.idempotency_key))
  const old=state.notes.find(row=>row.lesson_id===params.lesson_id)
  if((old?.version||0)!==params.expected_version) throw new EngineError('VERSION_CONFLICT')
  const note={id:'n-'+params.lesson_id,lesson_id:params.lesson_id,text:params.text,version:(old?.version||0)+1,updated_at:'2026-10-02T12:00:00'}
  state.notes=state.notes.filter(row=>row.lesson_id!==params.lesson_id).concat(note)
  const result={study_session_id:'study',note};receipts.set(params.idempotency_key,clone(result));return clone(result)
 }}
 const mod={exports:{}}
 vm.runInNewContext(compile('features/learning/composables/useStudyNotes.ts'),{exports:mod.exports,module:mod,setTimeout,clearTimeout,console,
  window:{addEventListener(){},removeEventListener(){}},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},
  require:name=>name==='vue'?{...vue,onBeforeUnmount:fn=>cleanup.push(fn)}:name.includes('shared/api')?{EngineError,studyApi:api,isTauri:()=>false}:name.includes('shared/ui')?{makeRequestKey:op=>op+':'+Math.random(),reportError(cause){errors.push(cause)},windowStorageKey:k=>'test:'+k}:require(name)})
 const course=vue.ref({study:{id:'study'},lessons:[{id:'l1'},{id:'l2'}]})
 return {model:mod.exports.useStudyNotes(course),store,state,calls,errors,reject(code){reject=code},hold(value){hold=value},dispose(){cleanup.forEach(fn=>fn())}}
}
test('按知识点保存笔记，清空也是合法更新',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].text='第一点的笔记';f.model.rows.value[1].text='第二点的笔记'
 assert.equal(await f.model.save(),true);assert.equal(f.calls.length,2);assert.equal(f.state.notes.length,2)
 f.model.rows.value[0].text='';assert.equal(await f.model.save(),true)
 assert.equal(f.state.notes.find(n=>n.lesson_id==='l1').text,'');assert.equal(f.model.dirty.value,false)}finally{f.dispose()}
})
test('笔记保存期间的新输入不会被旧响应覆盖',async()=>{
 const f=fixture();try{await f.model.load();let release;f.hold(new Promise(resolve=>release=resolve))
 f.model.rows.value[0].text='旧笔记';const saving=f.model.save();await pause(5)
 f.model.rows.value[0].text='继续写的新笔记';release();assert.equal(await saving,true)
 assert.equal(f.model.rows.value[0].text,'继续写的新笔记');assert.equal(f.state.notes[0].text,'继续写的新笔记');assert.equal(f.calls.length,2)}finally{f.dispose()}
})
test('笔记断线后同一幂等键重试',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].text='不要丢失';f.reject('DATABASE_LOCKED')
 assert.equal(await f.model.save(),false);assert.ok(f.model.pending.value)
 const key=f.calls[0].idempotency_key;assert.equal(await f.model.retry(),true)
 assert.equal(f.calls[1].idempotency_key,key);assert.equal(f.model.rows.value[0].text,'不要丢失')}finally{f.dispose()}
})
test('关闭后恢复未确认笔记请求',async()=>{
 const f=fixture();await f.model.load();f.model.rows.value[0].text='关闭前的笔记';f.reject('CONNECTION_FAILED');await f.model.save();f.dispose()
 const resumed=fixture(f.store);try{await resumed.model.load();assert.ok(resumed.model.pending.value)
 assert.equal(await resumed.model.retry(),true);assert.equal(resumed.model.rows.value[0].text,'关闭前的笔记');assert.equal(resumed.model.recovery.value,null)}finally{resumed.dispose()}
})
test('多窗口笔记冲突保留双方内容，明确恢复后才能再保存',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].text='本窗口的内容'
 f.state.notes=[{id:'n-l1',lesson_id:'l1',text:'另一个窗口的内容',version:1}]
 assert.equal(await f.model.save(),false);assert.equal(f.model.pending.value,null);assert.equal(f.state.notes[0].text,'另一个窗口的内容')
 assert.equal(await f.model.retry(),true);assert.equal(f.model.recovery.value.l1,'本窗口的内容')
 f.model.restoreCache();assert.equal(f.model.rows.value[0].text,'本窗口的内容');assert.equal(await f.model.save(),true)}finally{f.dispose()}
})
test('知识点生命周期包含文字，反馈状态优先于当前高亮',()=>{
 const mod={exports:{}};vm.runInNewContext(compile('features/courses/knowledgePointState.ts'),{exports:mod.exports,module:mod})
 const state=mod.exports.knowledgePointState, lesson={id:'l',progress:{status:'NOT_STARTED'}}, row={lessonId:'l',answer:'',action:'FIRST',draft:null,submission:null}
 assert.equal(state(lesson,[],false).label,'未学习');assert.equal(state(lesson,[],true).kind,'learning')
 assert.equal(state({...lesson,progress:{status:'COMPLETED'}},[]).label,'已读完')
 assert.equal(state(lesson,[{...row,answer:'草稿'}]).kind,'draft')
 assert.equal(state(lesson,[{...row,action:'LOCKED',submission:{status:'WAITING_REVIEW'}}],true).kind,'review')
 assert.equal(state(lesson,[{...row,action:'REVISION'}],true).label,'待修正')
 assert.equal(state(lesson,[{...row,action:'RETEST'}],true).label,'待复测')
 assert.equal(state(lesson,[{...row,action:'LOCKED',submission:{status:'PASSED'}}]).label,'已通过')
})

function exitFixture(config={}) {
 let guard,flushes=0,suspends=0;const cleanup=[],mod={exports:{}}
 vm.runInNewContext(compile('features/learning/composables/useSafeStudyExit.ts'),{exports:mod.exports,module:mod,setTimeout,clearTimeout,
  require:name=>name==='vue'?{...vue,onBeforeUnmount:fn=>cleanup.push(fn)}:{reportError(){},setNavigationGuard(fn){guard=fn;return ()=>{guard=null}}}})
 const model=mod.exports.useSafeStudyExit({busy:()=>false,hasProblem:()=>true,retry:async()=>{},flush:async()=>{flushes++;return false},timeoutMs:20,
  ...config,suspend:()=>{suspends++}})
 return {model,guard:path=>guard(path),get flushes(){return flushes},get suspends(){return suspends},dispose(){cleanup.forEach(fn=>fn())}}
}
test('保存失败立即提供退出确认，不再强制重新保存',async()=>{
 const f=exitFixture();try{const closing=f.guard('close-window');assert.equal(f.model.dialog.value.path,'close-window');assert.equal(f.flushes,0)
 f.model.finish(true,true);assert.equal(await closing,true);assert.equal(f.suspends,1);assert.equal(f.model.leaving.value,true)
 assert.equal(await f.guard('close-window'),true);assert.equal(f.flushes,0)}finally{f.dispose()}
})
test('取消离开保留学习页面，重试成功后才正常退出',async()=>{
 let success=false;const f=exitFixture({retry:async()=>{success=true},flush:async()=>success})
 try{let result=f.guard('/plans');f.model.finish(false);assert.equal(await result,false);assert.equal(f.suspends,0)
 result=f.guard('close-window');await f.model.retry();assert.equal(await result,true);assert.equal(f.model.dialog.value,null);assert.equal(f.suspends,0)}finally{f.dispose()}
})
test('重试挂起期间仍可不保存退出，不等待数据库请求结束',async()=>{
 let release;const f=exitFixture({retry:()=>new Promise(resolve=>release=resolve)})
 try{const result=f.guard('close-window');const retry=f.model.retry();assert.equal(f.model.dialog.value.retrying,true)
 f.model.finish(true,true);assert.equal(await result,true);release();await retry;assert.equal(f.flushes,0)}finally{f.dispose()}
})
test('保存超时或抛异常也不会把用户锁在窗口中',async()=>{
 for(const flush of [()=>new Promise(()=>{}),async()=>{throw Error('synthetic failure')}]) {
 const f=exitFixture({hasProblem:()=>false,flush});try{const result=f.guard('close-window');await pause(40)
 assert.ok(f.model.dialog.value);f.model.finish(true,true);assert.equal(await result,true)}finally{f.dispose()}
 }
})
test('明确不保存离开会停止笔记自动保存与后续重试',async()=>{
 const f=fixture();try{await f.model.load();f.model.rows.value[0].text='仅本机保留，不再写数据库';f.model.suspendAutosave()
 assert.equal(await f.model.save(),false);assert.equal(await f.model.retry(),false);await pause(1000);assert.equal(f.calls.length,0)
 assert.ok(f.store.size)}finally{f.dispose()}
})

test('不保存离开后，迟到的笔记请求失败不在新页面弹错误',async()=>{
 const f=fixture();try{await f.model.load();let failFlight;f.hold(new Promise((_,reject)=>failFlight=reject))
 f.model.rows.value[0].text='离开时保留恢复缓存';const saving=f.model.save();await pause(5)
 f.model.suspendAutosave();failFlight(new EngineError('CONNECTION_FAILED'));assert.equal(await saving,false)
 assert.equal(f.errors.length,0);assert.ok(f.model.pending.value);assert.equal(await f.model.retry(),false)
 assert.equal(f.calls.length,1);assert.equal(f.model.rows.value[0].text,'离开时保留恢复缓存')}finally{f.dispose()}
})

test('普通操作提示自动收起，错误提示持续保留且不会被旧计时器清除',()=>{const mod={exports:{}};let callback=null;vm.runInNewContext(compile('shared/ui/feedback.ts'),{module:mod,exports:mod.exports,setTimeout:fn=>{callback=fn;return 1},clearTimeout:()=>{callback=null},require:n=>n==='vue'?vue:{EngineError}});const api=mod.exports;api.notify('已置顶','info');assert.equal(typeof callback,'function');callback();assert.equal(api.notice.message,'');api.notify('已保存');api.notify('数据库错误','error');assert.equal(callback,null);assert.equal(api.notice.message,'数据库错误')})
