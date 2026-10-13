"""Multiple frozen citations and hidden-entry invariants through real Vue/Core."""
import sys,json,hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
import smoke_workbench_support as f
from studyflow.modules.learning.notebook.document import plain
sys.stdout.reconfigure(encoding='utf-8')
checks=[];errors=[]
def check(name,value):
 checks.append({'name':name,'passed':bool(value)})
 if not value:raise AssertionError(name)
try:
 cid=f.courses[0];opened=f.service.open_course_study(cid,'complex-source-open');sid=opened['study']['id'];l1,l2=opened['lessons'][:2]
 original1='冻结学习正文。';original2='多个知识点，不需要拆成多个课程。'
 sources=[{'id':'complex-a','course_id':cid,'lesson_id':l1['id'],'source_study_id':sid,'original':original1},{'id':'complex-b','course_id':cid,'lesson_id':l2['id'],'source_study_id':sid,'original':original2}]
 def marked(text,src,occ):return {'type':'text','text':text,'marks':[{'type':'citation','attrs':{'sourceId':src,'occurrenceId':occ}}]}
 entry={'id':'mixed','scope':'LESSON','course_id':cid,'lesson_id':l1['id'],'content':[{'type':'paragraph','content':[marked(original1,'complex-a','occ-a'),{'type':'text','text':' 我的联系：'},marked(original2,'complex-b','occ-b')]}]}
 hidden={'id':'hidden','scope':'LESSON','course_id':cid,'lesson_id':l2['id'],'content':[{'type':'paragraph','content':[{'type':'text','text':'隐藏知识点内容必须保留。'}]}]}
 f.service.apply_plan_notebook(f.plan.id,0,'complex-seed',[{'type':'insert_entry','entry':entry},{'type':'insert_entry','entry':hidden}],sources)
 hidden_hash=hashlib.sha256(json.dumps(hidden,sort_keys=True).encode()).hexdigest()
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if sys.platform=='win32' else None);page=browser.new_page(viewport={'width':1920,'height':1080});page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f.url+'/#/course/'+cid);page.wait_for_load_state('networkidle');page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=True).click()
  expect(page.locator('[data-note-source]')).to_have_count(2)
  check('source-labels-do-not-expand-prose',page.locator('.source-popover').count()==0)
  page.locator('[data-note-source="complex-a"]').hover();expect(page.get_by_role('dialog',name='引用来源',exact=True)).to_be_visible();page.get_by_role('button',name='查看原始摘录',exact=True).click();expect(page.locator('.source-popover blockquote')).to_have_text(original1)
  page.screenshot(path=str(f.WORKSPACE/'notebook-mixed-source-peek.png'));page.get_by_role('button',name='关闭来源',exact=True).click()
  page.locator('.card-prose').first.click();page.keyboard.press('Control+End');page.keyboard.insert_text(' 自己补充。');page.keyboard.press('Control+s');expect(page.get_by_text('已保存',exact=False).first).to_be_visible()
  data=f.service.read_plan_notebook(f.plan.id);current=next(e for e in data['entries'] if e['id']=='hidden');current={k:v for k,v in current.items() if k in hidden}
  check('hidden-lesson-id-content-same-hash',hashlib.sha256(json.dumps(current,sort_keys=True).encode()).hexdigest()==hidden_hash)
  check('mixed-source-registration-preserved',len(data['sources'])==2)
  check('immutable-originals-preserved',{s['id']:s['original'] for s in data['sources']}=={s['id']:s['original'] for s in sources})
  page.locator('[data-note-source="complex-a"]').hover();expect(page.get_by_role('dialog',name='引用来源',exact=True)).to_be_visible();page.get_by_role('button',name='转为普通笔记',exact=True).click();page.keyboard.press('Control+s');expect(page.locator('[data-note-source="complex-a"]')).to_have_count(0)
  check('remove-citation-keeps-text',original1 in page.get_by_role('textbox',name='连续笔记编辑器').inner_text())
  page.get_by_role('button',name='撤销',exact=True).click();expect(page.locator('[data-note-source="complex-a"]')).to_have_count(1);check('citation-removal-is-undoable',True)
  browser.close()
 check('no-page-errors',not errors)
finally:
 result={'workspace':str(f.WORKSPACE),'checks':checks,'errors':errors}
 (f.WORKSPACE/'notebook-complex-source-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False));f.server.shutdown();f.database.dispose()
