"""Measured notebook limits on disposable production Vue/Core, not learner data."""
from pathlib import Path
import json, time, statistics, hashlib, sys
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f
from studyflow.modules.learning.notebook.document import plain
from studyflow.shared.domain import DomainError

sys.stdout.reconfigure(encoding='utf-8')
metrics=[];checks=[];errors=[]
def check(name, value):
    checks.append({'name':name,'passed':bool(value)})
    if not value: raise AssertionError(name)
def timed(fn):
    start=time.perf_counter();value=fn();return value,round((time.perf_counter()-start)*1000,1)
def content(chars):
    # Short paragraphs test normal document layout, not one fake hidden huge node.
    rows=[];remaining=chars
    while remaining:
        size=min(199,remaining)
        rows.append({'type':'paragraph','content':[{'type':'text','text':'n'*size}]})
        remaining-=size
        if remaining==1:
            rows[-1]['content'][0]['text']+='n';remaining=0
        elif remaining:remaining-=1 # plain() counts a paragraph separator
    assert len(plain(rows))==chars,(len(plain(rows)),chars)
    return rows

def read_all():
    result=f.service.read_plan_notebook(f.plan.id)
    rows=list(result['entries']);cursor=result['next_cursor']
    while cursor is not None:
        result=f.service.read_plan_notebook(f.plan.id,offset=cursor,expected_version=result['version'])
        rows.extend(result['entries']);cursor=result['next_cursor']
    return rows

try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if sys.platform=='win32' else None)
  page=browser.new_page(viewport={'width':1920,'height':1080});page.set_default_timeout(60000)
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle')
  page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=True).click()
  expect(page.get_by_role('textbox',name='连续笔记编辑器')).to_be_visible()
  for size in (100_000,1_000_000):
   old=f.service.read_plan_notebook(f.plan.id)
   operations=[{'type':'remove_entry','entry_id':e['id']} for e in read_all()]
   entries=[];left=size
   while left:
    chars=min(200_000,left);eid=f'pressure-{size}-{len(entries)}';entries.append({'id':eid,'scope':'PLAN','course_id':None,'lesson_id':None,'content':content(chars)});left-=chars
   operations.extend({'type':'insert_entry','entry':e} for e in entries)
   saved,write_ms=timed(lambda:f.service.apply_plan_notebook(f.plan.id,old['version'],f'pressure-{size}',operations))
   stored,read_ms=timed(read_all)
   check(f'{size}-exact-core-budget',sum(len(plain(e['content'])) for e in stored)==size)
   _,load_ms=timed(lambda:page.reload(wait_until='networkidle'))
   page.get_by_role('button',name='打开答题与笔记',exact=True).click() if page.get_by_role('button',name='打开答题与笔记',exact=True).count() else None
   page.get_by_role('tab',name='笔记',exact=True).click()
   start=time.perf_counter();page.get_by_role('button',name='课程范围',exact=True).click();page.locator('.picker-item').filter(has_text='全计划').click()
   expect(page.locator('.plan-notebook-v2 .entry-card')).to_have_count(len(entries));expect(page.locator('.plan-notebook-v2 .card-prose').first).to_contain_text('nnnn')
   render_ms=round((time.perf_counter()-start)*1000,1)
   # Measure key event -> next two rendered frames without a network round trip.
   page.locator('.plan-notebook-v2 .card-prose').last.click();page.keyboard.press('Control+End')
   latencies=[]
   for _ in range(8):
    page.evaluate("()=>{window.__latency=null;document.querySelector('.notebook-document').addEventListener('keydown',()=>{const start=performance.now();requestAnimationFrame(()=>requestAnimationFrame(()=>window.__latency=performance.now()-start))},{once:true})}")
    page.keyboard.press('x');page.wait_for_function('window.__latency!==null');latencies.append(page.evaluate('window.__latency'))
   for _ in range(8):page.keyboard.press('Backspace')
   heap=page.evaluate('performance.memory?.usedJSHeapSize||null')
   # Over-limit request must preserve the committed snapshot exactly.
   before=f.service.read_plan_notebook(f.plan.id);hash_before=hashlib.sha256(json.dumps(read_all(),sort_keys=True).encode()).hexdigest()
   if size==1_000_000:
    page.keyboard.press('End');page.keyboard.insert_text('x');page.keyboard.press('Control+s')
    expect(page.locator('footer.notebook-alert')).to_be_visible()
    expect(page.get_by_role('textbox',name='连续笔记编辑器')).to_contain_text('x')
    check('million-over-limit-buffer-retained',page.locator('footer.notebook-alert').count()==1)
    check('million-over-limit-no-version-change',f.service.read_plan_notebook(f.plan.id)['version']==before['version'])
    check('million-over-limit-no-truncation',hashlib.sha256(json.dumps(read_all(),sort_keys=True).encode()).hexdigest()==hash_before)
    page.wait_for_timeout(5500) # Observe delayed best-effort recovery write as well.
    page.screenshot(path=str(f.WORKSPACE/'notebook-million-rejected-buffer.png'))
   metrics.append({'characters':size,'cards':len(entries),'core_write_ms':write_ms,'core_read_ms':read_ms,'page_reload_ms':load_ms,'scope_render_observed_ms':render_ms,'key_to_frame_ms':latencies,'key_p95_ms':round(sorted(latencies)[-1],1),'heap_bytes':heap,'recovery_quota_warning':page.locator('p.notebook-alert').filter(has_text='本机恢复缓存不可写').count()>0})
  check('no-page-errors',not errors)
  browser.close()
finally:
 result={'workspace':str(f.WORKSPACE),'checks':checks,'metrics':metrics,'errors':errors,'note':'Measured this host only; no SLA or physical IME inference.'}
 (f.WORKSPACE/'notebook-pressure-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(result,ensure_ascii=False))
 f.server.shutdown();f.database.dispose()
