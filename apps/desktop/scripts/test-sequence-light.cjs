const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const src=path.join(__dirname,'../src'); const read=p=>fs.readFileSync(path.join(src,p),'utf8')
test('sequence-light honors enabled operation audio instead of force muting',()=>{
 const theme=JSON.parse(read('shared/themes/builtin/sequence-light.json'));assert.equal(theme.sound_profile,'soft-tap')
})
test('sequence-light ships actual layout, outline and local assets, not just a palette',()=>{
 const theme=JSON.parse(read('shared/themes/builtin/sequence-light.json'));assert.ok(theme.display.assets.length>=2)
 assert.ok(read('shared/themes/builtin-assets.ts').includes('sequence-light::sidebar-landscape'))
 const css=read('features/courses/styles/sequence-light.css');const shell=read('app/styles/workspace.css')+read('shared/themes/runtime.css');assert.ok(css.includes('[data-theme-id="sequence-light"]'));assert.ok(shell.includes('100dvh'));assert.ok(shell.includes('min-height:0'))
 assert.ok(read('features/courses/components/CourseReader.vue').includes('CourseOutline'))
 assert.ok(read('shared/styles/index.css').includes('sequence-light.css'))
})

test('sequence-light adapts the real tool dock into the approved right-rail hierarchy',()=>{
 const reader=read('features/courses/components/CourseReader.vue'),panel=read('features/courses/components/CourseToolsSidebar.vue'),css=read('features/courses/styles/sequence-light.css')
 assert.ok(reader.includes(':sequence=\"sequenceTheme\"'));assert.ok(reader.includes(':course-progress=\"courseProgressPercent\"'))
 for(const marker of ['当前知识点','答案草稿','学习进度','下一知识点','窗口协作','保存保护','CourseToolContent'])assert.ok(panel.includes(marker),marker)
 assert.ok(panel.includes('completedLessons'));assert.ok(panel.includes('safeCourseProgress'));assert.ok(css.includes('.sequence-tools-panel'));assert.ok(css.includes('.sequence-progress-card'))
 assert.ok(!panel.includes('模拟保存失败'));assert.ok(!panel.includes('模拟批改'))
})

test('sequence-light viewport geometry is limited to course and detached tool shells',()=>{
 const css=read('features/courses/styles/sequence-light.css')
 assert.ok(css.includes('.app-shell.learning-shell'))
 assert.ok(css.includes('.app-shell.focus-shell'))
 assert.ok(!/\.app-shell\s*\{[^}]*height:100dvh/.test(css))
 assert.ok(!/body\s*\{\s*overflow:hidden/.test(css))
})
