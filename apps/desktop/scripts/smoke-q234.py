"""Q2/Q3/Q4 production Vue + real Core, disposable synthetic data only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
import smoke_workbench_support as f
RESULTS=f.ROOT/'test-results/q234-20261013';RESULTS.mkdir(exist_ok=True)
plan=f.service.create_plan_line('合成 · 新课程体验')
package={'schema':'studyflow.course-package/5','package_id':'q234-browser','plan_line':plan.name,'course':{'title':'合成 · 地址与指令','learning_mode':'general'},'lessons':[{'id':'cpu','title':'地址与指令','blocks':[
 {'id':'core','type':'concept','title':'地址与指令','sections':[{'id':'definition','title':'必要定义','role':'main','body':'程序计数器保存下一条指令的地址。\n\n主干说明始终显示，不需要展开才能理解。'},{'id':'proof','title':'补充推导','role':'supplement','summary':'地址指向位置，不等于该位置保存的指令。','body':'补充解释：地址和指令内容属于不同含义。','children':[{'id':'boundary','title':'边界条件','role':'main','body':'读取内容前需要先确定地址。'}]}]},
 {'id':'continuous','type':'concept','title':'从地址读取内容','body':'这是连续正文的第二部分，不应被厚边框隔开。'},
 {'id':'example','type':'example','title':'读取一个位置','given':'PC指向位置8。','steps':[{'title':'读取','body':'按地址8读取指令。'}],'conclusion':'位置不是指令本身。'},
 {'id':'practice','type':'practice','title':'独立检验','exercise_ids':['q1']}],
 'exercises':[{'id':'q1','title':'PC保存什么','prompt':'PC保存地址还是指令内容？说明原因。','review_reference':{'answer':'PC保存地址。','explanation':'地址用于定位指令，指令内容由其他寄存器保存。','criteria':['区分地址和内容'],'accepted_variants':['下一条指令的位置'],'source':'合成测试'}}]}]}
path=f.WORKSPACE/'q234.json';path.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');imported=f.service.import_course_package(path);cid=imported['course_id']
checks=[];errors=[]
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel='msedge')
  for theme in ('sequence-light','white-violet'):
   context=browser.new_context(viewport={'width':1920,'height':1080})
   context.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify({schema_version:'studyflow.theme-preference/1',selected_theme_id:'"+theme+"',custom_themes:[],revision:{clock:1,source:'q234'}}))")
   page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(10000)
   page.goto(f.url+'/#/course/'+cid+'?plan='+plan.id);page.wait_for_load_state('networkidle')
   expect(page.locator('html')).to_have_attribute('data-theme-id',theme)
   expect(page.get_by_role('heading',name='必要定义',exact=True)).to_be_visible()
   expect(page.locator('.section-supplement')).not_to_have_attribute('open','')
   expect(page.get_by_text('地址指向位置，不等于该位置保存的指令。',exact=True)).to_be_visible()
   geometry=page.locator('.teaching-concept').first.evaluate('(e)=>({border:getComputedStyle(e).borderTopWidth,padding:getComputedStyle(e).paddingTop,bg:getComputedStyle(e).backgroundColor})')
   assert geometry['border']=='0px' and geometry['padding']=='0px' and geometry['bg']=='rgba(0, 0, 0, 0)',geometry
   assert page.locator('.teaching-concept .teaching-kind').count()==0
   page.screenshot(path=str(RESULTS/(theme+'-reading-1920.png')));checks.append(theme+':continuous_reading')
   page.locator('.section-supplement>summary').focus();page.keyboard.press('Enter');expect(page.get_by_text('补充解释：地址和指令内容属于不同含义。',exact=True)).to_be_visible()
   page.locator('.section-supplement>summary').click();page.get_by_role('tab',name='本节大纲',exact=True).click();page.get_by_role('button',name='边界条件',exact=True).click()
   expect(page.get_by_text('读取内容前需要先确定地址。',exact=True)).to_be_visible();checks.append(theme+':outline_reveals_section')
   page.get_by_role('button',name='打开答题与笔记',exact=True).click();expect(page.locator('#workspace-tool-panel')).to_be_visible()
   assert not page.get_by_text('PC保存地址。',exact=True).is_visible()
   page.locator('.answer-reference>summary').click();expect(page.get_by_text('PC保存地址。',exact=True)).to_be_visible();checks.append(theme+':reference_user_view')
   expect(page.locator('.answer-reference-body')).to_contain_text('内容版本 1')
   page.locator('.answer-reference>summary').click();page.locator('.knowledge-question textarea').fill('测试答案')
   f.module.eventually(lambda:f.service.course_answer_sheet(cid)['answers'][0].get('draft') is not None)
   page.screenshot(path=str(RESULTS/(theme+'-tools-1920.png')))
   page.goto(f.url+'/#/plan/'+plan.id);expect(page.locator('[data-course-group="PENDING"]')).to_contain_text('合成 · 地址与指令')
   page.get_by_role('button',name='暂放其他',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible();page.get_by_role('button',name='确认移入',exact=True).click()
   expect(page.locator('[data-course-group="OTHER"]')).to_contain_text('合成 · 地址与指令');page.get_by_role('button',name='恢复到计划',exact=True).click()
   expect(page.locator('[data-course-group="PENDING"]')).to_contain_text('合成 · 地址与指令');checks.append(theme+':groups_hold_restore')
   page.set_viewport_size({'width':900,'height':720});page.screenshot(path=str(RESULTS/(theme+'-groups-900.png')))
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
   context.close()
  browser.close()
 assert not errors,errors
 (RESULTS/'browser-result.json').write_text(json.dumps({'checks':checks,'pageerrors':errors,'workspace':str(f.WORKSPACE),'business_acceptance':'not_evaluated'},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'checks':checks,'pageerrors':errors},ensure_ascii=False))
finally:f.server.shutdown();f.server.server_close();f.engine.close();f.database.dispose()
