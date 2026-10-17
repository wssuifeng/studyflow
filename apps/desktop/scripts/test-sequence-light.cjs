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
 assert.ok(!reader.includes(':sequence='));assert.ok(reader.includes(':course-progress="courseProgressPercent"'))
 for(const marker of ['当前知识点','答案草稿','学习进度','下一知识点','窗口协作','保存保护','CourseToolContent'])assert.ok(panel.includes(marker),marker)
 assert.ok(panel.includes('completedLessons'));assert.ok(panel.includes('safeCourseProgress'));assert.ok(css.includes('.sequence-tools-panel'));assert.ok(css.includes('.sequence-progress-card'))
 assert.ok(!panel.includes('模拟保存失败'));assert.ok(!panel.includes('模拟批改'))
})

test('阅读骨架统一：主题ID不再分支顶栏与导航，双主题共用一套结构',()=>{
 const reader=read('features/courses/components/CourseReader.vue'),panel=read('features/courses/components/CourseToolsSidebar.vue')
 assert.ok(!reader.includes('sequenceTheme'),'CourseReader不得再用主题ID做功能分支')
 assert.ok(!reader.includes("activeTheme.value.id==='sequence-light'"))
 assert.equal((reader.match(/class="reader-toolbar"/g)||[]).length,1,'顶栏只保留一个reader-toolbar')
 assert.ok(!reader.includes('reader-navigation'),'顶部不再铺全量知识点导航')
 assert.ok(!reader.includes('KnowledgePointPager'),'全量导航只留左栏CourseOutline')
 // 统一顶栏：返回、课程上下文、音效/同步/工具开关在同一集合
 for(const marker of ['course-navigation-action','reader-context','reader-actions','toggleSound','syncFeedback','ref="toolsToggle"'])assert.ok(reader.includes(marker),marker)
 assert.ok(reader.includes('ThemeReadingArtwork'),'装饰插画不再由主题ID条件渲染')
 assert.ok(reader.includes('sequence-page-turn'));assert.ok(reader.includes('sequence-practice-entry'))
 // 焦点契约：侧栏tab是真实存在的dock-tab元素，面板打开后焦点可进入
 assert.ok(reader.includes("getElementById('dock-tab-'+tab.value)"))
 assert.ok(panel.includes('id="dock-tab-exercises"'));assert.ok(panel.includes('id="dock-tab-notes"'))
 assert.ok(!panel.includes('sequence-tools-tab'));assert.ok(!panel.includes('sequence-notes-tab'))
 assert.ok(panel.includes(':aria-expanded="!!menu"'),'···菜单暴露展开状态')
 for(const trigger of ['其他工具操作','重新打开工具'])assert.ok(panel.includes(trigger))
})

test('sequence-light viewport geometry is limited to course and detached tool shells',()=>{
 const css=read('features/courses/styles/sequence-light.css')
 assert.ok(css.includes('.app-shell.learning-shell'))
 assert.ok(css.includes('.app-shell.focus-shell'))
 assert.ok(!/\.app-shell\s*\{[^}]*height:100dvh/.test(css))
 assert.ok(!/body\s*\{\s*overflow:hidden/.test(css))
})

test('course return actions share explicit themed normal/hover/focus styling',()=>{
 const css=read('features/courses/styles/navigation-actions.css')
 assert.ok(css.includes('background:transparent'))
 assert.ok(css.includes(':hover:not(:disabled)'))
 assert.ok(css.includes(':focus-visible'))
 assert.ok(css.includes('prefers-reduced-motion'))
 assert.ok(css.includes('min-height:32px'))
 assert.ok(read('shared/styles/index.css').includes('navigation-actions.css'))
 for(const file of ['features/courses/components/CourseReader.vue','features/courses/components/CourseOutline.vue']) {
  const source=read(file);assert.ok(source.includes('course-navigation-action'));assert.ok(source.includes('viewBox="0 0 20 20"'))
 }
})
