const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path')
const src=path.join(__dirname,'../src')
const read=p=>fs.readFileSync(path.join(src,p),'utf8')

test('普通页面路由拥有独立滚动与反馈清理契约',()=>{
 const app=read('app/App.vue')
 assert.match(app,/function resetMainScrollForRoute\(next:string\)/)
 assert.match(app,/resetMainScrollForRoute\(next\)/)
 assert.match(app,/nextName!==['"]course['"]&&nextName!==['"]tool['"]\)newFeedback\.value=false/)
 assert.match(app,/if\(held\.ok\)shutdownRequest=held\.requestId/)
 assert.doesNotMatch(app,/shutdownRequest=held\.requestId;if\(!held\.ok\)/)
})

test('队列首屏与分页使用同一页大小契约',()=>{
 const app=read('app/App.vue'),queue=read('features/reviews/components/QueueView.vue'),contracts=read('shared/api/contracts/reviews.ts'),index=read('shared/api/contracts/index.ts')
 assert.match(contracts,/export const QUEUE_PAGE_SIZE\s*=\s*50/)
 assert.match(index,/export \{QUEUE_PAGE_SIZE\} from ['"]\.\/reviews['"]/) 
 assert.match(app,/assignment\.summary',\{limit:QUEUE_PAGE_SIZE\}/)
 assert.match(queue,/limit:QUEUE_PAGE_SIZE/)
})

test('普通壳层和课程壳层不再依赖基础 sticky 侧栏',()=>{
 const shell=read('app/styles/shell.css'),workspace=read('app/styles/workspace.css'),runtime=read('shared/themes/runtime.css')
 assert.doesNotMatch(shell,/\.sidebar\{position:sticky/)
 assert.match(workspace,/\.app-shell\.workspace-shell\s*\{[\s\S]*overflow:hidden/)
 assert.match(runtime,/\.workspace-shell:not\(\.focus-shell\)>\.sidebar\{[\s\S]*position:fixed!important/)
})

test('序光与白紫只保留主题视觉覆盖并共享课程壳滚动边界',()=>{
 const sequence=read('features/courses/styles/sequence-light.css'),white=read('features/courses/styles/white-violet.css')
 assert.doesNotMatch(sequence,/\.app-shell\.learning-shell,\s*\n:root\[data-theme-id="sequence-light"\] \.app-shell\.focus-shell \{height:/)
 assert.doesNotMatch(white,/\.learning-shell > \.sidebar \{\s*position:\s*fixed/)
 assert.match(sequence,/\.learning-shell \.study-material-body/)
 assert.match(white,/\.learning-shell \.page-content\s*\{/) 
 assert.match(white,/\[data-theme-display="white-violet"\] \.theme-reading-artwork/)
})

test('状态提示和保存错误使用可见语义色',()=>{
 const notices=read('shared/styles/notices.css'),shell=read('app/styles/shell.css'),desktop=read('app/styles/desktop.css'),workspace=read('app/styles/workspace.css')
 assert.doesNotMatch(notices,/\.main-content:has\(\.native-tool-window\)/)
 assert.match(shell,/\.connection\.connected i\{background:var\(--theme-status-success\)/)
 assert.match(desktop,/\.window-controls button\.window-close:hover \{ background:var\(--theme-status-danger-soft\); color:var\(--theme-status-danger\); \}/)
 assert.match(workspace,/\.dock-save-status\.has-error \.dock-save-indicator \{background:var\(--theme-status-danger\)/)
})

test('前端审计修复保持生命周期与异常边界',()=>{
 const plan=read('features/plans/components/PlanDetail.vue'),workspace=read('features/workspace/components/WorkspaceSettings.vue'),tool=read('features/courses/components/ToolWindow.vue'),engine=read('shared/api/engine.ts'),plans=read('features/plans/components/PlanList.vue'),states=read('shared/styles/states.css'),interaction=read('shared/ui/interaction.ts')
 const mutate=plan.slice(plan.indexOf('async function mutate'),plan.indexOf('async function reorder'))
 assert.ok(mutate.indexOf('editing.value=true')<mutate.indexOf('notebook.save()'))
 assert.match(mutate,/finally\{editing\.value=false\}/)
  const switchTo=workspace.slice(workspace.indexOf('async function switchTo'),workspace.indexOf('\n}',workspace.indexOf('async function switchTo'))+2)
 assert.match(switchTo,/try\{\s*const prepared=await prepareTools\('shutdown'\)/)
 assert.match(switchTo,/if\(requestId\)await releaseTools\(requestId\)/)
 assert.match(tool,/session\.value&&ready\.value&&!await session\.value\.flush\(\)/)
 assert.match(tool,/Promise\.resolve\(handler\(e\.payload\)\)\.catch/)
 assert.match(engine,/response = await result\.json\(\)\s*\}\s*finally \{clearTimeout\(deadline\)\}/)
 assert.match(plans,/query\.value\.trim\(\)\.toLocaleLowerCase\(\)/)
 assert.match(plans,/当前筛选条件下没有计划/)
 assert.match(states,/\.empty-state,\.loading-state\{background:var\(--theme-surface-raised\)\}/)
 assert.match(states,/\.error-state\{background:color-mix\(in srgb,var\(--theme-status-danger-soft\)/)
 assert.match(interaction,/if\(raw===null\)return 72/)
})
