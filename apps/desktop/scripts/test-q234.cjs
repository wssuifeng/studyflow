const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const root=path.resolve(__dirname,'../src'),read=p=>fs.readFileSync(path.join(root,p),'utf8')
test('Q2 local answer references are lazy and use the tracked user-view endpoint',()=>{
 const source=read('features/learning/components/AnswerReference.vue')
 assert.ok(source.includes('studyApi.viewReference'));assert.ok(source.includes('if(open.value&&!data.value)'));assert.ok(source.includes('generation'))
 assert.ok(!source.includes('Math.random'));assert.ok(source.includes('这道题尚未配置答案解析'))
})
test('Q3 sections have stable scoped anchors and native disclosure with frozen preferences',()=>{
 const source=read('features/courses/components/TeachingSections.vue')
 for(const fragment of ['content-section-','props.lessonId','props.blockId','section-supplement','data-outline-level','saveDetailsPreference'])assert.ok(source.includes(fragment),fragment)
 const reader=read('features/courses/components/CourseReader.vue');assert.ok(reader.includes('source_section_id'));assert.ok(reader.includes('.teaching-section-title'))
})
test('Q4 course management uses shared plan groups and versioned existing mutations',()=>{
 const source=read('features/plans/components/PlanDetail.vue')
 for(const group of ['PENDING','COMPLETED','OTHER'])assert.ok(source.includes(group))
 assert.ok(source.includes('COURSE_POSITION'));assert.ok(source.includes('expected_version:data.value.plan.version'));assert.ok(source.includes('notebook.save()'))
 assert.ok(!source.includes('delete-course'));assert.ok(source.includes('保留全部答案'))
})

test('explicit outline navigation invalidates deferred theme/dock scroll restoration',()=>{
 const source=read('features/courses/components/CourseReader.vue')
 assert.ok(source.includes('readingRestoreGeneration++'))
 assert.ok(source.includes('generation!==readingRestoreGeneration'))
 assert.match(source,/explicitReadingNavigation=true\s+cancelReadingScrollRestore\(\)/)
 assert.ok(source.includes('!explicitReadingNavigation&&!restoringReadingScroll.value'))
})

// §7.2 计划与控制台信息密度：黑盒渲染实际 SFC（合成数据），断言用户可见输出而非实现细节。
const vm=require('node:vm'),ts=require('typescript'),vue=require('vue')
const {parse,compileScript}=require('@vue/compiler-sfc'),{renderToString}=require('@vue/server-renderer')
function compileSfc(file,extraVue){
 const {descriptor}=parse(read(file))
 const compiled=compileScript(descriptor,{id:'quality-'+path.basename(file),inlineTemplate:true})
 const code=ts.transpileModule(compiled.content,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText
 const mod={exports:{}}
 vm.runInNewContext(code,{module:mod,exports:mod.exports,require:id=>{
  if(id==='vue')return extraVue||vue
  if(id.endsWith('nextAction'))return {courseAction:()=>'继续学习'}
  if(id.endsWith('shared/ui'))return {navigate(){},statusLabel:s=>s}
  return require(id)
 }})
 return mod.exports.default
}
function syntheticCourse(i,plan='合成入门计划'){
 return {id:'course-'+i,title:'合成课程 '+i,sequence:i+1,total:9,knowledge_total:12,knowledge_completed:0,exercise_total:6,exercise_completed:0,progress_percent:0,plan_line:plan,plan_line_id:'plan-'+(i%2),study_status:'NOT_STARTED',learning_submitted:false,schedule:null}
}
async function renderToday(courses,searchValue='',counts){
 const search=vue.ref('')
 const TodayWorkspace=compileSfc('features/console/components/TodayWorkspace.vue',{...vue,ref:v=>v===''?search:vue.ref(v)})
 search.value=searchValue
 const data={protocol_version:'1',date:'2026-10-16',primary_task:null,current_course:courses[0]||null,courses,tasks:[],queue_counts:counts||{waiting_review:0,needs_revision:0,waiting_retest:0},next_action:''}
 return renderToString(vue.createSSRApp({render:()=>vue.h(TodayWorkspace,{data})}))
}
async function renderPlans(plans,queryValue=''){
 const query=vue.ref(''),showHistory=vue.ref(false)
 const PlanList=compileSfc('features/plans/components/PlanList.vue',{...vue,ref:v=>v===''?query:v===false?showHistory:vue.ref(v)})
 query.value=queryValue
 return renderToString(vue.createSSRApp({render:()=>vue.h(PlanList,{plans})}))
}
test('控制台搜索无匹配时区分“筛选无结果”与“没有计划”，就近给出清空动作',async()=>{
 const courses=Array.from({length:7},(_,i)=>syntheticCourse(i))
 const html=await renderToday(courses,'不存在的计划')
 assert.ok(html.includes('当前搜索没有匹配的计划'),'应显示搜索无结果短反馈')
 assert.ok(html.includes('清空搜索'),'应提供清空搜索动作')
 assert.ok(!html.includes('外部 Agent 可以通过 CLI'),'不得误报为没有计划')
})
test('控制台空数据空态以中性说明开场并保留打开动作',async()=>{
 const html=await renderToday([],'')
 assert.ok(html.includes('还没有学习计划'))
 assert.ok(html.includes('打开我的计划'))
 assert.ok(!html.includes('留一个位置给新的知识'))
 assert.ok(!html.includes('✦'))
})
test('控制台课程条目与反馈摘要是合法按钮内容：无标题/段落嵌套，标题与摘要改用类承载',async()=>{
 const courses=Array.from({length:7},(_,i)=>syntheticCourse(i))
 const html=await renderToday(courses,'',{waiting_review:2,needs_revision:1,waiting_retest:0})
 assert.ok(html.includes('class="inline-search"'))
 assert.ok(html.includes('class="course-title"'))
 assert.ok(html.includes('class="plan-course-meta"'))
 assert.ok(!html.includes('<h4'),'按钮内不得嵌套标题元素')
 const summary=html.match(/<button[^>]*console-feedback-summary[\s\S]*?<\/button>/)[0]
 assert.ok(!summary.includes('<p'),'反馈摘要按钮内不得嵌套段落')
 assert.ok(summary.includes('feedback-summary-meta'))
 assert.ok(summary.includes('等待批改 2'))
})
test('控制台移除渲染中被隐藏的英文 eyebrow 与重复的落款入口，保留计划详情与计数',()=>{
 const source=read('features/console/components/TodayWorkspace.vue')
 assert.ok(!source.includes('YOUR LEARNING SPACE'))
 assert.ok(!source.includes('查看完整学习路径'))
 assert.ok(source.includes('计划详情'))
 assert.ok(source.includes('门顺序课程'))
})
test('计划卡按钮只承载实际信息：无嵌套标题/段落，无重复点击动作的链接落款',async()=>{
 const plans=[{id:'plan-a',name:'合成计划甲',priority:3,status:'ACTIVE',version:1},{id:'plan-b',name:'合成计划乙',priority:1,status:'ACTIVE',version:1}]
 const html=await renderPlans(plans)
 const card=html.match(/<button[^>]*plan-card[\s\S]*?<\/button>/)[0]
 assert.ok(!card.includes('<h2'));assert.ok(!card.includes('<p'))
 assert.ok(card.includes('class="plan-card-title"'))
 assert.ok(card.includes('class="plan-card-meta"'))
 assert.ok(card.includes('优先级 3'))
 assert.ok(!card.includes('打开学习计划'))
 assert.ok(!card.includes('查看课程与学习进度'))
})
test('计划列表空态以中性说明开场，筛选无结果仍可一键清除',async()=>{
 const empty=await renderPlans([])
 assert.ok(empty.includes('还没有学习计划'))
 assert.ok(!empty.includes('从一个清晰的目标开始'))
 const filtered=await renderPlans([{id:'plan-a',name:'合成计划甲',priority:3,status:'ACTIVE',version:1}],'不存在')
 assert.ok(filtered.includes('当前筛选条件下没有计划'))
 assert.ok(filtered.includes('清除筛选'))
})
test('计划列表先说明后筛选，说明不含口号；两页筛选与列表同为 12px 节奏',()=>{
 const source=read('features/plans/components/PlanList.vue')
 const lead=source.indexOf('class="page-lead"'),filters=source.indexOf('class="plan-list-filters"'),grid=source.indexOf('class="plan-grid"')
 assert.ok(lead>-1&&filters>lead&&grid>filters,'顺序应为 page-lead → plan-list-filters → plan-grid')
 assert.ok(!source.includes('选一个方向，继续往前走'))
 const todayCss=read('features/console/styles/today.css')
 assert.match(todayCss,/\.inline-search\s*\{[^}]*margin-bottom:12px/)
})
test('计划详情移除英文装饰 eyebrow，课程条目标题层级随结构递降',()=>{
 const source=read('features/plans/components/PlanDetail.vue')
 assert.ok(!source.includes('LEARNING PATH'))
 assert.ok(!source.includes('<h3>{{course.title}}</h3>'))
 assert.ok(source.includes('<h4>{{course.title}}</h4>'))
 assert.ok(source.includes('<h3>{{group.title}}'))
})
test('计划卡密度收敛且样式选择器不再依赖卡内标题/段落元素',()=>{
 const css=read('features/plans/styles/plans.css')
 assert.match(css,/\.plan-card\{[^}]*padding:16px/)
 assert.match(css,/\.plan-card-top\{[^}]*margin-bottom:12px/)
 assert.match(css,/\.plan-icon\{[^}]*width:32px;height:32px/)
 assert.ok(!css.includes(':nth-child(2n)'),'装饰性换色应移除')
 assert.match(css,/\.plan-card \.plan-card-title\{[^}]*display:block/)
 assert.match(css,/\.plan-card \.plan-card-meta\{[^}]*display:block[^}]*margin:8px 0 12px/)
 assert.ok(!css.includes('.text-link'))
 const todayCss=read('features/console/styles/today.css')
 assert.ok(!todayCss.includes('.course-title-line h4'))
 assert.match(todayCss,/\.course-title-line \.course-title\s*\{[^}]*font-size:15px/)
})
