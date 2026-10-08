"""Real Vue + Python Core, synthetic local data only. No installed/learner workspace access."""
from __future__ import annotations
import argparse, json, threading, tempfile, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from sqlalchemy.orm import sessionmaker
from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.services import AppService, new_id
from studyflow.models import Course, Lesson, Exercise, PlanCourseItem
from studyflow.engine import StudyFlowEngine
from playwright.sync_api import sync_playwright, expect
from fastapi.encoders import jsonable_encoder

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'test-results';RESULTS.mkdir(exist_ok=True)
WORKSPACE=Path(tempfile.mkdtemp(prefix='workbench-',dir=RESULTS)).resolve()
assert WORKSPACE.is_relative_to(RESULTS.resolve())
settings=Settings(workspace_root=WORKSPACE,database_url=f"sqlite:///{(WORKSPACE/'test.db').as_posix()}")
database=build_engine(settings);init_db(database)
service=AppService(settings,sessionmaker(bind=database,autoflush=False,expire_on_commit=False))
engine=StudyFlowEngine(service=service);plan=service.create_plan_line('合成 · 连续学习计划')
courses=[]
with service.session() as db:
 for n in (1,2):
  c=Course(id=new_id(),plan_line_id=plan.id,title=f'合成课程{n}');db.add(c)
  db.add(PlanCourseItem(id=new_id(),plan_line_id=plan.id,course_id=c.id,sequence_number=n))
  for p in (1,2,3):
   filename=f'content/course-{n}-{p}.md';file=WORKSPACE/filename;file.parent.mkdir(parents=True,exist_ok=True)
   file.write_text(f'# 合成知识点{p}\n\n这里是课程{n}的冻结学习正文。连续笔记把理解关联到整个学习计划。\n\n## 概念联系\n\n同一课程可以包含多个知识点，不需要拆成多个课程。',encoding='utf-8')
   l=Lesson(id=new_id(),course_id=c.id,title=f'合成知识点{p}',position=p,markdown_path=filename);db.add(l)
   db.add(Exercise(id=new_id(),lesson_id=l.id,title=f'合成练习{p}',prompt=f'请用自己的话解释知识点{p}。',position=1))
  courses.append(c.id)
 db.flush()
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  if self.path!='/api/engine':self.send_error(404);return
  data=engine.handle(json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')))))
  content=json.dumps(jsonable_encoder(data),ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
 def do_GET(self):
  request=urlsplit(self.path).path.lstrip('/');file=(ROOT/'dist'/request).resolve()
  if not file.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not file.is_file():file=ROOT/'dist/index.html'
  content=file.read_bytes();types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'}
  self.send_response(200);self.send_header('Content-Type',types.get(file.suffix,'application/octet-stream'));self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
url=f'http://127.0.0.1:{server.server_port}'
def eventually(check):
 deadline=time.monotonic()+8
 while time.monotonic()<deadline:
  if check():return
  time.sleep(.05)
 raise AssertionError('Expected persisted synthetic state not observed')

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--inspect',action='store_true');args=parser.parse_args()
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  page=browser.new_page(viewport={'width':1580,'height':1050});page.set_default_timeout(8000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(url+'/#/course/'+courses[0]);page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='合成课程1',exact=True)).to_be_visible()
  page.screenshot(path=str(WORKSPACE/'01-initial.png'),full_page=True)
  print('INITIAL BUTTONS:',page.get_by_role('button').all_text_contents())
  if args.inspect:browser.close();return
  expect(page.locator('#workspace-tool-panel')).not_to_be_visible()
  page.get_by_role('button',name='打开答题与笔记',exact=True).click()
  page.get_by_role('tab',name='笔记',exact=False).click()
  page.get_by_role('button',name='＋ 写一段',exact=True).click();page.get_by_role('textbox',name='笔记：计划',exact=True).fill('第一课程形成的连续理解。')
  eventually(lambda:len(service.plan_notebook(plan.id)['blocks'])==1 and service.plan_notebook(plan.id)['blocks'][0]['text']=='第一课程形成的连续理解。')
  page.get_by_role('button',name='移除这段笔记',exact=True).click()
  expect(page.get_by_role('button',name='撤销删除',exact=True)).to_be_visible()
  page.get_by_role('button',name='撤销删除',exact=True).click()
  expect(page.get_by_role('textbox',name='笔记：计划',exact=True)).to_have_value('第一课程形成的连续理解。')
  paragraph=page.locator('.legacy-teaching-content p').first
  paragraph.evaluate('(el)=>{const selection=window.getSelection(),range=document.createRange();range.selectNodeContents(el);selection.removeAllRanges();selection.addRange(range);el.dispatchEvent(new MouseEvent("mouseup",{bubbles:true}))}')
  page.get_by_role('button',name='≡ 记入计划笔记',exact=True).click()
  eventually(lambda:any(b['quote'] for b in service.plan_notebook(plan.id)['blocks']))
  expect(page.locator('.notebook-highlight').first).to_be_visible()
  assert len(service.agent_queue()['items'])==0
  page.get_by_role('button',name='← 合成 · 连续学习计划',exact=True).click();expect(page.get_by_role('button',name='计划学习笔记',exact=True)).to_be_visible()
  page.get_by_role('button',name='计划学习笔记',exact=True).click();expect(page.get_by_role('textbox',name='笔记：计划',exact=True)).to_have_value('第一课程形成的连续理解。')
  page.get_by_role('button',name='课程路径',exact=True).click();page.locator('.path-list li').filter(has=page.get_by_role('heading',name='合成课程2',exact=True)).get_by_role('button',name='进入课程 →',exact=True).click()
  expect(page.get_by_role('heading',name='合成课程2',exact=True)).to_be_visible();page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('tab',name='笔记',exact=False).click()
  expect(page.get_by_role('textbox',name='笔记：计划',exact=True)).to_have_value('第一课程形成的连续理解。')
  expect(page.locator('.notebook-quote')).to_contain_text('课程1的冻结学习正文')
  page.get_by_role('button',name='＋ 写一段',exact=True).click();page.get_by_role('textbox',name='笔记：计划',exact=True).last.fill('第二课程继续这份笔记。')
  eventually(lambda:any(b['text']=='第二课程继续这份笔记。' for b in service.plan_notebook(plan.id)['blocks']))
  for name in ['关闭练习标签（保留数据）','关闭笔记标签（保留数据）','关闭大纲标签（保留数据）']:page.get_by_role('button',name=name,exact=True).click()
  expect(page.locator('.dock-surface')).not_to_be_visible()
  page.get_by_role('button',name='打开答题与笔记',exact=True).click();page.get_by_role('button',name='重新打开工具标签',exact=True).click();page.get_by_role('menuitem',name='笔记 重新打开',exact=False).click()
  expect(page.get_by_role('textbox',name='笔记：计划',exact=True).last).to_have_value('第二课程继续这份笔记。')
  page.screenshot(path=str(WORKSPACE/'02-continuous-notebook.png'),full_page=True)
  # Reopen a second tool without reopening/duplicating the note editor.
  page.get_by_role('button',name='重新打开工具标签',exact=True).click();page.get_by_role('menuitem',name='练习',exact=False).click()
  page.get_by_role('tab',name='笔记',exact=True).click();page.get_by_role('button',name='当前标签操作',exact=True).click();page.get_by_role('menuitem',name='在第二窗格查看',exact=True).click()
  expect(page.locator('.dock-pane')).to_have_count(2)
  expect(page.locator('.notebook-document')).to_have_count(1)
  separator=page.get_by_role('separator',name='调整双窗格比例',exact=True);separator.focus();page.keyboard.press('ArrowRight');expect(separator).to_have_attribute('aria-valuenow','55')
  resizer=page.get_by_role('separator',name='调整学习工具宽度',exact=True);box=resizer.bounding_box();page.mouse.move(box['x']+3,box['y']+80);page.mouse.down();page.mouse.move(box['x']-90,box['y']+80,steps=10);page.mouse.up()
  assert page.locator('.study-material').bounding_box()['width'] >= 280
  page.screenshot(path=str(WORKSPACE/'06-split-tools.png'),full_page=True)
  page.set_viewport_size({'width':730,'height':1000});expect(page.locator('.dock-surface')).to_be_visible();page.screenshot(path=str(WORKSPACE/'03-narrow.png'),full_page=True)
  assert not errors,errors
  print(json.dumps({'ok':True,'workspace':str(WORKSPACE),'checks':['continuous plan notes across two courses','frozen quote provenance','plan-level viewing','close/reopen tabs preserves notes','narrow layout','dual panes without duplicate editor','keyboard/pointer resize','no assignments created by notes'],'console_errors':errors},ensure_ascii=False))
  browser.close()
if __name__=='__main__':
 try:main()
 finally:server.shutdown();database.dispose()
