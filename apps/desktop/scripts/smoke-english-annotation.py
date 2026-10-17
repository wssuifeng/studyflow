"""Actual Vue/Core annotation geometry and author-only phonetics; synthetic data only."""
import copy,json,mimetypes,os,tempfile,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright,expect
from sqlalchemy.orm import sessionmaker
from studyflow.config import Settings
from studyflow.db import build_engine,init_db
from studyflow.engine import StudyFlowEngine
from studyflow.services import AppService
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'/'english-annotation-186';OUT.mkdir(parents=True,exist_ok=True)
workspace=Path(tempfile.mkdtemp(prefix='synthetic-',dir=OUT))
settings=Settings(workspace_root=workspace,database_url='sqlite:///'+(workspace/'test.db').as_posix())
db=build_engine(settings);init_db(db);service=AppService(settings,sessionmaker(bind=db,autoflush=False,expire_on_commit=False))
engine=StudyFlowEngine(service=service);requests=[];errors=[];checks=[];geometry=[];lane=threading.Lock()
words=[{'gloss':'定冠词：特指','pos':'det.','phonetic':'/ðə/'},{'gloss':'大小','pos':'n.'},{'gloss':'……的','pos':'prep.'},{'gloss':'定冠词：特指','pos':'det.'},{'gloss':'寄存器','pos':'n.','phonetic':'/ˈredʒɪstɚ/'}]
items=[
 {'id':'noun-phrase','title':'名词短语','prompt':'寄存器的大小','english':{'target':'the size of the register','gloss':'寄存器的大小','explanation':'这是名词短语，中心词是size；独立短语本身不固定作主语或宾语。','progression':{'chain_id':'context','stage':'chunk'},'sentence_parts':[{'role':'subject','start':0,'end':5,'words':words}]}},
 {'id':'verb-context','title':'有语境的谓语片段','prompt':'在 Each process ___. 中填入“有一个状态”的部分。','english':{'target':'has a state','gloss':'有一个状态（主语是each process）','explanation':'给定主语each process是第三人称单数，因此使用has。state在进程语境中表示状态。','progression':{'chain_id':'context','stage':'chunk'},'sentence_parts':[{'role':'predicate','start':0,'end':1,'words':[{'gloss':'有','pos':'v.'}]},{'role':'object','start':1,'end':3,'words':[{'gloss':'一个','pos':'det.','phonetic':'/ə/'},{'gloss':'状态','pos':'n.','phonetic':'/steɪt/'}]}]}},
 {'id':'clause','title':'完整句','prompt':'每个进程都有一个状态。','english':{'target':'Each process has a state.','gloss':'每个进程都有一个状态。','explanation':'在本句中，Each process是主语，has是谓语动词，a state是宾语。','progression':{'chain_id':'context','stage':'pattern'},'sentence_parts':[{'role':'subject','start':0,'end':2,'words':[{'gloss':'每个','pos':'det.'},{'gloss':'进程','pos':'n.','phonetic':'/ˈprɑːses/'}]},{'role':'predicate','start':2,'end':3,'words':[{'gloss':'有','pos':'v.'}]},{'role':'object','start':3,'end':5,'words':[{'gloss':'一个','pos':'det.'},{'gloss':'状态：这里指进程当时的运行情况，而不是国家、州或陈述。','pos':'n.','phonetic':'/steɪt/'}]}]}}
]
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  req=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  with lane:result=engine.handle(req);requests.append(req['method'])
  data=json.dumps(jsonable_encoder(result),ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_GET(self):
  f=(ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
  if not f.is_relative_to((ROOT/'dist').resolve()):self.send_error(400);return
  if not f.is_file():f=ROOT/'dist/index.html'
  data=f.read_bytes();self.send_response(200);self.send_header('Content-Type',mimetypes.guess_type(f.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
  for theme in ['sequence-light','white-violet']:
   package={'schema':'studyflow.course-package/6','package_id':'annotation-'+theme,'plan_line':'合成解析几何-'+theme,'course':{'title':'合成语境与解析验证','learning_mode':'english'},'lessons':[{'id':'l','title':'语境与结构','blocks':[{'id':'b','type':'concept','title':'结构','body':'合成验证，不是用户课程。'}],'exercises':copy.deepcopy(items)}]}
   service.create_plan_line(package['plan_line']);src=workspace/(theme+'.json');src.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');course=service.import_course_package(src);opened=service.open_course_study(course['course_id'],'annotation-'+theme)
   context=browser.new_context(viewport={'width':1920,'height':1080})
   context.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:"+json.dumps(theme)+",custom_themes:[],revision:{clock:1,source:'test'}}));window.__audio=[];window.Audio=class{constructor(src){this.src=src;window.__audio.push(this)}load(){queueMicrotask(()=>this.oncanplay?.())}play(){return Promise.resolve()}pause(){}}")
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.goto(f'http://127.0.0.1:{server.server_address[1]}/#/english/'+opened['study']['id'])
   for i,row in enumerate(items):
    if i:
     page.get_by_label('打开课程目录',exact=True).click();page.locator('.english-directory li').nth(i).get_by_role('button').click()
    expect(page.get_by_role('heading',name=row['prompt'],exact=True)).to_be_visible()
    page.get_by_label('第 1 个单词',exact=True).press('Control+Semicolon');expect(page.locator('.english-breakdown')).to_be_visible()
    assert page.locator('.english-metadata-status').count()==0
    assert page.get_by_role('button',name='重试辅助信息',exact=True).count()==0
    if i<2:assert page.locator('.part-role').count()==0 and page.locator('.sentence-part').count()==1
    else:expect(page.locator('.part-role')).to_have_text(['主语','谓语','宾语'])
    for width,height in [(1920,1080),(960,720),(720,720)]:
     page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(100);page.locator('.english-stage').evaluate('el=>el.scrollTop=0')
     initial=page.locator('.english-main-actions button').evaluate("el=>({bottom:el.getBoundingClientRect().bottom,footer:document.querySelector('.english-training-footer').getBoundingClientRect().top})")
     assert initial['bottom']<=initial['footer']+1,initial
     data=page.locator('.english-breakdown').evaluate("""el=>({box:el.getBoundingClientRect().toJSON(),groups:[...el.querySelectorAll('.sentence-part')].map(p=>[...p.querySelectorAll('.part-word strong')].map(w=>w.getBoundingClientRect().top)),posGroups:[...el.querySelectorAll('.sentence-part')].map(p=>[...p.querySelectorAll('.part-word em')].map(w=>w.getBoundingClientRect().top)),viewport:innerWidth,overflow:document.documentElement.scrollWidth})""")
     assert data['box']['x']>=-1 and data['box']['right']<=width+1,data
     assert data['overflow']<=width+1,data
     for tops in [*data['groups'],*data['posGroups']]:
      if tops:assert max(tops)-min(tops)<=1,data
     action=page.locator('.english-main-actions').evaluate("el=>({height:el.getBoundingClientRect().height,buttonHeight:el.querySelector('button').getBoundingClientRect().height})")
     assert action['height']>=action['buttonHeight']-1,action
     page.locator('.english-main-actions button').scroll_into_view_if_needed()
     visible=page.locator('.english-main-actions button').evaluate("el=>{const b=el.getBoundingClientRect(),f=document.querySelector('.english-training-footer').getBoundingClientRect();return {top:b.top,bottom:b.bottom,footerTop:f.top}}")
     assert visible['bottom']<=visible['footerTop']+1,visible
     geometry.append({'theme':theme,'item':row['id'],'width':width,**data,'action':action,'action_visible':visible})
     page.screenshot(path=str(OUT/f'{theme}-{row["id"]}-{width}.png'))
    before=len(page.evaluate('window.__audio'));page.get_by_role('button',name='朗读单词 '+row['english']['target'].split()[0],exact=True).first.click();page.wait_for_function('(n)=>window.__audio.length>n',arg=before)
    checks.append(theme+' '+row['id']+' authored rows aligned at 1920/960/720, no metadata UI, audio action retained')
   context.close()
  browser.close()
 assert 'audio.dictionary.metadata' not in requests,requests
 assert not errors,errors
 result={'ok':True,'checks':checks,'geometry':geometry,'page_errors':errors,'metadata_requests':0,'audio':'mock triggers only, not hearing acceptance','scope':'synthetic isolated only','workspace':str(workspace)}
 (OUT/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in result.items() if k!='geometry'},ensure_ascii=False))
finally:server.shutdown();engine.close();service.audio.provider.close()
