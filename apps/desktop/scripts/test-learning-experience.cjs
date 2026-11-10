const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),ts=require('typescript')
const root=path.join(__dirname,'../src')
function load(file){const m={exports:{}};vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(root,file),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:m,exports:m.exports,require,JSON,Math,Object,Array,Number,Set,Map,Error,String});return m.exports}
const disclosure=load('features/courses/detailsDisclosure.ts'),connection=load('features/workspace/agentConnection.ts'),restart=load('features/courses/studyRestartRequest.ts')
const info={workspace:'C:\\合成工作区\\local.studyflow.desktop',workspace_exists:true,cli_path:'D:\\安装 目录\\binaries\\studyflow.exe',cli_argv:['D:\\安装 目录\\binaries\\studyflow.exe'],source_cli:false,cli_available:true,skill_path:'D:\\安装 目录\\binaries\\studyflow-agent\\SKILL.md',skill_kind:'installed',skill_available:true,agent_ready:true,agent_workspace_entry_path:'D:\\资料\\StudyFlow-Agent-Workspace\\AGENTS.md',agent_workspace_entry_status:'found'}
function storage(){const map=new Map;return {getItem:k=>map.get(k)||null,setItem:(k,v)=>map.set(k,v),removeItem:k=>map.delete(k)}}
test('folded detail defaults closed and unavailable preference storage cannot break reading',()=>{assert.equal(disclosure.readDetailsPreference(null,'test'),false);assert.equal(disclosure.readDetailsPreference({getItem(){throw Error('denied')}},'test'),false);assert.doesNotThrow(()=>disclosure.saveDetailsPreference({setItem(){throw Error('denied')}},'test',true))})
test('disclosure preference is scoped to workspace frozen hash lesson and stable block',()=>{const s=storage(),key=disclosure.detailsPreferenceKey('workspace:hash-a','lesson','block');disclosure.saveDetailsPreference(s,key,true);assert.equal(disclosure.readDetailsPreference(s,key),true);assert.equal(disclosure.readDetailsPreference(s,disclosure.detailsPreferenceKey('workspace:hash-b','lesson','block')),false);assert.notEqual(key,disclosure.detailsPreferenceKey('other:hash-a','lesson','block'))})
test('outline target opens parent disclosure before navigation; block source opens its controlled disclosure',()=>{const details={tagName:'DETAILS',open:false,parentElement:null},node={tagName:'H3',parentElement:details};disclosure.revealTeachingTarget(node);assert.equal(details.open,true);const own={open:false};disclosure.revealTeachingTarget({tagName:'SECTION',parentElement:null,querySelectorAll:()=>[own]},true);assert.equal(own.open,true)})
test('Agent copy requires verified loaded resources and rejects workspace mismatches',()=>{assert.equal(connection.agentConnection(null).ready,false);assert.equal(connection.agentConnection({...info,skill_available:false}).ready,false);assert.equal(connection.agentConnection({...info,cli_argv:['relative.exe']}).ready,false);assert.equal(connection.agentConnection(info,'C:\\Other').ready,false);assert.equal(connection.agentConnection(info,info.workspace.toUpperCase()).ready,true)})
test('copied entry contains dynamic paths and only the session bootstrap flow',()=>{const data=connection.agentConnection(info);assert.equal(data.ready,true);for(const value of [info.cli_path,info.workspace,info.skill_path,info.agent_workspace_entry_path,'version、capabilities、doctor','列出当前可做事项'])assert.ok(data.text.includes(value),value);assert.ok(!data.text.includes('undefined'));assert.ok(!data.text.includes('~'));assert.match(data.text,/Skill（安装内）/);assert.match(data.text,/入口状态为 found/);assert.doesNotMatch(data.text,/course-authoring|requirements/);assert.ok(data.text.split('\n').length<18)})
test('source entry advertises explicit argv rather than an invented exe',()=>{const source={...info,source_cli:true,cli_path:null,cli_argv:['C:\\Python\\python.exe','-m','studyflow'],skill_kind:'repository'};const data=connection.agentConnection(source);assert.equal(data.ready,true);assert.match(data.text,/源码 CLI/);assert.match(data.text,/Skill（仓库）/);assert.ok(data.text.includes(JSON.stringify(source.cli_argv)))})
test('pending restart keeps original version hash and key across reload; workspace is isolated',()=>{const s=storage(),p={study_session_id:'round',expected_version:2,expected_content_hash:'a'.repeat(64),idempotency_key:'restart-key'};restart.storeRestartRequest(s,'key','workspace',p);const first=restart.readRestartRequest(s,'key','workspace');assert.equal(first.idempotency_key,p.idempotency_key);assert.equal(first.expected_version,2);assert.equal(restart.readRestartRequest(s,'key','other'),null);restart.storeRestartRequest(s,'key','workspace',null);assert.equal(restart.readRestartRequest(s,'key','workspace'),null)})
test('unknown write failures cannot clear pending restart or silently allocate another key',()=>{for(const code of ['ENGINE_TIMEOUT','CONNECTION_FAILED','INVALID_RESPONSE','DATABASE_ERROR'])assert.equal(restart.definitiveRestartFailure(code),false);for(const code of ['VERSION_CONFLICT','COURSE_CONTENT_CONFLICT','STUDY_RESTART_BLOCKED'])assert.equal(restart.definitiveRestartFailure(code),true)})

test('verified UNC paths are preserved rather than silently replaced',()=>{const unc={...info,workspace:'\\\\server\\data\\studyflow',cli_argv:['\\\\server\\apps\\studyflow.exe'],cli_path:'\\\\server\\apps\\studyflow.exe',skill_path:'\\\\server\\apps\\studyflow-agent\\SKILL.md'};assert.equal(connection.agentConnection(unc).ready,true);assert.ok(connection.agentConnection(unc).text.includes(unc.workspace))})

test('restart cache failure is explicit and cannot prevent safe exiting',()=>{assert.equal(restart.storeRestartRequest(null,'key','workspace',{}),false);assert.equal(restart.storeRestartRequest({setItem(){throw Error('quota')}},'key','workspace',{}),false)})

test('teaching headings are relative to the component, preserving text ids and author ordering',()=>{const {normalizeTeachingHeadings}=load('features/courses/teachingTypography.ts');assert.equal(normalizeTeachingHeadings('<h2 id="a">Definition</h2><h3>Proof</h3><p>text</p>'),'<h5 id="a">Definition</h5><h6>Proof</h6><p>text</p>');assert.equal(normalizeTeachingHeadings('<h1>Step detail</h1>',6),'<h6>Step detail</h6>');assert.equal(normalizeTeachingHeadings('<p>&lt;h1&gt; is text</p>'),'<p>&lt;h1&gt; is text</p>')})

test('component heading ids are lesson scoped when English overview renders multiple groups',()=>{const source=fs.readFileSync(path.join(root,'features/courses/components/TeachingContent.vue'),'utf8');assert.ok(source.includes("'block-title-'+lessonId+'-'+block.id"));assert.ok(source.includes("'content-block-'+lessonId+'-'+block.id"))})

// 阅读域统一骨架：保存/退出/工具归属语义保持不变。
test('统一阅读骨架保持保存退出链与工具归属，动作区唯一',()=>{
 const reader=fs.readFileSync(path.join(root,'features/courses/components/CourseReader.vue'),'utf8')
 const actions=fs.readFileSync(path.join(root,'features/courses/components/StudyActions.vue'),'utf8')
 for(const marker of ['useSafeStudyExit','LeaveStudyDialog','StudyRecovery','retrySaving','exportUnsaved','savePosition(true)','study-action-bar'])assert.ok(reader.includes(marker),marker)
 // 底部是唯一稳定动作区；侧栏不再接收第二份动作/恢复条（同一role=alert只出现一处）
 assert.ok(!reader.includes('#actions'))
 assert.ok(!reader.includes('#recovery'))
 assert.equal((reader.match(/<StudyActions/g)||[]).length,1)
 assert.equal((reader.match(/<StudyRecovery/g)||[]).length,1)
 // 动作区四按钮disabled语义一致（含末位“继续学习”）
 assert.equal((actions.match(/:disabled="blocked"/g)||[]).length,4)
})

// LC-05: copy routes to a single authoring reference source, not duplicated pedagogy.
test('Agent entry gives explicit found, missing, and invalid collaboration-root actions',()=>{
 const text=connection.agentConnection(info).text
 assert.ok(text.includes('读取上述 AGENTS.md'))
 const missing=connection.agentConnection({...info,agent_workspace_entry_path:null,agent_workspace_entry_status:'missing'}).text
 assert.match(missing,/入口状态为 missing/);assert.match(missing,/先按 Skill 初始化独立协作区/);assert.match(missing,/不得在数据根、安装目录或源码仓库初始化/)
 const invalid=connection.agentConnection({...info,agent_workspace_entry_path:null,agent_workspace_entry_status:'invalid'})
 assert.equal(invalid.ready,true);assert.match(invalid.text,/入口状态为 invalid/);assert.match(invalid.text,/停止初始化和后续业务操作/)
 assert.equal(connection.agentConnection({...info,agent_workspace_entry_path:null,agent_workspace_entry_status:'found'}).ready,false)
 assert.equal(connection.agentConnection({...info,skill_available:false}).ready,false)
})

// Authoring asset regressions share this approved test entry.
{
const root=path.resolve(__dirname,'../../..'),skill=path.join(root,'skills/studyflow-agent')
const read=name=>fs.readFileSync(path.join(skill,name),'utf8')
test('authoring entry is versioned and task references are all resolvable',()=>{
  const entry=read('SKILL.md');assert.match(entry,/version: "2\.9\.13"/);assert.match(entry,/Course-authoring task routing/)
  for(const file of ['entry-workflow.md','workspace-structure.md','course-authoring.md','authoring-presentation.md','authoring-prompts.md','authoring-workflows.md','english-course-authoring.md','authoring-review-examples.md']){assert.ok(entry.includes(file));assert.ok(fs.statSync(path.join(skill,'references',file)).isFile())}
 for(const file of fs.readdirSync(path.join(skill,'references')).filter(x=>x.endsWith('.md'))){const text=read('references/'+file);for(const link of text.matchAll(/\[[^\]]*\]\(([^)]+)\)/g)){if(/^https?:|^#/.test(link[1]))continue;assert.ok(fs.existsSync(path.resolve(skill,'references',link[1].split('#')[0])),file+': '+link[1])}}
})
function assertCurrentAuthoringRoute(text){
 assert.equal((text.match(/^#{2,3} Course-authoring task routing$/gm)||[]).length,1,'one canonical authoring route')
 assert.ok(!text.includes('Course teaching design (before authoring content)'),'no legacy duplicate route')
 assert.doesNotMatch(text,/English software support is currently a design proposal|The proposed first English release/)
 assert.match(text,/repository Core now has English capabilities/)
 assert.match(text,/Discover `content\.course_package_schemas`/)
 assert.match(text,/Public\/installed Skill copies do not automatically receive repository edits/)
}
test('long-term authoring routes to bounded material helpers without full upfront splitting',()=>{
 const entry=read('SKILL.md');assert.ok(entry.includes('learning-workspace-governance.md'));assert.ok(entry.includes('vocabulary-selection.md'));assert.ok(entry.includes('scripts/authoring_workspace.py'))
 const governance=read('references/learning-workspace-governance.md');assert.ok(governance.includes('没有可靠正向证据'));assert.ok(governance.includes('不为获得证据擅自open'));assert.ok(governance.includes('不自动判断'))
 const words=read('references/vocabulary-selection.md');assert.ok(words.includes('不要先全库AI分类'));assert.ok(words.includes('learning_evidence=false'));assert.ok(words.includes('--exclude-selections-dir'));assert.ok(words.includes('不能认证回执来自CLI'))
 assert.ok(fs.existsSync(path.join(skill,'scripts','authoring_workspace.py')))
})
test('authoring routing has one current capability-based source without legacy proposal wording',()=>{
 assertCurrentAuthoringRoute(read('SKILL.md'))
})
test('authoring consistency guard rejects stale statements duplicate routes and missing discovery',()=>{
 const text=read('SKILL.md');assertCurrentAuthoringRoute(text)
 for(const broken of [text+'\nEnglish software support is currently a design proposal',text+'\n## Course-authoring task routing',text.replace('Discover `content.course_package_schemas`','Skip discovery')])assert.throws(()=>assertCurrentAuthoringRoute(broken))
})
test('external author reference requires version and frozen-question binding before grading',()=>{
 const text=read('references/course-authoring.md')
 for(const marker of ['材料revision或草稿版本','内容hash与题面指纹','参考版本/来源','不能伪造课程字段','按其实际题面匹配参考','缺匹配依据暂停相关批改'])assert.ok(text.includes(marker),marker)
  const contract=read('references/course-experience-v5.md');for(const marker of ['content_revision/frozen_content_revision/question_hash/reference_hash','同题ID改题拒绝','旧轮次读原版'])assert.ok(contract.includes(marker),marker)
 assert.ok(read('references/authoring-prompts.md').includes('旧历史证据不改写'))
})

test('teaching, validation and rendering remain separate; authorized maintenance uses the W2 reset contract',()=>{
 const text=read('references/course-authoring.md')
  for(const marker of ['结构校验、内容审核、真实渲染是三道独立关','作者按授权来源逐条复核事实/教学语义','quality-check读取','requirements只写','作者材料','参考必须实际解答问题','CLI validate','真实呈现未验','明确课程授权','失败、无变化及幂等重放不能反复重置','不将purge当常规修法'])assert.ok(text.includes(marker),marker)
 assert.ok(!text.includes('错误查询增量仍待实现'))
})
test('presentation rules do not promise unsupported subsection or arbitrary HTML folding',()=>{
 const text=read('references/authoring-presentation.md')
 for(const marker of ['/3的独立details','/5的concept','必要定义、关系、推导条件、作答数据与理解桥梁保持常显','不写任意HTML、CSS、JS或假字段','选择实际支持的载体','关系/顺序缺陷回到骨架调整'])assert.ok(text.includes(marker),marker)
 assert.ok(!text.includes('每个知识点必须使用六'))
})
test('English authoring keeps source inventory, grammar progression and actual learning distinct',()=>{
 const text=read('references/english-course-authoring.md')
 for(const marker of ['原料、蓝图和具体课程','来源提取覆盖、表间覆盖和学习掌握分别计数','不规定每课词数','不把作者L1—L4叫官方等级或已测能力','词典优先','objective_ids','local_exact','SUPPLEMENT'])assert.ok(text.includes(marker),marker)
 assert.ok(!text.includes('错误数据查询未实现'))
})
test('replay and concurrency safeguards are conditional on host, not universal tool calls or permission',()=>{
 const text=read('references/authoring-workflows.md')
 for(const marker of ['不因为Skill','稳定任务ID','动态结果','原负载/原键','UTF-8 BOM','固定最佳值'])assert.ok(text.includes(marker),marker)
})

test('English independent expressions and textual role review cannot be replaced by coverage or blank carriers',()=>{
 const text=read('references/english-course-authoring.md')
 for(const marker of ['## 4.2. 独立表达与成分划分复核','角色→实际词段','原形','不能只加挖空句框来保留不合理独立切片','全部目标、中文提示、教学例句和完整答案变体','导出每框圈住的文本核对全部项'])assert.ok(text.includes(marker),marker)
 assert.ok(read('references/authoring-presentation.md').includes('english_structure_review'))
 assert.ok(!text.includes('应给`Each process ___.`等确切语境'))
})

}

test('authorized reset persists its original state fingerprint across reload',()=>{const s=storage(),p={study_session_id:'round',expected_version:2,expected_content_hash:'a'.repeat(64),expected_state_hash:'b'.repeat(64),reset_current_state:true,idempotency_key:'reset-key'};restart.storeRestartRequest(s,'reset','workspace',p);assert.deepEqual({...restart.readRestartRequest(s,'reset','workspace')},p);s.setItem('bad',JSON.stringify({workspaceKey:'workspace',params:{...p,expected_state_hash:undefined}}));assert.equal(restart.readRestartRequest(s,'bad','workspace'),null)})
