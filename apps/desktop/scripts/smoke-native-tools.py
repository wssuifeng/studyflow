"""Windows release/WebView2 smoke, synthetic data and isolated profile only.
No install, no system environment/registry changes, no learner workspace access.
"""
from __future__ import annotations
import asyncio, json, os, socket, subprocess, time
from pathlib import Path
from urllib.request import urlopen
from playwright.async_api import async_playwright, expect
import smoke_workbench_support as support

async def run():
 root=support.ROOT
 binary=root/'src-tauri/target/release/studyflow-desktop.exe'
 engine=root/'src-tauri/binaries/studyflow-engine.exe'
 assert binary.is_file() and engine.is_file()
 workspace=support.WORKSPACE.resolve()
 assert workspace.is_relative_to((root/'test-results').resolve())
 from native_acceptance_cases import seed, cases
 from native_fault_proxy import build_proxy
 fixture=seed(support.service,support.plan,workspace)
 proxy=build_proxy(workspace,engine)
 # Start with a stale/off-screen tool layout. The real Tauri code must clamp it
 # back to an available monitor before showing the borderless window.
 layout_dir=workspace/'window-state';layout_dir.mkdir(parents=True,exist_ok=True)
 (layout_dir/'tool-window-layout.json').write_text(json.dumps({'notes':{'x':99999,'y':99999,'width':2200,'height':1800}},ensure_ascii=False),encoding='utf-8')
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 env={k:v for k,v in os.environ.items() if not k.startswith(('STUDYFLOW_','WEBVIEW2_'))}
 temp=workspace/'runtime-temp';temp.mkdir()
 env.update(STUDYFLOW_DIAGNOSTICS_DIR=str(workspace/'diagnostics'),STUDYFLOW_WORKSPACE=str(workspace),STUDYFLOW_DATABASE_PATH=str(workspace/'test.db'),STUDYFLOW_ENGINE_PATH=str(proxy.resolve()),STUDYFLOW_REAL_ENGINE=str(engine.resolve()),STUDYFLOW_FAULT_FILE=str(workspace/"fault-notebook-save"),STUDYFLOW_WINDOW_STATE_DIR=str(workspace/'window-state'),WEBVIEW2_USER_DATA_FOLDER=str(workspace/'webview-profile'),WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port} --remote-debugging-address=127.0.0.1',TEMP=str(temp),TMP=str(temp))
 startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
 errors=[];checks=[];browser=None
 with (workspace/'native.log').open('w',encoding='utf-8') as log:
  proc=subprocess.Popen([str(binary)],cwd=workspace,env=env,startupinfo=startup,stdout=log,stderr=log)
  try:
   async with async_playwright() as p:
    deadline=time.monotonic()+25
    while True:
     if proc.poll() is not None:raise RuntimeError(f'Native app exited: {proc.returncode}')
     try:
      with urlopen(f'http://127.0.0.1:{port}/json/version',timeout=.5) as response:json.load(response)
      break
     except Exception:
      if time.monotonic()>deadline:raise
      await asyncio.sleep(.2)
    browser=await p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
    context=browser.contexts[0]
    async def window(label):
     deadline=time.monotonic()+15
     while time.monotonic()<deadline:
      for page in context.pages:
       if page.is_closed():continue
       try:
        actual=await page.evaluate('window.__TAURI_INTERNALS__?.metadata?.currentWindow?.label')
        if actual==label:
         page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)));return page
       except Exception:pass
      await asyncio.sleep(.1)
     raise AssertionError('Native WebView did not appear: '+label)
    main=await window('main')
    await expect(main.get_by_role('heading',name='\u5b66\u4e60\u63a7\u5236\u53f0',exact=True)).to_be_visible()
    # Normal pages use the shared workspace shell: the document stays fixed while the main pane scrolls.
    await main.evaluate('location.hash="/settings"')
    await expect(main.locator('.theme-option').filter(has_text='序光')).to_be_visible()
    await main.locator('.main-content').evaluate('(el)=>el.scrollTo(0,el.scrollHeight)')
    await main.locator('.theme-option').filter(has_text='序光').click()
    await expect(main.locator('html')).to_have_attribute('data-theme-id','sequence-light')
    settings_layout=await main.evaluate('''()=>{const shell=document.querySelector('.app-shell'),sidebar=document.querySelector('.sidebar'),main=document.querySelector('.main-content'),settings=document.querySelector('.theme-settings'),style=el=>el?getComputedStyle(el):null;return {documentHeight:document.documentElement.scrollHeight,viewport:innerHeight,shellHeight:shell?.getBoundingClientRect().height||0,sidebarPosition:style(sidebar)?.position,mainOverflow:style(main)?.overflowY,mainHeight:main?.clientHeight||0,mainScrollHeight:main?.scrollHeight||0,settingsVisible:!!settings&&settings.getBoundingClientRect().bottom>0}}''')
    if settings_layout['documentHeight']>settings_layout['viewport']+2:
     await main.screenshot(path=str(workspace/'native-settings-overflow.png'))
     offenders=await main.evaluate('''()=>[...document.querySelectorAll('body *')].filter(el=>el.getBoundingClientRect().bottom>innerHeight+2 && ['absolute','fixed'].includes(getComputedStyle(el).position)).map(el=>({tag:el.tagName,class:el.className,bottom:el.getBoundingClientRect().bottom,position:getComputedStyle(el).position,overflow:getComputedStyle(el).overflow})).slice(0,30)''')
     (workspace/'native-settings-layout.json').write_text(json.dumps({'layout':settings_layout,'offenders':offenders,'roots':await main.evaluate("()=>({y:scrollY,roots:[document.documentElement,document.body,document.getElementById('app'),document.querySelector('.app-shell')].map(el=>({tag:el.tagName,class:el.className,scroll:el.scrollHeight,client:el.clientHeight,rect:el.getBoundingClientRect().toJSON(),overflow:getComputedStyle(el).overflow,minHeight:getComputedStyle(el).minHeight,height:getComputedStyle(el).height}))})")},ensure_ascii=False,indent=2),encoding='utf-8')
    assert settings_layout['documentHeight']<=settings_layout['viewport']+2,settings_layout
    assert settings_layout['sidebarPosition']=='fixed',settings_layout
    assert settings_layout['mainOverflow'] in ('auto','scroll'),settings_layout
    assert settings_layout['mainScrollHeight']>settings_layout['mainHeight'],settings_layout
    assert settings_layout['settingsVisible'],settings_layout
    checks.append('settings page scrolls inside the main pane after switching to sequence-light')
    await main.locator('.theme-option').filter(has_text='\u767d\u7d2b').click()
    await expect(main.locator('html')).to_have_attribute('data-theme-id','white-violet')
    await main.evaluate('(id)=>{location.hash="/course/"+id}',support.courses[0])
    await main.evaluate('''()=>{window.scrollTo(0,0);const el=document.querySelector('.main-content');el?.scrollTo(0,0)}''')
    await expect(main.get_by_role('heading',name='\u5408\u6210\u77e5\u8bc6\u70b91',exact=True)).to_be_visible()
    await expect(main.locator('.sequence-course-outline')).to_be_visible()
    white_sidebar_position=await main.locator('.learning-shell > .sidebar').evaluate('(el)=>getComputedStyle(el).position')
    assert white_sidebar_position=='fixed',white_sidebar_position
    checks.append('white-violet course uses the shared fixed sidebar and synchronized course outline')
    # The primary native verification must use the adopted sequence-light theme.
    await main.evaluate('location.hash="/settings"')
    await expect(main.locator('.theme-option').filter(has_text='\u5e8f\u5149')).to_be_visible()
    await main.locator('.theme-option').filter(has_text='\u5e8f\u5149').click()
    await expect(main.locator('html')).to_have_attribute('data-theme-id','sequence-light')
    await main.evaluate('(id)=>{location.hash="/course/"+id}',support.courses[0])
    await expect(main.locator('.reader-toolbar .reader-context')).to_have_text('\u5408\u6210\u8bfe\u7a0b1');checks.append('release main WebView loads against isolated workspace in sequence-light')
    await expect(main.locator('.learning-shell > .sidebar')).to_have_css('overflow-y','hidden')
    await expect(main.locator('.learning-shell > .main-content')).to_have_css('overflow-y','hidden')
    await expect(main.locator('.study-material-body')).to_have_css('overflow-y','auto');checks.append('left navigation rail stays fixed while the reading pane scrolls')
    await main.get_by_role('button',name='打开答题与笔记',exact=True).click()
    await main.get_by_role('tab',name='笔记',exact=False).click();await main.get_by_role('button',name='其他工具操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
    notes=await window('tool-notes');await expect(notes.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_be_visible()
    async def native_invoke(page,command):
     return await page.evaluate('(command)=>window.__TAURI_INTERNALS__.invoke(command)',command)
    scale=await native_invoke(notes,'plugin:window|scale_factor')
    inner=await native_invoke(notes,'plugin:window|inner_size')
    outer=await native_invoke(notes,'plugin:window|outer_position')
    monitor=await native_invoke(notes,'plugin:window|current_monitor')
    monitors=await native_invoke(notes,'plugin:window|available_monitors')
    assert isinstance(scale,(int,float)) and scale>0
    assert isinstance(inner,dict) and inner.get('width',0)>0 and inner.get('height',0)>0
    assert isinstance(outer,dict) and isinstance(monitor,dict) and isinstance(monitors,list) and monitors
    mpos=monitor.get('position',{}) or {};msize=monitor.get('size',{}) or {}
    assert mpos.get('x',0)<=outer.get('x',0)<=mpos.get('x',0)+msize.get('width',0)
    assert mpos.get('y',0)<=outer.get('y',0)<=mpos.get('y',0)+msize.get('height',0)
    checks.append(f'native DPI scale {scale:g}, {len(monitors)} monitor(s), stale tool layout clamped to current monitor')
    checks.append('real native notes WebView loads in sequence-light')
    note_editor=notes.get_by_role('textbox',name='连续笔记编辑器',exact=True)
    await expect(note_editor).to_be_visible()
    await notes.locator('.plan-notebook-v2 .card-prose').first.click()
    await notes.keyboard.insert_text('真实原生窗口合成笔记')
    await notes.keyboard.press('Control+s')
    await expect(notes.get_by_text('已保存',exact=False).first).to_be_visible()
    await notes.get_by_role('button',name='知识点范围',exact=True).click()
    await notes.locator('.picker-item').filter(has_text='合成知识点3').click()
    await expect(notes.locator('.scope-button').last).to_contain_text('合成知识点3')
    checks.append('v2 native continuous editor and actual knowledge-point scope picker')
    await notes.locator('.card-prose').first.click();await notes.keyboard.insert_text('子窗第三节记录。'+('\n原生长笔记段落。'*70));await notes.keyboard.press('Control+s')
    await expect(notes.get_by_text('已保存',exact=False).first).to_be_visible()
    await notes.evaluate("""()=>{const root=document.querySelector('.card-prose');const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);const text=walker.nextNode();const r=document.createRange();r.setStart(text,1);r.setEnd(text,4);const selection=getSelection();selection.removeAllRanges();selection.addRange(r)}""")
    await notes.wait_for_timeout(150)
    await notes.locator('.notebook-scroll').evaluate('(el)=>el.scrollTop=250')
    await notes.wait_for_timeout(150)
    async def view_probe(page,label):
     value=await page.evaluate('''()=>({selection:getSelection()?.toString(),active:document.activeElement?.className,editorSelection:document.querySelector('.notebook-document')?.editor?.state?.selection?.toJSON(),editorDoc:document.querySelector('.notebook-document')?.editor?.state?.doc?.toJSON(),views:Object.fromEntries(Object.keys(localStorage).filter(k=>k.endsWith(':v2:view')).map(k=>[k,JSON.parse(localStorage.getItem(k))]))})''')
     (workspace/('native-view-'+label+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    await view_probe(notes,'selected-child')

    await notes.get_by_role('button',name='置顶窗口（失去焦点后仍显示在普通窗口上方）',exact=True).click()
    await expect(notes.get_by_role('button',name='取消窗口置顶',exact=True)).to_have_attribute('aria-pressed','true')
    await main.bring_to_front()
    pinned=await notes.evaluate('window.__TAURI_INTERNALS__.invoke("plugin:window|is_always_on_top")')
    assert pinned is True;checks.append('native always-on-top flag remains true after main focus')
    await notes.screenshot(path=str(workspace/'native-notes-sequence-light.png'))
    await view_probe(notes,'before-put-back')
    await notes.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
    await expect(main.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_be_visible()
    await expect(main.locator('.plan-notebook-v2 .scope-button').last).to_contain_text('合成知识点3')
    checks.append('native manual notebook scope transfers back with edit ownership')
    await expect(main.locator('.plan-notebook-v2 .notebook-scroll')).to_have_js_property('scrollTop',250)
    await view_probe(main,'before-editor-focus')
    await main.locator('.notebook-document').evaluate('(el)=>el.editor.view.focus()')
    await view_probe(main,'after-put-back')
    await main.wait_for_function('()=>getSelection()?.toString()==="窗第三"')
    checks.append('native notebook selection and document scroll transfer back with manual scope')

    await main.get_by_role('button',name='知识点范围',exact=True).click()
    await main.locator('.picker-item').filter(has_text='合成知识点1').click()
    await expect(main.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_contain_text('真实原生窗口合成笔记')
    checks.append('native put-back restores shared v2 note; selected scope and hidden entry preserved')
    await main.get_by_role('tab',name='学习工具',exact=False).click();await main.get_by_role('button',name='其他工具操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
    exercises=await window('tool-exercises');await expect(exercises.get_by_role('heading',name='合成课程1',exact=True)).to_be_visible()
    await exercises.get_by_role('textbox').fill('真实窗口的同轮作答')
    await main.get_by_role('button',name='下一知识点 →',exact=True).click()
    await expect(main.locator('.study-unit-heading .eyebrow')).to_contain_text('知识点 02 / 3')
    await expect(exercises.get_by_label('浏览知识点')).to_have_value('0');checks.append('native exercise window shares round but keeps independent knowledge selection')
    # Exercise the new structured renderer against the actual frozen sidecar too.
    await exercises.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
    teaching=json.loads((root.parents[1]/'skills/studyflow-agent/examples/course-package.json').read_text(encoding='utf-8'))
    teaching['plan_line']=support.plan.name
    path=workspace/'native-course-package.json';path.write_text(json.dumps(teaching,ensure_ascii=False),encoding='utf-8')
    from typer.testing import CliRunner
    from studyflow.cli import app
    from studyflow.interfaces.cli import runtime
    previous=runtime.service;runtime.service=lambda:support.service
    try:
     imported=CliRunner().invoke(app,['course','import-package','--file',str(path),'--format','json'])
     assert imported.exit_code==0,imported.output
     imported=json.loads(imported.stdout)
    finally:runtime.service=previous
    await main.evaluate('(id)=>{location.hash="/course/"+id}',imported['course_id'])
    await expect(main.locator('.teaching-block')).to_have_count(7)
    await expect(main.locator('.study-unit-heading h3')).to_have_text('CPU roles')
    checks.append('native frozen Engine renders seven structured teaching components')
    await main.locator('.teaching-practice-links button').click()
    await expect(main.get_by_role('textbox')).to_be_visible()
    await main.get_by_role('textbox').fill('结构化课程原生测试答案')
    await main.get_by_role('button',name='其他工具操作',exact=True).click()
    await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
    exercises=await window('tool-exercises')
    await expect(exercises.get_by_role('textbox')).to_have_value('结构化课程原生测试答案')
    detached_answer=exercises.get_by_role('textbox')
    await detached_answer.focus();await exercises.keyboard.press('Control+a');await exercises.keyboard.press('ArrowLeft');await exercises.keyboard.press('Control+Shift+ArrowRight')
    await expect(detached_answer).to_have_value('结构化课程原生测试答案')
    await expect(main.locator('.study-material')).to_be_visible()
    checks.append('BUG-ANSWER-SELECT-01 detached exercise selection retains independent tool and main reader')

    await main.locator('.teaching-practice-links button').click()
    await expect(exercises.get_by_role('textbox')).to_be_focused()
    checks.append('native component practice link opens and focuses the same detached answer')
    await main.screenshot(path=str(workspace/'native-main-sequence-light.png'))
    await exercises.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
    try:
     await cases(main,window,support.service,support.plan,workspace,fixture,checks,proc.pid)
    except Exception:
     await main.screenshot(path=str(workspace/'native-cases-failure.png'))
     (workspace/'native-cases-failure-body.txt').write_text(await main.locator('body').inner_text(),encoding='utf-8')
     raise
    await main.get_by_role('button',name='关闭窗口',exact=True).click()
    deadline=time.monotonic()+12
    while proc.poll() is None and time.monotonic()<deadline:await asyncio.sleep(.1)
    assert proc.poll()==0,'native main close failed';checks.append('native main close saves and terminates child windows')
    assert not errors,errors
    result={'ok':True,'mode':'actual release Tauri/WebView2; frozen Engine; synthetic isolated data','checks':checks,'page_errors':errors,'workspace':str(workspace)}
    (workspace/'native-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
  except Exception:
   if browser:
    for i,page in enumerate(browser.contexts[0].pages):
     if not page.is_closed():
      try:print(await page.locator('body').inner_text());await page.screenshot(path=str(workspace/f'failed-native-{i}.png'))
      except Exception:pass
   print('NATIVE EVIDENCE:',workspace,'PAGE ERRORS:',errors)
   raise
  finally:
   if proc.poll() is None:proc.terminate();proc.wait(timeout=8)

if __name__=='__main__':
 try:asyncio.run(run())
 finally:support.server.shutdown();support.database.dispose()

