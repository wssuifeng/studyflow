"""Real production Vue + real Core, isolated synthetic workspace, no learner data."""
import json,threading,tempfile,mimetypes,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit
from sqlalchemy.orm import sessionmaker
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright,expect
from studyflow.config import Settings
from studyflow.db import build_engine,init_db
from studyflow.services import AppService
from studyflow.engine import StudyFlowEngine

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'test-results'/'english';RESULTS.mkdir(parents=True,exist_ok=True)
workspace=Path(tempfile.mkdtemp(prefix='synthetic-',dir=RESULTS)).resolve()
settings=Settings(workspace_root=workspace,database_url=f"sqlite:///{(workspace/'test.db').as_posix()}")
db_engine=build_engine(settings);init_db(db_engine)
service=AppService(settings,sessionmaker(bind=db_engine,autoflush=False,expire_on_commit=False))
service.create_plan_line('合成英语计划')
package={"schema":"studyflow.course-package/2","package_id":"english-browser","plan_line":"合成英语计划","course":{"title":"合成 · 表达喜好","summary":"用 I like 表达喜好；本课为产品测试，不是学习记录。","learning_mode":"english"},"lessons":[{"id":"likes","title":"表达喜好","blocks":[{"id":"intro","type":"concept","title":"I like","body":"I like 表示我喜欢。"}],"exercises":[{"id":"tea","title":"我喜欢茶","prompt":"我喜欢茶。","english":{"target":"I like tea.","objective_ids":["likes"]}},{"id":"coffee","title":"我喜欢咖啡","prompt":"我喜欢咖啡。","english":{"target":"I like coffee.","objective_ids":["likes"]}}]}]}
path=workspace/'course.json';path.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');course=service.import_course_package(path)
engine=StudyFlowEngine(service=service)
fault={'save':False}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  if self.path!='/api/engine':self.send_error(404);return
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  response=({'id':request.get('id'),'ok':False,'error':{'code':'DATABASE_ERROR','message':'合成保存故障：测试不保存退出。','next_action':'重试原请求或不保存离开。'}} if fault['save'] and request.get('method') in {'course.english.save','course.english.retest-save'} else engine.handle(request))
  content=json.dumps(jsonable_encoder(response),ensure_ascii=False).encode()
  try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
  except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):pass # The test client left after the engine response; do not swallow business failures.
 def do_GET(self):
  path=(ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
  if not path.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not path.is_file():path=ROOT/'dist/index.html'
  content=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
errors=[];checks=[];requests=[]
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel="msedge" if os.name=="nt" else None);page=browser.new_page(viewport={"width":1920,"height":1080})
  page.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'sequence-light',custom_themes:[],revision:{clock:1,source:'synthetic'}}))")
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.on('request',lambda request:requests.append(request.post_data_json) if request.url.endswith('/api/engine') else None)
  page.route('https://dict.youdao.com/**',lambda route:route.abort())
  page.goto(f'http://127.0.0.1:{server.server_port}/#/course/'+course['course_id']);page.wait_for_load_state('networkidle')
  expect(page.get_by_role('heading',name='合成 · 表达喜好',exact=True)).to_be_visible()
  expect(page.locator('html')).to_have_attribute('data-theme-id','sequence-light');checks.append('sequence_light_overview')
  page.get_by_role('button',name='开始 / 继续训练 →').click()
  expect(page.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible()
  page.get_by_role('button',name='查看本组讲解',exact=True).click();expect(page.get_by_role('heading',name='I like',exact=True)).to_be_visible();page.get_by_role('button',name='查看本组讲解',exact=True).click();checks.append('frozen_group_teaching')
  page.get_by_role('textbox',name='第 1 个单词').fill('I');page.get_by_role('textbox',name='第 1 个单词').press('Space');expect(page.get_by_role('textbox',name='第 2 个单词')).to_be_focused();page.get_by_role('textbox',name='第 2 个单词').fill('lik');page.get_by_role('textbox',name='第 2 个单词').press('Space');expect(page.get_by_role('textbox',name='第 3 个单词')).to_be_focused();page.get_by_role('textbox',name='第 3 个单词').fill('tea');checks.append('space_to_next_word')
  page.get_by_role('textbox',name='第 3 个单词').press('Enter')
  expect(page.get_by_text('原输入：lik',exact=True)).to_be_visible()
  expect(page.get_by_role('textbox',name='第 2 个单词')).to_be_focused()
  page.screenshot(path=str(RESULTS/'correction-1920.png'))
  checks.append('wrong_word_focus_original_retained')
  page.get_by_role('textbox',name='第 2 个单词').press('l');page.get_by_role('textbox',name='第 2 个单词').type('ike')
  page.get_by_role('textbox',name='第 3 个单词').press('Enter')
  expect(page.locator('.english-target')).to_have_text('I like tea.')
  page.screenshot(path=str(RESULTS/'answer-1920.png'));checks.append('first_key_replaces_error_and_checks')
  page.get_by_role('button',name='笔记',exact=True).click()
  note=page.get_by_role('textbox',name='连续笔记编辑器',exact=True);note.click();page.keyboard.insert_text('合成笔记：把词句串成计划级学习记录。');page.keyboard.press('Control+s');page.wait_for_timeout(1000)
  page.get_by_role('button',name='关闭侧栏').click()
  page.get_by_role('button',name='下一项 →',exact=True).click()
  expect(page.get_by_role('heading',name='我喜欢咖啡。',exact=True)).to_be_visible()
  page.get_by_role('textbox',name='第 1 个单词').evaluate("el=>{const data=new DataTransfer();data.setData('text/plain','I like coffee');el.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}))}");expect(page.get_by_role('textbox',name='第 2 个单词')).to_have_value('like');checks.append('paste_sentence_into_tokens')
  page.get_by_role('textbox',name='第 3 个单词').press('Enter');expect(page.locator('.english-target')).to_have_text('I like coffee.')
  page.get_by_role('button',name='完成并提交本课',exact=True).click();expect(page.get_by_role('heading',name='这门课的训练已确认')).to_be_visible()
  checks.append('whole_course_submit')
  page.get_by_role('button',name='查看错误与复习',exact=True).click();expect(page.get_by_role('heading',name='错误与复习',exact=True)).to_be_visible()
  page.get_by_role('button',name='查看原错与证据').first.click();expect(page.get_by_text('I lik tea',exact=True)).to_be_visible();checks.append('scoped_error_evidence')
  page.get_by_role('button',name='收录复习',exact=True).click();page.get_by_role('button',name='无提示复测',exact=True).click()
  expect(page.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible()
  page.get_by_role('textbox',name='第 1 个单词').fill('I');page.get_by_role('textbox',name='第 2 个单词').fill('like');page.get_by_role('textbox',name='第 3 个单词').fill('tea')
  expect(page.locator('.english-training-header small')).to_have_text('草稿已同步');page.reload();expect(page.get_by_role('textbox',name='第 2 个单词')).to_have_value('like');checks.append('retest_saved_draft_restores_after_reload')
  page.get_by_role('button',name='确认本次复测',exact=True).click();expect(page.get_by_role('heading',name='本次无提示复测通过',exact=True)).to_be_visible();checks.append('real_retest_task')
  page.screenshot(path=str(RESULTS/'retest-1920.png'))
  # Run the other official theme at a laptop-width viewport and inject only a save failure.
  page.close();page=browser.new_page(viewport={'width':960,'height':720})
  page.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'white-violet',custom_themes:[],revision:{clock:1,source:'synthetic'}}))")
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.route('https://dict.youdao.com/**',lambda route:route.abort())
  page.goto(f'http://127.0.0.1:{server.server_port}/#/course/'+course['course_id'])
  expect(page.locator('html')).to_have_attribute('data-theme-id','white-violet')
  page.get_by_role('button',name='开启新的回顾轮次',exact=True).click()
  expect(page.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible()
  page.get_by_role('textbox',name='第 1 个单词').focus();page.get_by_role('textbox',name='第 1 个单词').evaluate("el=>el.dispatchEvent(new KeyboardEvent('keydown',{key:' ',isComposing:true,bubbles:true,cancelable:true}))");expect(page.get_by_role('textbox',name='第 1 个单词')).to_be_focused();page.get_by_role('textbox',name='第 2 个单词').focus();page.get_by_role('textbox',name='第 2 个单词').press('Backspace');expect(page.get_by_role('textbox',name='第 1 个单词')).to_be_focused();checks.append('ime_guard_and_empty_backspace')
  page.get_by_role('button',name='暂时跳过',exact=True).click()
  expect(page.get_by_role('heading',name='我喜欢咖啡。',exact=True)).to_be_visible()
  page.get_by_role('button',name='← 上一项',exact=True).click()
  expect(page.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible();checks.append('skip_and_return_without_error')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'), 'horizontal overflow'
  page.screenshot(path=str(RESULTS/'white-violet-960.png'));checks.append('white_violet_narrow_shared_layout')
  fault['save']=True
  page.get_by_role('textbox',name='第 1 个单词').fill('I')
  expect(page.get_by_role('alert')).to_contain_text('合成保存故障')
  page.get_by_role('button',name='← 返回课程',exact=True).click()
  expect(page.get_by_role('alertdialog')).to_be_visible()
  page.screenshot(path=str(RESULTS/'save-failure-exit-960.png'))
  page.get_by_role('button',name='不保存并离开',exact=True).click()
  expect(page.get_by_role('heading',name='合成 · 表达喜好',exact=True)).to_be_visible();checks.append('save_failure_discard_exit')
  fault['save']=False
  assert not errors,errors
  browser.close()
 result={'checks':checks,'pageerrors':errors,'workspace':str(workspace),'screenshots':['correction-1920.png','answer-1920.png','retest-1920.png','white-violet-960.png','save-failure-exit-960.png'],'business_acceptance':'not_evaluated'}
 (RESULTS/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:
 server.shutdown();server.server_close();engine.close();db_engine.dispose()
