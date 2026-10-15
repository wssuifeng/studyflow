"""Real Vue/Core, isolated synthetic data; deterministic audio triggers, not hearing acceptance."""
import json, mimetypes, os, tempfile, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import sessionmaker
from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.engine import StudyFlowEngine
from studyflow.services import AppService
ROOT=Path(__file__).resolve().parents[1]
RESULTS=ROOT/'test-results'/'english-light-20261014';RESULTS.mkdir(parents=True,exist_ok=True)
workspace=Path(tempfile.mkdtemp(prefix='synthetic-',dir=RESULTS))
settings=Settings(workspace_root=workspace,database_url='sqlite:///'+(workspace/'test.db').as_posix())
database=build_engine(settings);init_db(database)
service=AppService(settings,sessionmaker(bind=database,autoflush=False,expire_on_commit=False))
package=json.loads((ROOT.parents[1]/'skills/studyflow-agent/examples/english-course-package-v6.json').read_text(encoding='utf-8'))
package['lessons'][0]['exercises'][0]['english'].update(gloss='我',phonetic='/aɪ/')
package['lessons'][0]['exercises'][2]['english'].update(gloss='我喜欢',explanation='I 表示说话者；like 保持动词原形。')
service.create_plan_line(package['plan_line']);source=workspace/'course.json';source.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');course=service.import_course_package(source)
engine=StudyFlowEngine(service=service);lane=threading.Lock();requests=[];errors=[];checks=[]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  with lane:
   started=time.monotonic();response=engine.handle(request);requests.append({'method':request['method'],'params':request.get('params'), 'ms':round((time.monotonic()-started)*1000,2)})
  content=json.dumps(jsonable_encoder(response),ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
 def do_GET(self):
  file=(ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
  if not file.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not file.is_file():file=ROOT/'dist/index.html'
  data=file.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(file.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_address[1]}'
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
  for theme in ['sequence-light','white-violet']:
   opened=service.open_course_study(course['course_id'],idempotency_key='open-'+theme,review_round=theme=='white-violet')
   sid=opened['study']['id'];context=browser.new_context(viewport={'width':1920,'height':1080})
   context.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:"+json.dumps(theme)+",custom_themes:[],revision:{clock:1,source:'test'}}));window.__audio=[];window.Audio=class {constructor(src){this.src=src;window.__audio.push(this)}load(){queueMicrotask(()=>this.oncanplay?.())}play(){return Promise.resolve()}pause(){this.paused=true}}")
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto(url+'/#/english/'+sid)
   expect(page.get_by_role('heading',name='我',exact=True)).to_be_visible();page.wait_for_function('window.__audio.length===1')
   assert page.locator('.english-breakdown,.english-answer-reference').count()==0
   assert page.get_by_text('本句提示',exact=True).count()==0
   page.get_by_label('第 1 个单词',exact=True).press('Control+Semicolon')
   expect(page.locator('.fallback-meaning')).to_have_text('我');expect(page.locator('.fallback-phonetic')).to_have_text('/aɪ/')
   assert page.locator('.part-role').count()==0
   page.get_by_role('button',name='朗读单词 I',exact=True).click();page.wait_for_function('window.__audio.length===2')
   assert json.loads(page.evaluate('JSON.stringify(window.__audio.map(a=>a.src))'))[-1].find('audio=I')>=0
   page.screenshot(path=str(RESULTS/(theme+'-fallback-word-1920.png')))
   page.get_by_label('第 1 个单词',exact=True).press('Control+Semicolon');assert page.locator('.english-breakdown').count()==0
   checks.append(theme+' fallback word meaning, supplied pronunciation and exact audio index')
   page.get_by_label('训练快捷键').get_by_role('button',name='暂跳').click()
   expect(page.get_by_role('heading',name='喜欢',exact=True)).to_be_visible()
   for answer,prompt in [('like','我喜欢'),('I like','这个食物'),('the food','我喜欢这个食物')]:
    if answer=='I like':
     page.get_by_label('第 1 个单词',exact=True).press('Control+Semicolon')
     expect(page.locator('.fallback-meaning')).to_have_text('我喜欢');expect(page.locator('.breakdown-explanation')).to_contain_text('保持动词原形')
     expect(page.get_by_role('button',name='朗读单词 like',exact=True)).to_be_visible();assert page.locator('.part-role').count()==0
     page.set_viewport_size({'width':960,'height':720})
     rect=page.locator('.english-breakdown').bounding_box();assert rect and rect['x']>=0 and rect['x']+rect['width']<=962,rect
     page.screenshot(path=str(RESULTS/(theme+'-fallback-chunk-960.png')));page.set_viewport_size({'width':1920,'height':1080})
     page.screenshot(path=str(RESULTS/(theme+'-fallback-chunk-1920.png')))
     checks.append(theme+' fragment fallback has a readable meaning without fabricated roles at both window sizes')
    page.get_by_label('第 1 个单词',exact=True).fill(answer.split()[0])
    if ' ' in answer:page.get_by_label('第 2 个单词',exact=True).fill(answer.split()[1])
    page.get_by_label('第 1 个单词',exact=True).press('Enter');expect(page.locator('.english-target')).to_be_visible()
    page.get_by_role('button',name='下一项 →',exact=True).click();expect(page.get_by_role('heading',name=prompt,exact=True)).to_be_visible()
   words=['I','lik','the','food']
   for i,word in enumerate(words):page.get_by_label(f'第 {i+1} 个单词',exact=True).fill(word)
   page.get_by_label('第 2 个单词',exact=True).press('Enter');expect(page.get_by_label('第 2 个单词',exact=True)).to_have_attribute('aria-invalid','true');expect(page.get_by_role('button',name='检查答案 Enter',exact=True)).to_be_enabled()
   assert page.locator('.english-breakdown').count()==0
   page.get_by_label('第 2 个单词',exact=True).press('Enter');expect(page.locator('.english-breakdown')).to_be_visible()
   expect(page.locator('.part-role')).to_have_text(['主语','谓语','宾语'])
   page.set_viewport_size({'width':960,'height':720})
   frame=page.evaluate('''()=>{const f=document.querySelector('.english-training-footer');return {bottom:f.getBoundingClientRect().bottom,height:innerHeight,document:document.documentElement.scrollHeight,width:innerWidth,scrollWidth:document.documentElement.scrollWidth}}''')
   assert frame['bottom']<=frame['height']+2 and frame['document']<=frame['height']+2 and frame['scrollWidth']<=frame['width']+2,frame
   checks.append(theme+' narrow error analysis keeps the full shortcut footer within viewport')
   page.set_viewport_size({'width':1920,'height':1080})
   page.screenshot(path=str(RESULTS/(theme+'-error-breakdown-1920.png')))
   page.get_by_label('第 2 个单词',exact=True).fill('like');page.get_by_label('第 2 个单词',exact=True).press('Enter')
   expect(page.locator('.english-target')).to_have_text('I like the food');assert page.locator('.english-breakdown').count()==0
   page.get_by_role('button',name='下一项 →',exact=True).click();expect(page.get_by_role('heading',name='他没有一个计划',exact=True)).to_be_visible()
   for i,word in enumerate(['He',"doesn't",'have','a','plan']):page.get_by_label(f'第 {i+1} 个单词',exact=True).fill(word)
   page.get_by_label('第 5 个单词',exact=True).press('Enter');expect(page.locator('.english-target')).to_have_text("He doesn't have a plan")
   page.get_by_role('button',name='下一项 →',exact=True).click()
   for i,word in enumerate(['write','code']):page.get_by_label(f'第 {i+1} 个单词',exact=True).fill(word)
   page.get_by_label('第 1 个单词',exact=True).press('Enter');expect(page.locator('.english-target')).to_be_visible();page.get_by_role('button',name='下一项 →',exact=True).click()
   for i,word in enumerate(['I','write','code','every','day']):page.get_by_label(f'第 {i+1} 个单词',exact=True).fill(word)
   before=len(page.evaluate('window.__audio'));page.get_by_label('第 2 个单词',exact=True).press('Enter');expect(page.locator('.english-target')).to_be_visible();page.wait_for_function('(n)=>window.__audio.length===n+1',arg=before)
   page.get_by_role('button',name='完成本课',exact=True).click();expect(page.get_by_role('heading',name='我',exact=True)).to_be_visible()
   assert page.locator('.english-error').count()==0
   expect(page.locator('.status-banner.info .status-mark')).to_have_text('i')
   checks.append(theme+' incomplete navigation uses an information icon, not a success mark')
   page.get_by_label('第 1 个单词',exact=True).fill('I');page.get_by_label('第 1 个单词',exact=True).press('Enter');expect(page.locator('.english-target')).to_be_visible()
   page.get_by_role('button',name='下一项 →',exact=True).click()
   page.get_by_label('打开课程目录',exact=True).click();page.locator('.english-directory li').last.get_by_role('button').click()
   page.get_by_role('button',name='完成本课',exact=True).click();expect(page.get_by_role('heading',name='这门课的训练已确认',exact=True)).to_be_visible()
   checks.extend([theme+' automatic entry/check sentence trigger',theme+' early-word Enter checks full input',theme+' analysis only after two failures and hides after success',theme+' explicit grammatical spans',theme+' alternate word count matches complete variant',theme+' final submit routes first omitted item',theme+' complete course with no Agent review'])
   page.screenshot(path=str(RESULTS/(theme+'-complete-1920.png')));context.close()
  browser.close()
 assert not errors,errors
 result={'ok':True,'checks':checks,'page_errors':errors,'scope':'synthetic-only','audio':'deterministic trigger mock; not audible acceptance','workspace':str(workspace),'requests':requests}
 (RESULTS/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='requests'},ensure_ascii=False))
except Exception:
 (workspace/'failure-evidence.json').write_text(json.dumps({'requests':requests,'page_errors':errors,'view':service.english.get(sid) if sid else None},ensure_ascii=False,indent=2),encoding='utf-8')
 raise
finally:server.shutdown();engine.close();service.audio.provider.close()
