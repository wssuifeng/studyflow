"""Production Vue and real Core; isolated synthetic course/notes, no learner data."""
import json, threading, tempfile, mimetypes, os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright, expect
from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.services import AppService
from studyflow.engine import StudyFlowEngine
from studyflow.modules.learning.models import CourseStudySession

ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'test-results'/'learning-experience';RESULTS.mkdir(parents=True,exist_ok=True)
runtime_temp=RESULTS/'runtime-temp';runtime_temp.mkdir(exist_ok=True)
os.environ['TEMP']=os.environ['TMP']=str(runtime_temp.resolve())
tempfile.tempdir=str(runtime_temp.resolve())
workspace=Path(tempfile.mkdtemp(prefix='synthetic-',dir=RESULTS)).resolve()
settings=Settings(workspace_root=workspace,database_url=f"sqlite:///{(workspace/'test.db').as_posix()}")
db_engine=build_engine(settings);init_db(db_engine)
service=AppService(settings,sessionmaker(bind=db_engine,autoflush=False,expire_on_commit=False))
service.create_plan_line('合成文档计划')
package={'schema':'studyflow.course-package/3','package_id':'document-browser','plan_line':'合成文档计划','course':{'title':'合成 · 二进制位权','learning_mode':'general'},'lessons':[{'id':'binary','title':'二进制与位权','blocks':[
 {'id':'first','type':'concept','title':'先理解位权','body':'位权是该位一个单位代表的数值。\n\n**先记定义，再做计算。**'},
 {'id':'second','type':'concept','title':'再理解进位','body':'二进制中，相邻两位的位权相差两倍。'},
 {'id':'detail','type':'details','title':'为什么相差两倍','summary':'低位的两个单位合成高位的一个单位。','body':'### 深入推导\n每位只有 0 和 1；进位后的单位变化来自数制的基数。\n\n**详解正文用于补充理解。**'},
 {'id':'comparison','type':'comparison','title':'按数制对照','columns':['数制','基数','合法数字'],'rows':[['二进制','2','0、1'],['十进制','10','0—9']]},
 {'id':'example','type':'example','title':'计算一个小例子','given':'二进制数 101','steps':[{'title':'展开位权','body':'1×4 + 0×2 + 1×1'}],'conclusion':'对应十进制数 5。'},
 {'id':'summary','type':'summary','title':'带走三个要点','items':['位权由位置决定','进位来自基数','计算时逐位展开']},
 {'id':'practice','type':'practice','title':'用练习检验理解','exercise_ids':['q1']}],
 'exercises':[{'id':'q1','title':'位权小练习','prompt':'二进制 101 对应的十进制数是多少？'}]}]}
path=workspace/'course.json';path.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');imported=service.import_course_package(path);cid=imported['course_id']
opened=service.open_course_study(cid,'browser-initial');old_sid=opened['study']['id'];lid=opened['lessons'][0]['id']
service.save_study_note(old_sid,lid,'历史笔记必须保留',0,'browser-history-note')
engine=StudyFlowEngine(service=service);fault={'lost_restart':False,'progress':False};requests=[];errors=[];checks=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  if self.path!='/api/engine':self.send_error(404);return
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append(request)
  if fault['progress'] and request['method']=='course.study.progress.save':response={'id':request['id'],'ok':False,'error':{'code':'DATABASE_ERROR','message':'合成保存失败','next_action':'重试原请求或明确不保存退出。'}}
  else:
   response=engine.handle(request)
   if fault['lost_restart'] and request['method']=='course.study.restart' and response['ok']:
    fault['lost_restart']=False;response={'id':request['id'],'ok':False,'error':{'code':'CONNECTION_FAILED','message':'合成回执丢失，写入结果待确认','next_action':'保留原请求并重试。'}}
  content=json.dumps(jsonable_encoder(response),ensure_ascii=False).encode()
  try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
  except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):pass # The test client left after the engine response; do not swallow business failures.
 def do_GET(self):
  path=(ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
  if not path.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not path.is_file():path=ROOT/'dist/index.html'
  content=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
  context=browser.new_context(viewport={'width':1920,'height':1080},permissions=['clipboard-read','clipboard-write'])
  context.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'sequence-light',custom_themes:[],revision:{clock:1,source:'synthetic'}}))")
  page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
  page.goto(origin+'/#/course/'+cid);page.wait_for_load_state('networkidle');expect(page.get_by_role('heading',name='先理解位权',exact=True)).to_be_visible()
  expect(page.locator('html')).to_have_attribute('data-theme-id','sequence-light')
  assert page.locator('.is-concept-pair').count()==0;checks.append('linear_concepts')
  expect(page.locator('.teaching-disclosure')).not_to_have_attribute('open','')
  expect(page.get_by_text('低位的两个单位合成高位的一个单位。',exact=True)).to_be_visible()
  page.screenshot(path=str(RESULTS/'sequence-document-1920.png'));checks.append('summary_visible_detail_closed')
  page.locator('.teaching-disclosure summary').focus();page.keyboard.press('Enter')
  expect(page.get_by_role('heading',name='深入推导',exact=True)).to_be_visible();checks.append('keyboard_disclosure')
  page.locator('.teaching-disclosure summary').click();page.get_by_role('tab',name='本节大纲',exact=True).click()
  page.get_by_role('button',name='深入推导',exact=True).click()
  expect(page.get_by_role('heading',name='深入推导',exact=True)).to_be_visible()
  page.screenshot(path=str(RESULTS/'sequence-detail-expanded-1920.png'));checks.append('outline_reveals_hidden_target')
  page.reload();expect(page.get_by_role('heading',name='深入推导',exact=True)).to_be_visible();checks.append('frozen_scope_expansion_restored')
  page.locator('.teaching-detail-body p').first.scroll_into_view_if_needed()
  page.evaluate("""async () => {await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));const node=document.querySelector('.teaching-detail-body p');const selection=getSelection(),range=document.createRange();range.selectNodeContents(node);selection.removeAllRanges();selection.addRange(range);node.dispatchEvent(new MouseEvent('mouseup',{bubbles:true}))}""")
  with page.expect_response(lambda r:r.url.endswith('/api/engine') and r.request.post_data_json.get('method')=='plan.notebook.apply') as saved:
   page.get_by_role('button',name='≡ 记入计划笔记',exact=True).click()
  assert saved.value.json()['ok'];excerpt=service.read_plan_notebook(opened['course']['plan_line_id'])['sources'][0]
  assert excerpt['source_block_id']=='detail' and excerpt['source_study_id']==old_sid;checks.append('detail_excerpt_preserves_frozen_source')
  page.get_by_role('button',name='用最新版重新开始',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible()
  page.get_by_role('button',name='取消',exact=True).click();assert service.course_study_detail(old_sid)['study']['is_current'];checks.append('restart_cancel_no_mutation')
  source=workspace/imported['paths'][0];source.write_text(source.read_text(encoding='utf-8').replace('先记定义，再做计算','新版：定义清楚，再做计算'),encoding='utf-8')
  page.get_by_role('button',name='用最新版重新开始',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible()
  fault['lost_restart']=True;page.get_by_role('button',name='保留历史并重新开始',exact=True).click()
  expect(page.get_by_text('重新开始的结果待确认，原请求已保留。请勿重复创建轮次。',exact=True)).to_be_visible()
  page.evaluate("window.location.hash='#/today'");expect(page.get_by_role('alertdialog')).to_be_visible()
  page.get_by_role('button',name='返回学习',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible();checks.append('restart_modal_does_not_trap_exit')
  page.get_by_role('button',name='稍后处理',exact=True).click()
  page.reload();expect(page.get_by_role('button',name='重试原请求',exact=True)).to_be_visible()
  page.get_by_role('button',name='重试原请求',exact=True).click()
  expect(page.get_by_text('新版：定义清楚，再做计算。',exact=True)).to_be_visible()
  restart_calls=[r['params'] for r in requests if r['method']=='course.study.restart'];assert len(restart_calls)==2 and restart_calls[0]==restart_calls[1]
  with service.session(read_only=True) as db:assert len(db.scalars(select(CourseStudySession)).all())==2
  assert service.course_study_detail(old_sid)['course']['study_status']=='ABANDONED'
  assert service.study_notes(old_sid)['notes'][0]['text']=='历史笔记必须保留';checks.append('lost_reply_exact_replay_history_retained')
  expect(page.locator('.teaching-disclosure')).not_to_have_attribute('open','');checks.append('new_frozen_hash_does_not_inherit_expansion')
  page.get_by_role('button',name='打开答题与笔记',exact=True).click();expect(page.locator('#workspace-tool-panel')).to_be_visible()
  assert page.get_by_role('heading',name='先理解位权',exact=True).is_visible();page.screenshot(path=str(RESULTS/'sequence-tools-1920.png'));checks.append('shared_template_with_tools')
  page.goto(origin+'/#/settings');copy=page.get_by_role('button',name='复制Agent接入说明',exact=True);expect(copy).to_be_enabled();copy.click();copied=page.evaluate('navigator.clipboard.readText()')
  assert str(workspace) in copied and 'undefined' not in copied and '仓库 Skill' in copied and '"-m","studyflow"' in copied;checks.append('settings_exact_source_paths')
  # Use a new context so the selected theme is not reset by the first context init script.
  white=browser.new_context(viewport={'width':1280,'height':800});white.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'white-violet',custom_themes:[],revision:{clock:1,source:'synthetic-white'}}))")
  second=white.new_page();second.on('pageerror',lambda error:errors.append(str(error)));second.goto(origin+'/#/course/'+cid)
  expect(second.get_by_role('heading',name='先理解位权',exact=True)).to_be_visible();expect(second.locator('html')).to_have_attribute('data-theme-id','white-violet')
  second.locator('.teaching-disclosure summary').click();expect(second.get_by_role('heading',name='深入推导',exact=True)).to_be_visible()
  assert second.locator('.is-concept-pair').count()==0 and second.evaluate('document.documentElement.scrollWidth<=innerWidth')
  second.screenshot(path=str(RESULTS/'white-document-1280.png'));checks.append('white_violet_same_functional_template')
  second.set_viewport_size({'width':960,'height':720});second.get_by_role('button',name='打开答题与笔记',exact=True).click();assert second.evaluate('document.documentElement.scrollWidth<=innerWidth')
  second.screenshot(path=str(RESULTS/'white-tools-960.png'));checks.append('narrow_tools_no_overflow')
  fault['progress']=True;second.get_by_role('button',name='学习控制台',exact=True).click()
  expect(second.get_by_role('alertdialog')).to_be_visible();second.screenshot(path=str(RESULTS/'save-failure-exit-960.png'));second.get_by_role('button',name='不保存并离开',exact=True).click()
  expect(second.get_by_role('heading',name='学习控制台',exact=True)).to_be_visible();checks.append('save_failure_explicit_exit')
  fault['progress']=False
  source_page=white.new_page();source_page.on('pageerror',lambda error:errors.append(str(error)));source_page.goto(origin+'/#/source/'+old_sid+'?lesson='+lid+'&block=detail')
  expect(source_page.get_by_text('冻结来源 · 只读，不开启学习轮次',exact=True)).to_be_visible()
  expect(source_page.get_by_role('heading',name='深入推导',exact=True)).to_be_visible();source_page.screenshot(path=str(RESULTS/'frozen-details-source-1280.png'));checks.append('historical_source_auto_reveals_detail')
  source_page.goto(origin+'/#/source/'+old_sid+'?lesson='+lid);expect(source_page.get_by_role('heading',name='深入推导',exact=True)).to_be_visible();checks.append('unanchored_source_keeps_full_detail_visible')
  assert not errors,errors;browser.close()
 result={'checks':checks,'pageerrors':errors,'workspace':str(workspace),'restart_requests':restart_calls,'business_acceptance':'not_evaluated'}
 (RESULTS/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
finally:server.shutdown();server.server_close();engine.close();db_engine.dispose()
