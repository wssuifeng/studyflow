"""Real production Vue + Core with disposable synthetic workspace; no installed data."""
from pathlib import Path
import sys
sys.stdout.reconfigure(encoding="utf-8")
import json,time
import smoke_workbench_support as f
from playwright.sync_api import sync_playwright,expect
from studyflow.modules.learning.notebook.document import plain

checks=[];errors=[];responses=[]
def check(name,ok):
    checks.append({"name":name,"passed":bool(ok)})
    if not ok: raise AssertionError(name)
def wait(checker):
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        if checker():return
        time.sleep(.08)
    page.screenshot(path=str(f.WORKSPACE/"failure.png"));print(page.locator(".plan-notebook-v2").inner_text());print(json.dumps([r for r in responses if not r.get("ok")][-5:],ensure_ascii=False));raise AssertionError("Persisted state not observed")

try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,**({"channel":"msedge"} if sys.platform=="win32" else {}))
  page=browser.new_page(viewport={"width":1600,"height":1000});page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)));page.on('response',lambda r:responses.append(r.json()) if '/api/engine' in r.url else None)
  page.goto(f.url+'/#/settings');page.wait_for_load_state('networkidle');page.locator('.theme-option').filter(has_text='序光').click()
  page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle')
  page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=True).click()
  editor=page.get_by_role('textbox',name='连续笔记编辑器',exact=True);expect(editor).to_be_visible()
  check('single-continuous-editor',editor.count()==1)
  check('no-obsolete-scratch-entry',page.locator('.notebook-legacy').count()==0 and page.get_by_text('查看旧版随手草稿（原文保留）',exact=True).count()==0)
  def geometry():
   return page.evaluate("""()=>{const pane=document.getElementById('sequence-tools-pane'),root=pane.querySelector('.plan-notebook-v2'),tabs=document.querySelector('.sequence-tool-tabs');const box=el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width}};return {tabs:box(tabs),root:box(root),navigation:box(root.querySelector('.scope-bar')),toolbar:box(root.querySelector('.tool-header')),outerOverflow:getComputedStyle(pane).overflowY,innerOverflow:getComputedStyle(root.querySelector('.notebook-scroll')).overflowY}}""")
  initial_geometry=geometry()
  (f.WORKSPACE/'notebook-sidebar-geometry-initial.json').write_text(json.dumps(initial_geometry,indent=2),encoding='utf-8')
  page.screenshot(path=str(f.WORKSPACE/'notebook-sidebar-empty.png'))
  check('navigation-fills-tab-container',all(abs(initial_geometry[k]['left']-initial_geometry['tabs']['left'])<=1 and abs(initial_geometry[k]['right']-initial_geometry['tabs']['right'])<=1 for k in ['root','navigation','toolbar']))
  check('single-notebook-scroll-owner',initial_geometry['outerOverflow']=='hidden' and initial_geometry['innerOverflow']=='auto')
  expect(page.locator('.plan-notebook-v2 [data-course-group="'+f.courses[0]+'"]').first).to_be_visible()
  expect(page.locator('.plan-notebook-v2 .lesson-title').first).to_contain_text('合成知识点1')
  check('default-context-has-three-levels',page.locator('.plan-notebook-v2 .course-shell .lesson-group .entry-card').count()==1)
  check('empty-notebook-does-not-auto-write',f.service.read_plan_notebook(f.plan.id)['version']==0)
  page.locator('.plan-notebook-v2 .card-prose').first.click();page.keyboard.insert_text('第一段真实保存的理解。');page.keyboard.press('Enter');page.keyboard.insert_text('自然段无需另加一行。');page.keyboard.press('Control+Enter');page.keyboard.insert_text('第二张记录。');page.keyboard.press('Control+s')
  wait(lambda:len(f.service.read_plan_notebook(f.plan.id)['entries'])==2)
  result=f.service.read_plan_notebook(f.plan.id)
  check('natural-paragraph-and-split',len(result['entries'][0]['content'])==2)
  check('default-current-lesson',all(e['scope']=='LESSON' for e in result['entries']))
  page.locator('.plan-notebook-v2 .lesson-title button').first.click()
  check('current-lesson-fold-preserves-saved-records',page.locator('.plan-notebook-v2 .entry-card').count()==0 and len(f.service.read_plan_notebook(f.plan.id)['entries'])==2)
  page.locator('.plan-notebook-v2 .lesson-title button').first.click()
  expect(page.locator('.plan-notebook-v2 .entry-card')).to_have_count(2)
  page.get_by_role('button',name='只读阅读',exact=True).click();before=f.service.read_plan_notebook(f.plan.id)['version'];page.locator('.plan-notebook-v2 .card-prose').first.click();page.keyboard.press('Control+End');page.keyboard.press('Control+Enter');page.keyboard.press('Backspace');page.wait_for_timeout(1000)
  check('readonly-cannot-mutate',f.service.read_plan_notebook(f.plan.id)['version']==before and page.locator('.entry-card').count()==2)
  page.get_by_role('button',name='编辑笔记',exact=True).click();page.screenshot(path=str(f.WORKSPACE/'notebook-sequence-light.png'))
  page.reload();page.wait_for_load_state('networkidle');page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=True).click();expect(editor).to_contain_text('第二张记录。')
  check('reload-durable-notes',True)
  para=page.locator('.legacy-teaching-content p').first
  para.evaluate('(el)=>{const s=window.getSelection(),r=document.createRange();r.selectNodeContents(el);s.removeAllRanges();s.addRange(r);el.dispatchEvent(new MouseEvent("mouseup",{bubbles:true}))}')
  page.get_by_role('button',name='≡ 记入计划笔记',exact=True).click()
  wait(lambda:len(f.service.read_plan_notebook(f.plan.id)['sources'])==1)
  quote=page.locator('[data-note-source]').first;expect(quote).to_be_visible();quote.hover();expect(page.get_by_role('dialog',name='引用来源')).to_be_visible()
  page.get_by_role('button',name='查看原始摘录',exact=True).click();expect(page.locator('.source-popover blockquote')).to_contain_text('冻结学习正文')
  check('verified-editable-quote',f.service.read_plan_notebook(f.plan.id)['sources'][0]['verification']=='VERIFIED')
  with page.expect_download() as exported:page.get_by_role('button',name='导出笔记',exact=True).click()
  target=f.WORKSPACE/'notebook-export.json';exported.value.save_as(str(target));portable=json.loads(target.read_text(encoding='utf-8'))
  check('json-export-keeps-full-provenance',portable['schema']=='studyflow.notebook-recovery/2' and portable['document']['sources'][0]['content_hash']==f.service.read_plan_notebook(f.plan.id)['sources'][0]['content_hash'])
  page.screenshot(path=str(f.WORKSPACE/'notebook-source.png'));page.keyboard.press('Escape')
  page.get_by_role('button',name='课程范围',exact=True).click();page.get_by_role('button',name='全计划',exact=True).click();expect(page.locator('.course-title').first).to_be_visible()
  check('plan-grouping',page.locator('.lesson-title').count()>=1)
  page.locator('.course-title button').first.click();check('fold-hides-records',page.locator('.entry-card').count()==0);page.locator('.course-title button').first.click();check('fold-preserves-records',len(f.service.read_plan_notebook(f.plan.id)['entries'])==3)
  page.screenshot(path=str(f.WORKSPACE/'notebook-all-plan.png'))
  # Preserve the browser/controller under real save errors and prove escape route.
  def reject(route):
   req=route.request.post_data_json
   if req.get('method')=='plan.notebook.apply':route.fulfill(status=200,content_type='application/json',body=json.dumps({"ok":False,"id":req.get('id'),"protocol_version":"1.2","error":{"code":"DATABASE_READ_ONLY","message":"合成失败注入","hint":"仅验证失败退出"}}))
   else:route.continue_()
  page.route('**/api/engine',reject);page.locator('.plan-notebook-v2 .card-prose').first.click();page.keyboard.press('Control+End');page.keyboard.insert_text('未保存失败场景');page.keyboard.press('Control+s');expect(page.locator('.notebook-alert').filter(has_text='保存尚未确认')).to_be_visible()
  page.get_by_role('button',name='学习控制台',exact=True).first.click();expect(page.get_by_role('alertdialog')).to_be_visible();page.screenshot(path=str(f.WORKSPACE/'notebook-failed-exit.png'));page.get_by_role('button',name='不保存并离开',exact=True).click();expect(page.get_by_role('alertdialog')).not_to_be_visible();check('failure-can-discard-and-leave',True)
  page.unroute('**/api/engine',reject)
  page.goto(f.url+'/#/settings');page.wait_for_load_state('networkidle');page.locator('.theme-option').filter(has_text='白紫轻学').click();page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle');page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=True).click();expect(editor).to_be_visible()
  check('white-violet-shared-editor',editor.count()==1)
  purple_geometry=geometry()
  check('white-violet-navigation-fills-tab-container',all(abs(purple_geometry[k]['left']-purple_geometry['tabs']['left'])<=1 and abs(purple_geometry[k]['right']-purple_geometry['tabs']['right'])<=1 for k in ['root','navigation','toolbar']))
  check('white-violet-single-scroll-owner',purple_geometry['outerOverflow']=='hidden' and purple_geometry['innerOverflow']=='auto')
  retry=page.get_by_role('button',name='原键重试／读取冲突',exact=True)
  if retry.count():retry.click();expect(retry).not_to_be_visible()
  page.locator('.plan-notebook-v2 .card-prose').first.click();page.keyboard.press('Control+End');page.keyboard.insert_text('白紫主题也能真实写入');page.keyboard.press('Control+s')
  wait(lambda:any('白紫主题也能真实写入' in plain(e['content']) for e in f.service.read_plan_notebook(f.plan.id)['entries']))
  check('white-violet-edit-and-persist',True);page.screenshot(path=str(f.WORKSPACE/'notebook-white-violet.png'))
  page.set_viewport_size({'width':720,'height':1000});check('narrow-no-document-overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'));page.screenshot(path=str(f.WORKSPACE/'notebook-narrow.png'))
  responsive=[]
  for theme,label in [('sequence-light','序光'),('white-violet','白紫轻学')]:
   page.set_viewport_size({'width':1600,'height':1000})
   page.goto(f.url+'/#/settings');page.wait_for_load_state('networkidle');page.locator('.theme-option').filter(has_text=label).click()
   page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle')
   opener=page.get_by_role('button',name='打开答题与笔记',exact=True)
   expect(opener.or_(page.get_by_role('tab',name='笔记',exact=True)).first).to_be_visible()
   if opener.count():opener.click()
   page.get_by_role('tab',name='笔记',exact=True).click()
   page.get_by_role('button',name='回到当前知识点',exact=True).click()
   expect(page.locator('.plan-notebook-v2 .lesson-title').first).to_contain_text('合成知识点1')
   page.screenshot(path=str(f.WORKSPACE/('notebook-sidebar-'+theme+'-current.png')))
   page.locator('.course-tools.unified-tools-panel').screenshot(path=str(f.WORKSPACE/('notebook-sidebar-'+theme+'-panel.png')))
   for width in [1600,1280,1024,900,720]:
    page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(120)
    measure=geometry()
    contained=page.locator('.plan-notebook-v2').evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
    text_width=page.locator('.plan-notebook-v2 .card-prose').first.bounding_box()['width']
    same_width=all(abs(measure[k]['left']-measure['tabs']['left'])<=1 and abs(measure[k]['right']-measure['tabs']['right'])<=1 for k in ['root','navigation','toolbar'])
    ok=same_width and contained and text_width>=180 and measure['outerOverflow']=='hidden' and measure['innerOverflow']=='auto'
    responsive.append({'theme':theme,'viewport':width,'text_width':text_width,**measure,'passed':ok})
    check('responsive-full-width-'+theme+'-'+str(width),ok)
  (f.WORKSPACE/'notebook-sidebar-responsive.json').write_text(json.dumps(responsive,indent=2),encoding='utf-8')
  page.set_viewport_size({'width':1280,'height':720});page.wait_for_timeout(120)
  last=page.locator('.plan-notebook-v2 .entry-card').last
  old_height=last.bounding_box()['height']
  page.locator('.plan-notebook-v2 .card-prose').last.click();page.keyboard.press('Control+End')
  for i in range(18):
   page.keyboard.press('Enter');page.keyboard.insert_text('段落自然增长验证 '+str(i+1)+'：无需手动加行，正文保持连续编辑。')
  page.keyboard.press('Control+s')
  wait(lambda:any('段落自然增长验证 18' in plain(e['content']) for e in f.service.read_plan_notebook(f.plan.id)['entries']))
  check('paragraph-card-grows-with-content',last.bounding_box()['height']>old_height+200)
  nav=page.locator('.plan-notebook-v2 .scope-bar').bounding_box()
  scroll_result=page.locator('.plan-notebook-v2 .notebook-scroll').evaluate('(el)=>{el.scrollTop=el.scrollHeight;return {overflow:el.scrollHeight>el.clientHeight,top:el.scrollTop}}')
  after_nav=page.locator('.plan-notebook-v2 .scope-bar').bounding_box()
  check('long-content-scroll-keeps-navigation-fixed',scroll_result['overflow'] and scroll_result['top']>0 and abs(nav['y']-after_nav['y'])<=1)
  page.screenshot(path=str(f.WORKSPACE/'notebook-sidebar-grown-paragraph.png'))
  check('no-runtime-errors',not errors)
  browser.close()
finally:
 (f.WORKSPACE/'notebook-v2-verification.json').write_text(json.dumps({"workspace":str(f.WORKSPACE),"checks":checks,"errors":errors},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({"workspace":str(f.WORKSPACE),"passed":sum(c['passed'] for c in checks),"checks":len(checks),"errors":errors},ensure_ascii=False))
 f.server.shutdown();f.database.dispose()
