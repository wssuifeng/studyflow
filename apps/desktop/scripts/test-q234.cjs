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
