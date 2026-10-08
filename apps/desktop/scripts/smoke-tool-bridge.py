"""Multi-page Tauri IPC simulation + real Python Core. This is NOT a real OS-window test."""
from __future__ import annotations
import asyncio, json
from playwright.async_api import async_playwright, expect
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func
from studyflow.modules.learning.models import CourseStudySession
import smoke_workbench_support as support

async def run():
 errors=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True);context=await browser.new_context(viewport={'width':1520,'height':1000})
  pages={};labels={};windows={};listeners={};counter=0;pin={};fail_writes=False
  async def dispatch(event,payload,target=None):
   for lid,row in list(listeners.items()):
    if row['event']!=event or target and row['label']!=target:continue
    page=pages.get(row['label'])
    if page and not page.is_closed():
     await page.evaluate('(e)=>{void window.__callbacks[e.handler]?.({id:e.id,event:e.event,payload:e.payload})}',{'handler':row['handler'],'id':lid,'event':event,'payload':payload})
  async def destroy(label):
   page=pages.pop(label,None)
   if page and not page.is_closed():await page.close()
   for lid in list(listeners):
    if listeners[lid]['label']==label:listeners.pop(lid,None)
   if label.startswith('tool-'):
    tool=label[5:];windows.pop(tool,None);await dispatch('studyflow-tool-closed',{'tool':tool})
  async def new_page(label,route):
   page=await context.new_page();page.set_default_timeout(8000);pages[label]=page;labels[page]=label
   await page.add_init_script('''window.isTauri=true;window.__callbacks={};let seq=0;
window.__TAURI_INTERNALS__={metadata:{currentWindow:{label:LABEL},currentWebview:{label:LABEL}},transformCallback:(fn)=>{const id=++seq;window.__callbacks[id]=fn;return id},unregisterCallback:id=>delete window.__callbacks[id],invoke:(cmd,args)=>window.__mockInvoke(cmd,args||{})};
window.__TAURI_EVENT_PLUGIN_INTERNALS__={unregisterListener(){}};'''.replace('LABEL',json.dumps(label)))
   page.on('pageerror',lambda e:errors.append(label+': '+str(e)))
   await page.goto(support.url+'/#/'+route)
   return page
  async def invoke(source,command,args):
   nonlocal counter,fail_writes
   label=labels[source['page']]
   if command=='engine_call':
    request=args['request']
    if fail_writes and request['method']=='course.answers.draft.save':return {'id':request['id'],'ok':False,'error':{'code':'DATABASE_READ_ONLY','message':'合成：保存失败','next_action':'合成测试，不写正式数据'}}
    return jsonable_encoder(support.engine.handle(request))
   if command=='tool_windows':return [{'tool':tool,'context':ctx} for tool,ctx in windows.items()]
   if command=='open_tool_window':
    tool=args['tool']
    if tool not in windows:
     windows[tool]=args['context'];ctx=args['context'];await new_page('tool-'+tool,f'tool/{tool}?study={ctx["studyId"]}&course={ctx["courseId"]}&plan={ctx["planId"]}')
    return None
   if command=='set_tool_context':
    for tool in list(windows):windows[tool]=args['context'];await dispatch('studyflow-tool-context',{'tool':tool,'context':args['context']},'tool-'+tool)
    return None
   if command=='close_tool_windows':
    for tool in list(windows):await destroy('tool-'+tool)
    return None
   if command=='plugin:event|listen':
    counter+=1;listeners[counter]={'event':args['event'],'handler':args['handler'],'label':label};return counter
   if command=='plugin:event|unlisten':listeners.pop(args['eventId'],None);return None
   if command in ('plugin:event|emit','plugin:event|emit_to'):
    await dispatch(args['event'],args.get('payload'),args.get('target',{}).get('label'));return None
   if command=='plugin:window|is_maximized':return False
   if command=='plugin:window|is_always_on_top':return pin.get(label,False)
   if command=='plugin:window|set_always_on_top':pin[label]=args['alwaysOnTop'];return None
   if command=='plugin:window|close':await dispatch('tauri://close-requested',None,label);return None
   if command=='plugin:window|destroy':asyncio.create_task(destroy(label));return None
   if command in ('plugin:window|minimize','plugin:window|toggle_maximize','plugin:window|start_dragging'):return None
   raise AssertionError('Unexpected synthetic IPC: '+command)
  await context.expose_binding('__mockInvoke',invoke)
  try:
   main=await new_page('main','course/'+support.courses[0]);await expect(main.get_by_role('heading',name='合成课程1',exact=True)).to_be_visible()
   await main.get_by_role('button',name='打开答题与笔记',exact=True).click()
   await main.get_by_role('tab',name='笔记',exact=False).click();await main.get_by_role('button',name='当前标签操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
   async def wait_window(tool,course=1):
    for _ in range(100):
     if 'tool-'+tool in pages:break
     await asyncio.sleep(.05)
    page=pages['tool-'+tool];await expect(page.get_by_role('heading',name='合成课程'+str(course),exact=True)).to_be_visible();return page
   notes=await wait_window('notes');await notes.get_by_role('button',name='＋ 写笔记',exact=True).click();await notes.get_by_role('textbox',name='笔记：计划',exact=True).fill('跨窗共享的一份计划笔记。')
   await expect(main.get_by_role('heading',name='笔记已在独立窗口',exact=True)).to_be_visible()
   await main.get_by_role('tab',name='练习',exact=False).click();await main.get_by_role('button',name='当前标签操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click();exercises=await wait_window('exercises')
   await expect(notes.get_by_label('关联知识点')).to_have_count(1);await notes.get_by_label('关联知识点').select_option('2')
   await expect(exercises.get_by_label('浏览知识点')).to_have_count(1)
   for i in range(3):
    await exercises.get_by_label('浏览知识点').select_option(str(i));await exercises.get_by_role('textbox').fill('独立窗口作答'+str(i+1))
   with support.service.session() as db:assert db.scalar(select(func.count()).select_from(CourseStudySession))==1
   await main.get_by_role('button',name='下一知识点 →',exact=True).click();await expect(main.locator('.study-unit-heading .eyebrow')).to_have_text('知识点 02 / 3');await main.get_by_role('button',name='下一知识点 →',exact=True).click();await expect(main.locator('.study-unit-heading .eyebrow')).to_have_text('知识点 03 / 3');await main.get_by_role('button',name='提交并完成本次学习 →',exact=True).click()
   await expect(exercises.locator('.waiting-note')).to_be_visible()
   queued=support.service.agent_queue()['waiting_review'];assert len(queued)==3 and len({x['study_session_id'] for x in queued})==1
   await main.get_by_role('button',name='← 合成 · 连续学习计划',exact=True).click();await main.locator('.path-list li').filter(has=main.get_by_role('heading',name='合成课程2',exact=True)).get_by_role('button',name='进入课程 →',exact=True).click()
   await expect(notes.get_by_role('heading',name='合成课程2',exact=True)).to_be_visible();await expect(exercises.get_by_role('heading',name='合成课程2',exact=True)).to_be_visible()
   await expect(notes.get_by_role('textbox',name='笔记：计划',exact=True)).to_have_value('跨窗共享的一份计划笔记。')
   await main.locator('.legacy-teaching-content p').first.evaluate('(el)=>{const s=window.getSelection(),r=document.createRange();r.selectNodeContents(el);s.removeAllRanges();s.addRange(r);el.dispatchEvent(new MouseEvent("mouseup",{bubbles:true}))}')
   await main.get_by_role('button',name='≡ 记入计划笔记',exact=True).click();await expect(notes.locator('.notebook-quote')).to_contain_text('课程2的冻结学习正文')
   await notes.get_by_role('button',name='放回侧栏 ↙',exact=True).click();await expect(main.locator('.tool-detached-placeholder').filter(has_text='笔记已在独立窗口')).to_have_count(0)
   await main.get_by_role('tab',name='笔记',exact=False).click();await expect(main.get_by_role('textbox',name='笔记：计划',exact=True)).to_have_value('跨窗共享的一份计划笔记。')
   assert len(support.service.plan_notebook(support.plan.id)['blocks'])==2
   fail_writes=True;await exercises.get_by_role('textbox').fill('模拟不能保存的作答');await exercises.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
   await expect(exercises.get_by_role('alertdialog')).to_be_visible();await exercises.screenshot(path=str(support.WORKSPACE/'06-save-failure-discard-dialog.png'),full_page=True);await exercises.get_by_role('button',name='不保存并退出',exact=True).click()
   for _ in range(100):
    if 'exercises' not in windows:break
    await asyncio.sleep(.05)
   assert 'exercises' not in windows
   fail_writes=False;await main.get_by_role('tab',name='练习',exact=False).click();await main.get_by_role('button',name='当前标签操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
   exercises=await wait_window('exercises',2);await expect(exercises.get_by_role('button',name='恢复',exact=True)).to_be_visible();await exercises.get_by_role('button',name='恢复',exact=True).click();await expect(exercises.get_by_role('textbox')).to_have_value('模拟不能保存的作答');await exercises.get_by_role('button',name='重试保存',exact=True).click();await expect(exercises.get_by_role('button',name='重试保存',exact=True)).to_have_count(0)
   # Main navigation with a failed peer must not suspend that peer permanently.
   fail_writes=True;await exercises.get_by_role('textbox').fill('主窗离开期间保留的作答')
   await main.get_by_role('button',name='← 合成 · 连续学习计划',exact=True).click()
   await expect(main.get_by_role('alertdialog')).to_be_visible();await main.screenshot(path=str(support.WORKSPACE/'07-main-discard-dialog.png'),full_page=True);await main.get_by_role('button',name='不保存并离开',exact=True).click()
   await expect(main.get_by_role('heading',name='合成 · 连续学习计划',exact=True)).to_be_visible()
   fail_writes=False;await exercises.get_by_role('button',name='重试保存',exact=True).click()
   await expect(exercises.get_by_role('textbox')).to_be_enabled();await exercises.get_by_role('textbox').fill('主窗离开后工具仍可继续编辑')
   await main.locator('.path-list li').filter(has=main.get_by_role('heading',name='合成课程2',exact=True)).get_by_role('button',name='进入课程 →',exact=True).click()
   await expect(exercises.get_by_role('textbox')).to_have_value('主窗离开后工具仍可继续编辑')
   await main.screenshot(path=str(support.WORKSPACE/'04-multi-window-main.png'),full_page=True);await exercises.screenshot(path=str(support.WORKSPACE/'05-tool-course.png'),full_page=True)
   # Closing main must flush every live tool then destroy it, even with no focus in that tool.
   await main.get_by_role('button',name='关闭窗口',exact=True).click()
   for _ in range(100):
    if not pages:break
    await asyncio.sleep(.05)
   assert not pages and not windows
   assert not errors,errors
   print(json.dumps({'ok':True,'workspace':str(support.WORKSPACE),'mode':'simulated Tauri IPC; real Vue and Python Core','checks':['one frozen round shared','all course knowledge points browsable in tool','answers from tool submitted atomically by main','course following','excerpt delivered to detached plan notebook','put back without duplicate editors','failed save allows discard exit','reopen offers recovery','main discard navigation keeps peer editable','notes can associate any course knowledge point','main closes all tools'],'console_errors':errors},ensure_ascii=False))
  except Exception:
   for label,page in list(pages.items()):
    if not page.is_closed():
     await page.screenshot(path=str(support.WORKSPACE/('failed-'+label+'.png')),full_page=True)
     print(label,await page.locator('body').inner_text())
   print('PAGE ERRORS:',errors)
   print('EVIDENCE:',support.WORKSPACE)
   raise
  await browser.close()
if __name__=='__main__':
 try:asyncio.run(run())
 finally:support.server.shutdown();support.database.dispose()
