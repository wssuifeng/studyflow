"""Synthetic CLI publication -> production Vue learning -> unchanged source evidence."""
import json,os,sys,threading,tempfile,mimetypes,subprocess
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
from studyflow.modules.learning.english.checker import tokenize
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
RESULTS=ROOT/'test-results'/'english-remediation';RESULTS.mkdir(parents=True,exist_ok=True)
runtime=RESULTS/'runtime-temp';runtime.mkdir(exist_ok=True);os.environ['TEMP']=str(runtime.resolve());os.environ['TMP']=str(runtime.resolve())
workspace=Path(tempfile.mkdtemp(prefix='synthetic-',dir=RESULTS)).resolve()
settings=Settings(workspace_root=workspace,database_url='sqlite:///'+(workspace/'test.db').as_posix())
db_engine=build_engine(settings);init_db(db_engine);service=AppService(settings,sessionmaker(bind=db_engine,autoflush=False,expire_on_commit=False))
sys.path.insert(0,str(REPO/'packages/core/tests'))
from test_english_remediation import source,progressive_package
original,request=source(service,workspace)
env={**os.environ,'STUDYFLOW_WORKSPACE':str(workspace),'STUDYFLOW_DATABASE_URL':settings.database_url,'PYTHONIOENCODING':'utf-8'}
receipts=[]
def cli(args,params=None):
 if params is not None:
  file=workspace/('request-'+str(len(receipts))+'.json');file.write_text(json.dumps(params,ensure_ascii=False),encoding='utf-8');args=[*args,'--file',str(file)]
 proc=subprocess.run([sys.executable,'-X','utf8','-m','studyflow',*args,'--format','json'],cwd=REPO,env=env,capture_output=True,text=True,encoding='utf-8',timeout=40)
 value=json.loads(proc.stdout);assert proc.returncode==0 and value['ok'],(args,proc.returncode,proc.stdout,proc.stderr)
 receipts.append({'args':args,'exit_code':proc.returncode,'response':value})
 return value.get('result',value)
for command in ('version','capabilities','doctor'):cli([command])
cli(['call','--method','system.schema'],{'method':'course.remediation.publish'})
cli(['course','validate-package','--file',request['path']])
preview=cli(['call','--method','course.remediation.preview'],request)
payload={**request,'preview_hash':preview['preview_hash'],'idempotency_key':'cli-remediation-once'}
created=cli(['call','--method','course.remediation.publish'],payload)
assert cli(['call','--method','course.remediation.publish'],payload)==created
cli(['call','--method','course.remediation.list'],{'plan_line_id':original['plan_id']})
cli(['call','--method','course.remediation.get'],{'course_id':created['course_id']})
engine=StudyFlowEngine(service=service)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  if self.path!='/api/engine':self.send_error(404);return
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  body=json.dumps(jsonable_encoder(engine.handle(request)),ensure_ascii=False).encode()
  try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
  except (ConnectionAbortedError,ConnectionResetError,BrokenPipeError):pass # Client left after a committed response; no business exception is swallowed.
 def do_GET(self):
  path=(ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
  if not path.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not path.is_file():path=ROOT/'dist/index.html'
  body=path.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
checks=[];errors=[];origin='http://127.0.0.1:'+str(server.server_port)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
  page=browser.new_page(viewport={'width':1920,'height':1080})
  page.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'sequence-light',custom_themes:[],revision:{clock:1,source:'synthetic'}}))")
  page.on('pageerror',lambda error:errors.append(str(error)));page.route('https://dict.youdao.com/**',lambda route:route.abort())
  page.goto(origin+'/#/plan/'+original['plan_id']);page.get_by_role('button',name='补充学习 · 1',exact=True).click()
  expect(page.get_by_role('heading',name='主语变化与动词形式',exact=True)).to_be_visible();page.screenshot(path=str(RESULTS/'supplement-plan-1920.png'));checks.append('main_and_supplement_separate')
  page.get_by_role('button',name='学习目标与来源',exact=True).click();expect(page.get_by_text('来源规则版本',exact=False)).to_be_visible();checks.append('bounded_provenance_view')
  page.get_by_role('button',name='开始学习 →',exact=True).click();page.get_by_role('button',name='开始 / 继续训练 →',exact=True).click()
  expect(page.get_by_text('必要词汇',exact=False).first).to_be_visible();checks.append('progression_full_training_surface')
  page.get_by_role('button',name='笔记',exact=True).click();expect(page.get_by_role('complementary',name='计划笔记')).to_be_visible()
  assert page.locator('aside').count()==1
  page.get_by_role('button',name='＋ 写一段',exact=True).click();page.locator('.plan-notebook textarea').last.fill('合成补充学习笔记：从词到句逐步练习。')
  page.screenshot(path=str(RESULTS/'english-notes-1920.png'));page.get_by_role('button',name='关闭侧栏',exact=True).click();checks.append('notes_only_drawer_shared_plan_notebook')
  page.get_by_role('button',name='☰ 课程目录',exact=True).click();expect(page.get_by_role('dialog',name='课程目录')).to_be_visible();page.keyboard.press('Escape');expect(page.get_by_role('dialog',name='课程目录')).to_have_count(0);checks.append('directory_modal_not_another_sidebar')
  for index,ex in enumerate(progressive_package()['lessons'][0]['exercises']):
   words=tokenize(ex['english']['target'])
   for i,word in enumerate(words):page.get_by_role('textbox',name=f'第 {i+1} 个单词',exact=True).fill(word)
   if ex['english']['progression']['stage']=='transfer':
    assert page.get_by_role('button',name='查看本组讲解',exact=True).count()==0
    page.screenshot(path=str(RESULTS/'transfer-1920.png'));checks.append('transfer_no_inline_solution_scaffold')
   page.get_by_role('button',name='检查答案 ↵',exact=True).click();expect(page.locator('.english-target')).to_have_text(ex['english']['target'])
   if index<4:page.get_by_role('button',name='下一项 →',exact=True).click()
  page.get_by_role('button',name='完成并提交本课',exact=True).click();expect(page.get_by_role('heading',name='这门课的训练已确认')).to_be_visible();checks.append('whole_supplement_learning_submit')
  page.screenshot(path=str(RESULTS/'completed-1920.png'))
  page.get_by_role('button',name='查看错误与复习',exact=True).click();expect(page.get_by_role('heading',name='补充学习',exact=True)).to_be_visible()
  expect(page.get_by_text('本轮迁移验证无提示通过；原错题复测单独记录。',exact=True)).to_be_visible();checks.append('result_returns_to_source_errors')
  assert service.plan_detail(original['plan_id'])['plan']['course_total']==1
  stats=service.mistakes.summary(plan_line_id=original['plan_id'],domain='english');assert stats['valid_error_evidence']==1
  assert '合成补充学习笔记' in json.dumps(service.plan_notebook(original['plan_id']),ensure_ascii=False);checks.append('completed_preserves_original_error_mainline_and_notes')
  white=browser.new_context(viewport={'width':1280,'height':800});white.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'white-violet',custom_themes:[],revision:{clock:1,source:'synthetic-white'}}))")
  second=white.new_page();second.on('pageerror',lambda error:errors.append(str(error)));second.goto(origin+'/#/plan/'+original['plan_id']);second.get_by_role('button',name='补充学习 · 1',exact=True).click()
  expect(second.get_by_role('heading',name='主语变化与动词形式',exact=True)).to_be_visible();assert second.evaluate('document.documentElement.scrollWidth<=innerWidth');second.screenshot(path=str(RESULTS/'white-supplement-1280.png'));checks.append('white_violet_shared_functional_layout')
  assert not errors,errors;browser.close()
 result={'checks':checks,'pageerrors':errors,'cli_receipts':receipts,'workspace':str(workspace),'business_acceptance':'not_evaluated'}
 (RESULTS/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'checks':checks,'pageerrors':errors,'cli_receipts':len(receipts),'business_acceptance':'not_evaluated'},ensure_ascii=False))
finally:server.shutdown();server.server_close();engine.close();db_engine.dispose()
