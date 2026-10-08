"""Application-level panel geometry and learning regression, synthetic data only."""
import json
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f

checks=[]
with f.service.session() as db:
 from studyflow.models import Lesson
 lesson=db.query(Lesson).filter_by(course_id=f.courses[0]).order_by(Lesson.position).first()
 source=f.WORKSPACE/lesson.markdown_path
 source.write_text(source.read_text(encoding='utf-8')+'\n\n'.join('## 合成阅读段落 '+str(n)+'\n\n仅用于验证阅读位置在侧栏展开前后不会丢失。'*5 for n in range(30)),encoding='utf-8')
def bounds(page,selector):return page.locator(selector).bounding_box()
def no_overflow(page):assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
def run():
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  page=browser.new_page(viewport={'width':1440,'height':900});page.set_default_timeout(8000)
  errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  try:
   page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle')
   expect(page.get_by_role('heading',name='合成课程1',exact=True)).to_be_visible()
   expect(page.locator('#workspace-tool-panel')).not_to_be_visible()
   page.locator('.study-material-body').evaluate('(el)=>el.scrollTop=360')
   page.wait_for_function('document.querySelector(".study-material-body").scrollTop>300')
   before=bounds(page,'.main-content');nav=bounds(page,'.sidebar')
   page.screenshot(path=str(f.WORKSPACE/'panel-closed.png'))
   page.get_by_role('button',name='打开答题与笔记',exact=True).click()
   page.locator('#workspace-tool-panel').evaluate('(el)=>Promise.all(el.getAnimations().map(a=>a.finished))')
   panel=bounds(page,'#workspace-tool-panel');main=bounds(page,'.main-content');left=bounds(page,'.sidebar')
   assert panel['y']==main['y']==left['y'] and panel['height']==main['height']==left['height']
   assert main['width']<before['width'] and abs(left['width']-nav['width'])<2 and abs(left['x']-nav['x'])<2
   assert abs(panel['x']-(main['x']+main['width']))<2
   assert page.locator('#workspace-tool-panel').evaluate('(el)=>el.parentElement.classList.contains("app-shell")')
   no_overflow(page);checks.append('default closed; three equal-height sibling surfaces; main and tools resize while left navigation rail stays fixed')
   expect(page.get_by_role('tab',name='练习',exact=False)).to_be_focused()
   page.get_by_role('textbox').fill('第一题的合成答案，收起和切换后仍需保留。')
   page.get_by_role('button',name='收起工具侧栏',exact=True).click()
   expect(page.get_by_role('button',name='打开答题与笔记',exact=True)).to_be_focused()
   expect(page.locator('#workspace-tool-panel')).not_to_be_visible()
   page.get_by_role('button',name='打开答题与笔记',exact=True).click()
   expect(page.get_by_role('textbox')).to_have_value('第一题的合成答案，收起和切换后仍需保留。')
   page.locator('#workspace-tool-panel').evaluate('(el)=>Promise.all(el.getAnimations().map(a=>a.finished))')
   page.screenshot(path=str(f.WORKSPACE/'panel-answer.png'))
   checks.append('collapse preserves answer and restores keyboard focus')
   position=page.locator('.study-material-body').evaluate('(el)=>el.scrollTop')
   page.get_by_role('button',name='展开到内容区',exact=True).click()
   expect(page.locator('.main-content')).not_to_be_visible()
   page.get_by_role('button',name='返回侧栏',exact=True).click()
   assert abs(page.locator('.study-material-body').evaluate('(el)=>el.scrollTop')-position)<2
   checks.append('expanded tools preserve reading position')
   separator=page.get_by_role('separator',name='调整学习工具宽度',exact=True)
   separator.focus();page.keyboard.press('ArrowLeft');expect(separator).to_have_attribute('aria-valuenow','440')
   page.keyboard.press('ArrowRight');expect(separator).to_have_attribute('aria-valuenow','420')
   page.set_viewport_size({'width':1024,'height':800})
   page.wait_for_function('document.querySelector(".sidebar").getBoundingClientRect().width===184')
   no_overflow(page)
   assert abs(bounds(page,'.sidebar')['width']-184)<2
   assert bounds(page,'.main-content')['width']>=360
   page.set_viewport_size({'width':730,'height':800})
   expect(page.locator('.main-content')).not_to_be_visible()
   expect(page.get_by_role('button',name='← 返回阅读',exact=True)).to_be_visible()
   expect(page.get_by_role('button',name='下一知识点 →',exact=True)).to_be_visible()
   page.get_by_role('button',name='下一知识点 →',exact=True).click()
   expect(page.get_by_role('textbox')).to_have_value('')
   page.route('**/api/engine',lambda route:route.fulfill(status=503,body='synthetic save failure') if 'course.answers.draft.save' in (route.request.post_data or '') else route.continue_())
   page.get_by_role('textbox').fill('第二题通过窄屏工具作答。')
   expect(page.get_by_role('button',name='重试保存',exact=True)).to_be_visible()
   expect(page.get_by_role('textbox')).to_have_value('第二题通过窄屏工具作答。')
   page.unroute('**/api/engine')
   page.get_by_role('button',name='重试保存',exact=True).click()
   expect(page.get_by_role('button',name='重试保存',exact=True)).to_have_count(0)
   checks.append('narrow panel exposes retry after synthetic save failure, preserving input')
   page.get_by_role('button',name='下一知识点 →',exact=True).click()
   expect(page.get_by_role('textbox')).to_have_value('')
   page.get_by_role('textbox').fill('第三题也在同一学习轮次。')
   page.screenshot(path=str(f.WORKSPACE/'panel-narrow.png'))
   page.get_by_role('button',name='提交并完成本次学习 →',exact=True).click()
   expect(page.get_by_role('textbox')).to_have_count(0)
   assert len(f.service.agent_queue()['items'])==3
   no_overflow(page);checks.append('keyboard resize; compact navigation; narrow same-round whole-course submission')
   page.get_by_role('button',name='← 返回阅读',exact=True).click()
   expect(page.locator('.main-content')).to_be_visible()
   page.set_viewport_size({'width':1440,'height':900})
   page.get_by_role('button',name='打开答题与笔记',exact=True).click()
   page.get_by_role('button',name='展开到内容区',exact=True).click()
   expect(page.locator('.main-content')).not_to_be_visible()
   expect(page.get_by_role('button',name='继续学习 →',exact=True)).to_be_visible()
   page.get_by_role('button',name='返回侧栏',exact=True).click()
   expect(page.locator('.main-content')).to_be_visible()
   checks.append('expanded tools retain the same action bar')
   page.get_by_role('button',name='收起工具侧栏',exact=True).click()
   page.evaluate('location.hash=location.hash+"&tab=answers"')
   expect(page.locator('#workspace-tool-panel')).to_be_visible()
   checks.append('explicit same-course answer link opens panel')
   page.emulate_media(reduced_motion='reduce')
   assert page.locator('.workspace-tool-panel').evaluate('(el)=>getComputedStyle(el).animationName')=='none'
   page.get_by_role('button',name='工作区',exact=True).click()
   sound=page.get_by_role('checkbox',name='启用轻柔操作音效',exact=False)
   expect(sound).not_to_be_checked();sound.check();page.get_by_role('button',name='试听',exact=True).click()
   page.reload();expect(sound).to_be_checked();sound.uncheck()
   expect(page.locator('#workspace-tool-panel')).not_to_be_visible()
   checks.append('reduced-motion respected; sound off by default, preference persists; leaving clears panel')
   assert not errors,errors
   result={'ok':True,'checks':checks,'page_errors':errors,'workspace':str(f.WORKSPACE)}
   (f.WORKSPACE/'panel-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
   print(json.dumps(result,ensure_ascii=False))
  except Exception:
   page.screenshot(path=str(f.WORKSPACE/'panel-failed.png'));print('EVIDENCE',f.WORKSPACE,'ERRORS',errors);raise
  finally:browser.close()
if __name__=='__main__':
 try:run()
 finally:f.server.shutdown();f.database.dispose()
