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
async function renderPlans(plans,queryValue=''){
 const query=vue.ref(''),showHistory=vue.ref(false)
 const PlanList=compileSfc('features/plans/components/PlanList.vue',{...vue,ref:v=>v===''?query:v===false?showHistory:vue.ref(v)})
 query.value=queryValue
 return renderToString(vue.createSSRApp({render:()=>vue.h(PlanList,{plans})}))
}
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
test('计划列表先说明后筛选，说明不含口号',()=>{
 const source=read('features/plans/components/PlanList.vue')
 const lead=source.indexOf('class="page-lead"'),filters=source.indexOf('class="plan-list-filters"'),grid=source.indexOf('class="plan-grid"')
 assert.ok(lead>-1&&filters>lead&&grid>filters,'顺序应为 page-lead → plan-list-filters → plan-grid')
 assert.ok(!source.includes('选一个方向，继续往前走'))
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
})
